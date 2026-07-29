"""Python-side probe for the Five12 preflight doctor.

`scripts/doctor.ps1` runs this file with the APP interpreter
(``C:\\Users\\antho\\AppData\\Local\\Programs\\Python\\Python312\\python.exe``)
and parses one JSON object from stdout. Everything that needs to know what the
app's Python actually sees lives here; the PowerShell side owns Windows facts
(adapters, categories, processes) and all presentation.

Three of the six silent faults of 2026-07-28/29 are answered by this file:

* Fault 3 — ``websocket-client`` was missing from the app runtime. The import
  sits inside a function wrapped in a blanket ``except Exception``, so a broken
  install looked exactly like an unreachable fixture. The package check runs
  against the app interpreter specifically, because the interpreter on ``PATH``
  (the one the tests use) has a different package set.
* Fault 4 — ``backend/.env`` had ``DB_PASS`` while ``config.py`` reads
  ``DB_PASSWORD``. The key list is therefore *derived from config.py by
  parsing it*, never hardcoded: a hardcoded list goes stale the next time
  someone renames a key, which is the bug itself.
* The database credentials are exercised for real rather than assumed.

Never print a secret. Values are reported as presence and length only.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Pure helpers — these are what backend/tests/test_doctor_probe.py exercises.
# ---------------------------------------------------------------------------

#: Requirement lines look like ``Flask==3.1.1``. Extras/markers/URLs are not
#: used in this repo's requirements.txt; if one appears we keep the name and
#: drop the pin rather than guessing.
_REQ_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9._-]+)\s*(?:\[[^\]]*\])?\s*(?:==\s*(?P<version>[^\s;#]+))?"
)


def normalize_dist_name(name: str) -> str:
    """PEP 503 normalization: ``websocket-client`` and ``websocket_client`` match."""
    return re.sub(r"[-_.]+", "-", name).strip().lower()


def parse_requirements(text: str) -> list[dict]:
    """Parse requirements.txt into ``[{name, normalized, version}]``.

    Comment lines are skipped, which is load-bearing: the optional Starlink
    dependencies are commented out on purpose and must not be reported missing.
    """
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        line = line.split(" #", 1)[0].strip()
        match = _REQ_RE.match(line)
        if not match:
            continue
        name = match.group("name")
        out.append(
            {
                "name": name,
                "normalized": normalize_dist_name(name),
                "version": match.group("version"),
            }
        )
    return out


def config_env_keys(source: str) -> dict[str, bool]:
    """Map every environment key ``source`` reads to whether it has a default.

    Recognizes ``os.getenv(K)``, ``os.getenv(K, d)``, ``os.environ.get(K[, d])``
    and ``os.environ[K]``. A key read in more than one place is required if any
    single read has no default.

    Parsing rather than hardcoding is the whole point — see fault 4 above.
    """
    tree = ast.parse(source)
    keys: dict[str, bool] = {}

    def record(key: str, has_default: bool) -> None:
        keys[key] = keys.get(key, True) and has_default

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = None
            if isinstance(func, ast.Attribute):
                name = func.attr
            if name in ("getenv", "get") and node.args:
                target = func.value
                is_os_env = (
                    isinstance(target, ast.Name) and target.id == "os"
                ) or (
                    isinstance(target, ast.Attribute) and target.attr == "environ"
                )
                first = node.args[0]
                if is_os_env and isinstance(first, ast.Constant) and isinstance(first.value, str):
                    record(first.value, len(node.args) > 1 or bool(node.keywords))
        elif isinstance(node, ast.Subscript):
            target = node.value
            if isinstance(target, ast.Attribute) and target.attr == "environ":
                index = node.slice
                if isinstance(index, ast.Constant) and isinstance(index.value, str):
                    record(index.value, False)

    return keys


def parse_env_file(text: str) -> dict[str, str]:
    """Parse a dotenv file into key -> value. Values stay in memory only."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key] = value
    return out


def scan_env_references(sources: dict[str, str]) -> set[str]:
    """Every env key name referenced anywhere in ``{path: source}``.

    Used to flag keys that sit in ``.env`` but nothing reads — which is what
    ``DB_PASS`` looked like while the app hunted for a password that was
    right there under the wrong name.
    """
    found: set[str] = set()
    pattern = re.compile(
        r"""(?:os\.getenv|os\.environ\.get|environ\.get)\(\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]"""
        r"""|os\.environ\[\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]\s*\]"""
    )
    for text in sources.values():
        for match in pattern.finditer(text):
            found.add(match.group(1) or match.group(2))
    return found


def env_report(
    config_keys: dict[str, bool],
    env_file_keys: dict[str, str],
    process_env: dict[str, str],
    referenced_keys: set[str] | None = None,
) -> dict:
    """Compare what config.py reads against what backend/.env supplies.

    ``missing_required`` is a FAIL condition on the PowerShell side; the rest
    are WARN or informational. Only key names and value *lengths* cross this
    boundary.
    """
    missing_required = []
    missing_optional = []
    from_process_env = []
    present = []

    for key in sorted(config_keys):
        has_default = config_keys[key]
        if key in env_file_keys:
            present.append({"key": key, "length": len(env_file_keys[key])})
        elif key in process_env:
            from_process_env.append({"key": key, "length": len(process_env[key])})
        elif has_default:
            missing_optional.append(key)
        else:
            missing_required.append(key)

    unreferenced = []
    if referenced_keys is not None:
        for key in sorted(env_file_keys):
            if key not in referenced_keys:
                unreferenced.append(key)

    return {
        "missing_required": missing_required,
        "missing_optional": missing_optional,
        "from_process_env": from_process_env,
        "present": present,
        "unreferenced_in_env_file": unreferenced,
    }


def package_report(requirements: list[dict], installed: dict[str, str]) -> dict:
    """Compare requirements.txt against installed distributions.

    ``installed`` maps normalized distribution name -> version.
    """
    missing = []
    mismatched = []
    for req in requirements:
        actual = installed.get(req["normalized"])
        if actual is None:
            missing.append(req["name"])
        elif req["version"] and actual != req["version"]:
            mismatched.append(
                {"name": req["name"], "wanted": req["version"], "installed": actual}
            )
    return {"missing": missing, "mismatched": mismatched}


# ---------------------------------------------------------------------------
# Impure collection
# ---------------------------------------------------------------------------


def installed_distributions() -> dict[str, str]:
    """Installed distributions by normalized name.

    Metadata, not import: importing pandas/scapy/bleak for real costs seconds
    on every launch. ``--full`` does the real imports instead.
    """
    import importlib.metadata as md

    out: dict[str, str] = {}
    for dist in md.distributions():
        name = dist.metadata["Name"]
        if name:
            out[normalize_dist_name(name)] = dist.version or ""
    return out


#: Distribution name -> module name, only where they differ. Used by --full.
_IMPORT_NAMES = {
    "websocket-client": "websocket",
    "pymysql": "pymysql",
    "flask-sqlalchemy": "flask_sqlalchemy",
    "flask-migrate": "flask_migrate",
    "python-dateutil": "dateutil",
    "python-dotenv": "dotenv",
    "et-xmlfile": "et_xmlfile",
    "typing-extensions": "typing_extensions",
    "markupsafe": "markupsafe",
    "itsdangerous": "itsdangerous",
    "pyyaml": "yaml",
}


def import_failures(requirements: list[dict]) -> list[dict]:
    """Actually import every requirement. Slow — --full only."""
    import importlib

    failures = []
    for req in requirements:
        module = _IMPORT_NAMES.get(req["normalized"], req["normalized"].replace("-", "_"))
        try:
            importlib.import_module(module)
        except Exception as exc:  # noqa: BLE001 - reporting the exception IS the job
            failures.append(
                {"name": req["name"], "module": module, "error": f"{type(exc).__name__}: {exc}"}
            )
    return failures


def database_probe(env: dict[str, str]) -> dict:
    """Connect with the configured credentials and report the database name.

    Mirrors config.py's defaults so that a doctor pass means the app's own
    connection string would work.
    """
    host = env.get("DB_HOST", "localhost")
    user = env.get("DB_USER", "root")
    password = env.get("DB_PASSWORD")
    name = env.get("DB_NAME", "five12_website")

    if not password:
        return {
            "ok": False,
            "error": "DB_PASSWORD is empty; config.py builds no SQLALCHEMY_DATABASE_URI without it",
            "database": None,
            "host": host,
            "user": user,
        }
    try:
        import pymysql

        conn = pymysql.connect(
            host=host, user=user, password=password, database=name, connect_timeout=3
        )
        try:
            cur = conn.cursor()
            cur.execute("SELECT DATABASE(), VERSION()")
            row = cur.fetchone()
        finally:
            conn.close()
        return {
            "ok": True,
            "database": row[0],
            "server_version": row[1],
            "host": host,
            "user": user,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        # Never echo the exception verbatim without stripping: PyMySQL puts the
        # user and host in the message but not the password. Keep it that way.
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "database": None,
            "host": host,
            "user": user,
        }


def subnet_probe(env: dict[str, str]) -> dict:
    """Read configured subnets straight from the database.

    doctor.ps1 prefers GET /api/network/subnets and falls back to this when the
    backend is not up.
    """
    host = env.get("DB_HOST", "localhost")
    user = env.get("DB_USER", "root")
    password = env.get("DB_PASSWORD")
    name = env.get("DB_NAME", "five12_website")
    if not password:
        return {"ok": False, "error": "no DB_PASSWORD", "subnets": []}
    try:
        import pymysql

        conn = pymysql.connect(
            host=host, user=user, password=password, database=name, connect_timeout=3
        )
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT label, cidr, interface_hint, active, ignore_cidrs "
                "FROM network_subnets ORDER BY id"
            )
            rows = cur.fetchall()
        finally:
            conn.close()
        return {
            "ok": True,
            "error": None,
            "subnets": [
                {
                    "label": r[0],
                    "cidr": r[1],
                    "interfaceHint": r[2],
                    "active": bool(r[3]),
                    "ignoreCidrs": r[4],
                }
                for r in rows
            ],
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "subnets": []}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Five12 doctor probe (emits JSON)")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--full", action="store_true", help="really import every requirement")
    args = parser.parse_args(argv)

    root = Path(args.repo_root)
    config_path = root / "backend" / "config.py"
    env_path = root / "backend" / ".env"
    req_path = root / "backend" / "requirements.txt"

    result: dict = {
        "interpreter": sys.executable,
        "python_version": sys.version.split()[0],
        "paths": {
            "config": str(config_path),
            "env": str(env_path),
            "requirements": str(req_path),
        },
        "errors": [],
    }

    requirements = []
    if req_path.exists():
        requirements = parse_requirements(req_path.read_text(encoding="utf-8"))
    else:
        result["errors"].append(f"missing {req_path}")

    result["packages"] = package_report(requirements, installed_distributions())
    result["packages"]["checked"] = len(requirements)
    result["packages"]["import_failures"] = (
        import_failures(requirements) if args.full else None
    )

    config_keys: dict[str, bool] = {}
    if config_path.exists():
        config_keys = config_env_keys(config_path.read_text(encoding="utf-8"))
    else:
        result["errors"].append(f"missing {config_path}")

    env_file_keys: dict[str, str] = {}
    if env_path.exists():
        env_file_keys = parse_env_file(env_path.read_text(encoding="utf-8"))
    else:
        result["errors"].append(f"missing {env_path}")

    sources = {}
    for py in list((root / "backend").rglob("*.py")):
        if "__pycache__" in py.parts or "tests" in py.parts:
            continue
        try:
            sources[str(py)] = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    referenced = scan_env_references(sources)

    result["env"] = env_report(config_keys, env_file_keys, dict(os.environ), referenced)
    result["env"]["config_keys"] = {k: config_keys[k] for k in sorted(config_keys)}
    result["env"]["env_file_exists"] = env_path.exists()

    # The app reads .env through python-dotenv at import time; the doctor must
    # use the same source of truth rather than whatever is in its own shell.
    merged = dict(env_file_keys)
    for key in ("DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME"):
        if key not in merged and key in os.environ:
            merged[key] = os.environ[key]

    result["database"] = database_probe(merged)
    result["subnets"] = subnet_probe(merged)

    json.dump(result, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
