"""Tests for the preflight doctor's Python probe (`scripts/doctor_probe.py`).

Each test here exists to prove a check can FAIL. On 2026-07-28 a missing
package and an unreachable fixture produced byte-identical output — empty grid,
no error, nothing in the log — so a preflight check that cannot fail is worse
than no check at all.

Run with the canonical command (pytest is not on PATH):

    cd backend && python -m pytest tests/test_doctor_probe.py
"""

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = REPO_ROOT / "scripts" / "doctor_probe.py"


def _load_probe():
    """Import scripts/doctor_probe.py, which is outside the backend package."""
    spec = importlib.util.spec_from_file_location("five12_doctor_probe", PROBE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


probe = _load_probe()


# ---------------------------------------------------------------------------
# requirements.txt parsing
# ---------------------------------------------------------------------------


def test_parses_pinned_requirements():
    reqs = probe.parse_requirements("Flask==3.1.1\nPyMySQL==1.1.1\n")
    assert [r["name"] for r in reqs] == ["Flask", "PyMySQL"]
    assert reqs[0]["version"] == "3.1.1"


def test_skips_comments_and_commented_out_optional_deps():
    """The Starlink extras are commented out on purpose and must not be
    reported missing."""
    text = (
        "# Optional - Starlink live telemetry (sim mode works without these):\n"
        "# starlink-grpc-tools\n"
        "# grpcio\n"
        "websocket-client==1.9.0\n"
        "\n"
        "# Bluetooth LE\n"
        "bleak==3.0.2\n"
    )
    names = [r["name"] for r in probe.parse_requirements(text)]
    assert names == ["websocket-client", "bleak"]


def test_normalizes_distribution_names():
    assert probe.normalize_dist_name("websocket_client") == "websocket-client"
    assert probe.normalize_dist_name("typing_extensions") == "typing-extensions"
    assert probe.normalize_dist_name("PyMySQL") == "pymysql"


def test_real_requirements_file_parses():
    text = (REPO_ROOT / "backend" / "requirements.txt").read_text(encoding="utf-8")
    reqs = probe.parse_requirements(text)
    names = {r["normalized"] for r in reqs}
    # Fault 3 was websocket-client missing from the app runtime.
    assert "websocket-client" in names
    assert "bleak" in names
    assert "starlink-grpc-tools" not in names  # commented out


# ---------------------------------------------------------------------------
# Fault 3 - a requirement missing from the app interpreter
# ---------------------------------------------------------------------------


def test_package_report_is_clean_when_everything_matches():
    reqs = probe.parse_requirements("Flask==3.1.1\nwebsocket-client==1.9.0\n")
    installed = {"flask": "3.1.1", "websocket-client": "1.9.0"}
    report = probe.package_report(reqs, installed)
    assert report["missing"] == []
    assert report["mismatched"] == []


def test_package_report_lists_what_was_required():
    """The packet-capture check needs to know whether scapy is part of this app
    at all before it has an opinion about Npcap."""
    reqs = probe.parse_requirements("scapy==2.6.1\nFlask==3.1.1\n")
    report = probe.package_report(reqs, {"scapy": "2.6.1", "flask": "3.1.1"})
    assert report["required"] == ["scapy", "flask"]


def test_package_report_FAILS_when_websocket_client_is_absent():
    """The literal fault: the import lives inside a blanket `except Exception`,
    so nothing anywhere said the package was gone."""
    reqs = probe.parse_requirements("Flask==3.1.1\nwebsocket-client==1.9.0\n")
    installed = {"flask": "3.1.1"}
    report = probe.package_report(reqs, installed)
    assert report["missing"] == ["websocket-client"]


def test_package_report_matches_across_name_normalization():
    """`websocket_client` in metadata must satisfy `websocket-client` in
    requirements, or the check cries wolf and gets ignored."""
    reqs = probe.parse_requirements("websocket-client==1.9.0\n")
    installed = {probe.normalize_dist_name("websocket_client"): "1.9.0"}
    assert probe.package_report(reqs, installed)["missing"] == []


def test_package_report_reports_version_drift():
    reqs = probe.parse_requirements("Flask==3.1.1\n")
    report = probe.package_report(reqs, {"flask": "3.1.0"})
    assert report["missing"] == []
    assert report["mismatched"] == [
        {"name": "Flask", "wanted": "3.1.1", "installed": "3.1.0"}
    ]


def test_packet_capture_probe_reports_a_real_answer_or_a_real_error():
    """Whatever scapy's state on this machine, the probe must return a decided
    answer rather than an empty shrug — an unanswerable check is the thing the
    doctor exists to prevent."""
    result = probe.packet_capture_probe()
    assert set(result) == {"available", "use_pcap", "interfaces", "error"}
    if result["available"]:
        assert result["use_pcap"] in (True, False)
        assert result["error"] is None
    else:
        assert result["use_pcap"] is None
        assert result["error"]


# ---------------------------------------------------------------------------
# Fault 4 - .env said DB_PASS, config.py reads DB_PASSWORD
# ---------------------------------------------------------------------------


def test_config_env_keys_marks_defaulted_and_required_reads():
    source = (
        "import os\n"
        "class C:\n"
        "    DB_USER = os.getenv('DB_USER', 'root')\n"
        "    DB_PASSWORD = os.getenv('DB_PASSWORD')\n"
        "    SECRET = os.environ['SECRET_KEY']\n"
        "    OTHER = os.environ.get('OTHER', '1')\n"
    )
    keys = probe.config_env_keys(source)
    assert keys["DB_USER"] is True          # has a default
    assert keys["DB_PASSWORD"] is False     # required
    assert keys["SECRET_KEY"] is False      # os.environ[...] is required
    assert keys["OTHER"] is True


def test_config_env_keys_treats_a_key_as_required_if_any_read_lacks_a_default():
    source = (
        "import os\n"
        "A = os.getenv('K', 'default')\n"
        "B = os.getenv('K')\n"
    )
    assert probe.config_env_keys(source)["K"] is False


def test_key_list_is_derived_from_the_real_config_not_hardcoded():
    """This is the anti-staleness test.

    Hardcoding the key list is the bug that caused fault 4 in the first place:
    someone renames a key and the check keeps validating the old name. Read
    config.py and follow it.
    """
    source = (REPO_ROOT / "backend" / "config.py").read_text(encoding="utf-8")
    keys = probe.config_env_keys(source)
    assert "DB_PASSWORD" in keys
    assert keys["DB_PASSWORD"] is False, "DB_PASSWORD has no default; it is required"
    assert "DB_PASS" not in keys, "config.py does not read DB_PASS - that was the fault"
    assert "FIVE12_BLE_TOOLS" in keys
    assert "FIVE12_BLE_WRITE" in keys


def test_parse_env_file_handles_quotes_exports_and_comments():
    text = (
        "# a comment\n"
        "\n"
        "DB_HOST=localhost\n"
        "export DB_USER=root\n"
        'DB_NAME="five12_website"\n'
        "DB_PASSWORD='p@ss=word'\n"
        "not a key line\n"
    )
    parsed = probe.parse_env_file(text)
    assert parsed["DB_HOST"] == "localhost"
    assert parsed["DB_USER"] == "root"
    assert parsed["DB_NAME"] == "five12_website"
    assert parsed["DB_PASSWORD"] == "p@ss=word"  # '=' inside the value survives
    assert "not a key line" not in parsed


def test_env_report_is_clean_when_every_key_is_present():
    report = probe.env_report(
        config_keys={"DB_PASSWORD": False, "DB_USER": True},
        env_file_keys={"DB_PASSWORD": "secret", "DB_USER": "root"},
        process_env={},
        referenced_keys={"DB_PASSWORD", "DB_USER"},
    )
    assert report["missing_required"] == []
    assert report["unreferenced_in_env_file"] == []


def test_env_report_FAILS_on_the_DB_PASS_rename():
    """Exactly fault 4: the value is right there under the wrong name, and the
    app's error sent the operator hunting for a bad password instead."""
    report = probe.env_report(
        config_keys={"DB_PASSWORD": False},
        env_file_keys={"DB_PASS": "secret"},
        process_env={},
        referenced_keys={"DB_PASSWORD"},
    )
    assert report["missing_required"] == ["DB_PASSWORD"]
    assert report["unreferenced_in_env_file"] == ["DB_PASS"]


def test_env_report_does_not_fail_on_keys_that_have_defaults():
    report = probe.env_report(
        config_keys={"FIVE12_BLE_TOOLS": True},
        env_file_keys={},
        process_env={},
        referenced_keys={"FIVE12_BLE_TOOLS"},
    )
    assert report["missing_required"] == []
    assert report["missing_optional"] == ["FIVE12_BLE_TOOLS"]


def test_env_report_credits_the_process_environment_but_says_so():
    report = probe.env_report(
        config_keys={"DB_PASSWORD": False},
        env_file_keys={},
        process_env={"DB_PASSWORD": "secret"},
        referenced_keys={"DB_PASSWORD"},
    )
    assert report["missing_required"] == []
    assert report["from_process_env"] == [{"key": "DB_PASSWORD", "length": 6}]


def test_env_report_never_carries_a_secret_value():
    secret = "hunter2-not-a-real-password"
    report = probe.env_report(
        config_keys={"DB_PASSWORD": False},
        env_file_keys={"DB_PASSWORD": secret},
        process_env={"DB_PASSWORD": secret},
        referenced_keys={"DB_PASSWORD"},
    )
    assert secret not in repr(report)
    assert report["present"] == [{"key": "DB_PASSWORD", "length": len(secret)}]


def test_scan_env_references_finds_every_read_form():
    sources = {
        "a.py": "os.getenv('FIVE12_BOLERO_HOST')",
        "b.py": 'os.environ["DB_NAME"]',
        "c.py": "os.environ.get('FIVE12_SACN_SRC', '')",
    }
    found = probe.scan_env_references(sources)
    assert found == {"FIVE12_BOLERO_HOST", "DB_NAME", "FIVE12_SACN_SRC"}


def test_scan_env_references_over_the_real_backend_sees_bolero_host():
    """FIVE12_BOLERO_HOST is in backend/.env and is read outside config.py.
    It must not be reported as an unread leftover."""
    sources = {}
    for py in (REPO_ROOT / "backend").rglob("*.py"):
        if "__pycache__" in py.parts or "tests" in py.parts:
            continue
        sources[str(py)] = py.read_text(encoding="utf-8", errors="replace")
    assert "FIVE12_BOLERO_HOST" in probe.scan_env_references(sources)


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------


def test_database_probe_fails_closed_without_a_password():
    """config.py builds no SQLALCHEMY_DATABASE_URI without DB_PASSWORD, so the
    doctor must not report a healthy database either. No network involved."""
    result = probe.database_probe({"DB_HOST": "localhost", "DB_USER": "root"})
    assert result["ok"] is False
    assert "DB_PASSWORD" in result["error"]


def test_database_probe_FAILS_on_an_unreachable_host_without_leaking_the_password():
    """`.invalid` never resolves, so this fails fast and touches no server."""
    result = probe.database_probe(
        {
            "DB_HOST": "five12-doctor-probe.invalid",
            "DB_USER": "root",
            "DB_PASSWORD": "hunter2-not-a-real-password",
            "DB_NAME": "five12_website",
        }
    )
    assert result["ok"] is False
    assert result["database"] is None
    assert "hunter2-not-a-real-password" not in repr(result)
