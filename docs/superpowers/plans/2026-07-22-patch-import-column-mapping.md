# Smart Patch-Import Column Mapping — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import a foreign patch sheet (`.xlsx`/`.csv`), auto-map its columns onto our `PatchRow` fields with a user-confirmed mapping screen, ignore unmatched columns, and fill derivable address math.

**Architecture:** A pure-Python logic module (`patch_import.py`) does normalization, alias matching, header detection, mapping and derivation with no Flask/DB deps (fully unit-testable). Two thin Flask endpoints wrap it: `/import/analyze` (parse + guess, no writes) and `/import/commit` (apply confirmed mapping + insert rows). A React `ImportWizard` modal drives the two-step flow from the patch editor.

**Tech Stack:** Flask + SQLAlchemy, pandas/openpyxl (already deps), React 19 + Vite, Tailwind v4 design tokens.

## Global Constraints

- Python interpreter for all backend commands: `backend/.venv/Scripts/python.exe` (has pandas, openpyxl, pytest). A bare `python` off PATH lacks them.
- Run tests from `backend/`: `& .venv\Scripts\python.exe -m pytest tests/ -q`.
- Tests use in-memory SQLite via the existing `client`/`db`/`app` fixtures in `backend/tests/conftest.py` (`create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})`).
- JSON API keys are **camelCase** (`endAddress`, `channelCount`, `headerRowIndex`).
- `PatchRow` field mapping: `set`→`set_name`, `endAddress`→`end_address`, `channelCount`→`channel_count`; `universe`/`address`/`endAddress`/`channelCount` are ints, `wattage`/`weight` are strings.
- Frontend uses design tokens (`bg-surface`, `border-border`, `text-text-muted`, `bg-brand`, `bg-online`, etc.) — no raw Tailwind gray/blue.
- Kill stale flask before manual testing: `Get-Process python | Stop-Process -Force`, then start per handoff.
- No JS test runner is configured; frontend task 8 is verified manually in the browser.

---

### Task 1: Canonical fields, normalization & alias matching

**Files:**
- Create: `backend/app/patch_import.py`
- Test: `backend/tests/test_patch_import.py`

**Interfaces:**
- Produces:
  - `CANONICAL_FIELDS: list[str]`
  - `INT_FIELDS: set[str]`, `STR_FIELDS: set[str]`
  - `ALIASES: dict[str, set[str]]`
  - `normalize_header(value) -> str`
  - `guess_field(header: str) -> str | None`
  - `guess_mapping(headers: list[str]) -> dict[str, str | None]`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_patch_import.py
from app.patch_import import normalize_header, guess_field, guess_mapping

def test_normalize_header_strips_punct_and_case():
    assert normalize_header("Fix #") == "fix"
    assert normalize_header("ch. Count") == "ch count"
    assert normalize_header("  DMX Addr ") == "dmx addr"
    assert normalize_header(None) == ""

def test_guess_field_exact_and_alias():
    assert guess_field("Fixture Type") == "type"
    assert guess_field("DMX Addr") == "address"
    assert guess_field("Ch") == "channelCount"
    assert guess_field("Position") == "location"
    assert guess_field("End Add") == "endAddress"

def test_guess_field_ambiguous_calls():
    # bare "Fixture" -> type (model), bare "Fix #"/"Unit" -> fixture number
    assert guess_field("Fixture") == "type"
    assert guess_field("Unit") == "fixture"
    assert guess_field("Dimmer") is None

def test_guess_mapping():
    m = guess_mapping(["Fixture Type", "DMX Addr", "Ch", "Dimmer"])
    assert m == {"Fixture Type": "type", "DMX Addr": "address",
                 "Ch": "channelCount", "Dimmer": None}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& .venv\Scripts\python.exe -m pytest tests/test_patch_import.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.patch_import'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/patch_import.py
"""Pure logic for the smart patch-sheet importer: header detection, column
alias matching, mapping and address derivation. No Flask/DB dependencies."""
import math
import re
from io import BytesIO

CANONICAL_FIELDS = [
    "set", "fixture", "universe", "address", "endAddress", "type",
    "channelCount", "location", "wattage", "weight", "firmware", "notes",
]
INT_FIELDS = {"universe", "address", "endAddress", "channelCount"}
STR_FIELDS = {"set", "fixture", "type", "location", "wattage", "weight",
              "firmware", "notes"}

# Aliases are stored already-normalized (see normalize_header).
ALIASES = {
    "set":          {"set", "group", "sys", "system"},
    "fixture":      {"fix", "fix no", "fixture no", "fixture number", "unit",
                     "unit no", "chan no", "channel no"},
    "universe":     {"universe", "uni", "u", "net"},
    "address":      {"address", "addr", "add", "dmx", "dmx address",
                     "dmx addr", "start", "start address", "patch"},
    "endAddress":   {"end", "end add", "end addr", "end address", "last",
                     "last address", "thru"},
    "type":         {"type", "fixture type", "fixture", "model", "instrument",
                     "instrument type", "gear"},
    "channelCount": {"ch count", "ch cnt", "channel count", "channels",
                     "chans", "ch", "footprint", "dmx footprint", "slots"},
    "location":     {"location", "loc", "position", "pos", "area", "zone",
                     "spot"},
    "wattage":      {"wattage", "watt", "watts", "power", "w"},
    "weight":       {"weight", "wt", "mass", "lbs", "lb", "kg"},
    "firmware":     {"firmware", "fw", "version", "ver"},
    "notes":        {"notes", "note", "comment", "comments", "remark",
                     "remarks", "desc", "description"},
}
_ALL_ALIASES = {a for aliases in ALIASES.values() for a in aliases}


def normalize_header(value) -> str:
    if value is None:
        return ""
    s = str(value).strip().lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)   # punctuation -> space
    return re.sub(r"\s+", " ", s).strip()


def guess_field(header):
    norm = normalize_header(header)
    if not norm:
        return None
    for field in CANONICAL_FIELDS:          # deterministic order
        if norm in ALIASES[field]:
            return field
    return None


def guess_mapping(headers):
    return {h: guess_field(h) for h in headers}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& .venv\Scripts\python.exe -m pytest tests/test_patch_import.py -q`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/patch_import.py backend/tests/test_patch_import.py
git commit -m "feat(import): canonical fields, header normalization and alias matching"
```

---

### Task 2: Header-row detection

**Files:**
- Modify: `backend/app/patch_import.py`
- Test: `backend/tests/test_patch_import.py`

**Interfaces:**
- Consumes: `normalize_header`, `_ALL_ALIASES` (Task 1)
- Produces: `detect_header_row(grid: list[list]) -> int`

- [ ] **Step 1: Write the failing tests**

```python
# append to backend/tests/test_patch_import.py
from app.patch_import import detect_header_row

def test_detect_header_row_first_row():
    grid = [["Fix #", "Uni", "Add", "Fix Type"], ["1", "1", "1", "PAR"]]
    assert detect_header_row(grid) == 0

def test_detect_header_row_with_title_rows_above():
    grid = [
        ["My Show Patch", None, None, None],
        [None, None, None, None],
        ["Fix #", "Universe", "Address", "Fixture Type"],
        ["1", "1", "1", "PAR"],
    ]
    assert detect_header_row(grid) == 2

def test_detect_header_row_fallback_zero():
    grid = [["a", "b"], ["c", "d"]]
    assert detect_header_row(grid) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& .venv\Scripts\python.exe -m pytest tests/test_patch_import.py -k detect_header -q`
Expected: FAIL — `ImportError: cannot import name 'detect_header_row'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to backend/app/patch_import.py
def detect_header_row(grid, scan_limit=15):
    """Return the index of the row whose cells best match known column
    aliases. Ties break to the earliest row; fallback is row 0."""
    best_idx, best_score = 0, 0
    for idx, row in enumerate(grid[:scan_limit]):
        score = sum(1 for cell in row if normalize_header(cell) in _ALL_ALIASES)
        if score > best_score:
            best_score, best_idx = score, idx
    return best_idx
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& .venv\Scripts\python.exe -m pytest tests/test_patch_import.py -k detect_header -q`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/patch_import.py backend/tests/test_patch_import.py
git commit -m "feat(import): detect the header row instead of assuming row 5"
```

---

### Task 3: Integer parsing & address derivation

**Files:**
- Modify: `backend/app/patch_import.py`
- Test: `backend/tests/test_patch_import.py`

**Interfaces:**
- Consumes: `INT_FIELDS`, `STR_FIELDS` (Task 1)
- Produces:
  - `parse_int(value) -> int | None`
  - `clean_str(value) -> str | None`
  - `derive_row(row: dict) -> dict` — returns a new canonical dict with ints
    parsed, strings cleaned, and missing endAddress/channelCount derived.

- [ ] **Step 1: Write the failing tests**

```python
# append to backend/tests/test_patch_import.py
from app.patch_import import parse_int, derive_row

def test_parse_int_handles_floats_and_junk():
    assert parse_int("101") == 101
    assert parse_int(101.0) == 101       # pandas gives floats
    assert parse_int("") is None
    assert parse_int("n/a") is None
    assert parse_int(None) is None

def test_derive_end_from_count():
    r = derive_row({"address": "101", "channelCount": "8"})
    assert r["address"] == 101 and r["channelCount"] == 8
    assert r["endAddress"] == 108

def test_derive_count_from_end():
    r = derive_row({"address": "1", "endAddress": "13"})
    assert r["channelCount"] == 13

def test_derive_does_not_overwrite_provided():
    r = derive_row({"address": "1", "endAddress": "20", "channelCount": "5"})
    assert r["endAddress"] == 20 and r["channelCount"] == 5

def test_clean_str_wattage_float_to_int_string():
    r = derive_row({"wattage": 400.0, "weight": "34.2"})
    assert r["wattage"] == "400" and r["weight"] == "34.2"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& .venv\Scripts\python.exe -m pytest tests/test_patch_import.py -k "parse_int or derive or clean_str" -q`
Expected: FAIL — `ImportError: cannot import name 'parse_int'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to backend/app/patch_import.py
def parse_int(value):
    if value is None:
        return None
    s = str(value).strip()
    if s == "" or s.lower() == "nan":
        return None
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


def clean_str(value):
    if value is None:
        return None
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if value.is_integer():
            value = int(value)
    s = str(value).strip()
    return s or None


def derive_row(row):
    out = {}
    for k in INT_FIELDS:
        out[k] = parse_int(row.get(k))
    for k in STR_FIELDS:
        out[k] = clean_str(row.get(k))
    a, e, c = out.get("address"), out.get("endAddress"), out.get("channelCount")
    if a is not None:
        if e is None and c is not None:
            out["endAddress"] = a + c - 1
        elif c is None and e is not None:
            out["channelCount"] = e - a + 1
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& .venv\Scripts\python.exe -m pytest tests/test_patch_import.py -k "parse_int or derive or clean_str" -q`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/patch_import.py backend/tests/test_patch_import.py
git commit -m "feat(import): int parsing, string cleanup and address derivation"
```

---

### Task 4: Apply mapping to rows (with blank-skip)

**Files:**
- Modify: `backend/app/patch_import.py`
- Test: `backend/tests/test_patch_import.py`

**Interfaces:**
- Consumes: `derive_row`, `CANONICAL_FIELDS` (Tasks 1, 3)
- Produces: `apply_mapping(headers: list[str], data_rows: list[list], mapping: dict) -> list[dict]`
  — one canonical dict per non-blank data row; headers mapped to `None`/`"ignore"` are dropped; on duplicate targets the later column wins.

- [ ] **Step 1: Write the failing tests**

```python
# append to backend/tests/test_patch_import.py
from app.patch_import import apply_mapping

def test_apply_mapping_ignores_unmatched_columns():
    headers = ["Fix Type", "Add", "Ch", "Dimmer"]
    mapping = {"Fix Type": "type", "Add": "address", "Ch": "channelCount",
               "Dimmer": None}
    rows = [["PAR64", "101", "8", "full"]]
    out = apply_mapping(headers, rows, mapping)
    assert out == [{"set": None, "fixture": None, "universe": None,
                    "address": 101, "endAddress": 108, "type": "PAR64",
                    "channelCount": 8, "location": None, "wattage": None,
                    "weight": None, "firmware": None, "notes": None}]

def test_apply_mapping_skips_blank_rows():
    headers = ["Fix Type", "Add"]
    mapping = {"Fix Type": "type", "Add": "address"}
    rows = [["PAR", "1"], [None, None], ["", ""]]
    out = apply_mapping(headers, rows, mapping)
    assert len(out) == 1 and out[0]["type"] == "PAR"

def test_apply_mapping_ignore_keyword():
    headers = ["Add", "Junk"]
    out = apply_mapping(headers, [["5", "x"]], {"Add": "address", "Junk": "ignore"})
    assert out[0]["address"] == 5 and out[0]["type"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& .venv\Scripts\python.exe -m pytest tests/test_patch_import.py -k apply_mapping -q`
Expected: FAIL — `ImportError: cannot import name 'apply_mapping'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to backend/app/patch_import.py
def _row_is_blank(canonical):
    return all(canonical.get(f) in (None, "") for f in CANONICAL_FIELDS)


def apply_mapping(headers, data_rows, mapping):
    results = []
    for cells in data_rows:
        raw = {}
        for idx, header in enumerate(headers):
            field = mapping.get(header)
            if not field or field == "ignore":
                continue
            raw[field] = cells[idx] if idx < len(cells) else None
        canonical = derive_row(raw)
        if _row_is_blank(canonical):
            continue
        results.append(canonical)
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& .venv\Scripts\python.exe -m pytest tests/test_patch_import.py -k apply_mapping -q`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/patch_import.py backend/tests/test_patch_import.py
git commit -m "feat(import): apply confirmed mapping to rows, skip blanks"
```

---

### Task 5: Read xlsx/csv into a raw grid

**Files:**
- Modify: `backend/app/patch_import.py`
- Test: `backend/tests/test_patch_import.py`

**Interfaces:**
- Produces: `read_table(data: bytes, filename: str) -> list[list]` — raw grid with
  no header assumption; empty cells become `None`. Picks CSV vs Excel by filename.

- [ ] **Step 1: Write the failing tests**

```python
# append to backend/tests/test_patch_import.py
import pandas as pd
from io import BytesIO
from app.patch_import import read_table

def _xlsx_bytes(rows):
    bio = BytesIO()
    pd.DataFrame(rows).to_excel(bio, header=False, index=False, engine="openpyxl")
    return bio.getvalue()

def test_read_table_csv():
    data = b"Fix Type,Add,Ch\nPAR64,101,8\n"
    grid = read_table(data, "foreign.csv")
    assert grid[0] == ["Fix Type", "Add", "Ch"]
    assert grid[1][0] == "PAR64"

def test_read_table_xlsx_parity():
    data = _xlsx_bytes([["Fix Type", "Add", "Ch"], ["PAR64", 101, 8]])
    grid = read_table(data, "foreign.xlsx")
    assert grid[0] == ["Fix Type", "Add", "Ch"]
    assert grid[1][0] == "PAR64"

def test_read_table_blank_cells_are_none():
    grid = read_table(b"a,,c\n1,,3\n", "x.csv")
    assert grid[1][1] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& .venv\Scripts\python.exe -m pytest tests/test_patch_import.py -k read_table -q`
Expected: FAIL — `ImportError: cannot import name 'read_table'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to backend/app/patch_import.py
import pandas as pd   # add near the top imports of the module


def read_table(data, filename):
    name = (filename or "").lower()
    bio = BytesIO(data)
    if name.endswith(".csv"):
        df = pd.read_csv(bio, header=None, dtype=object,
                         na_values=[""], keep_default_na=True)
    else:
        df = pd.read_excel(bio, header=None, dtype=object, engine="openpyxl")
    df = df.where(pd.notnull(df), None)
    return df.values.tolist()
```

(Move the `import pandas as pd` to the module's import block at the top; shown here for context.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `& .venv\Scripts\python.exe -m pytest tests/test_patch_import.py -k read_table -q`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/patch_import.py backend/tests/test_patch_import.py
git commit -m "feat(import): read xlsx and csv into a header-less grid"
```

---

### Task 6: `/import/analyze` endpoint

**Files:**
- Modify: `backend/app/routes.py` (add route; ensure `import json` and the
  `patch_import` imports are present near the top)
- Test: `backend/tests/test_patch_import_api.py`

**Interfaces:**
- Consumes: `read_table`, `detect_header_row`, `guess_mapping` (Tasks 1,2,5)
- Produces: `POST /api/patch-sheets/<int:patch_id>/import/analyze` returning
  `{headerRowIndex, theirColumns, suggestedMapping, previewRows, rowCount}`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_patch_import_api.py
import io

def test_analyze_returns_mapping_and_preview(client):
    csv = b"Fixture Type,DMX Addr,Ch,Dimmer\nPAR64,101,8,full\nMac,110,16,\n"
    data = {"file": (io.BytesIO(csv), "foreign.csv")}
    resp = client.post("/api/patch-sheets/1/import/analyze",
                       data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["headerRowIndex"] == 0
    assert body["theirColumns"] == ["Fixture Type", "DMX Addr", "Ch", "Dimmer"]
    assert body["suggestedMapping"] == {"Fixture Type": "type",
        "DMX Addr": "address", "Ch": "channelCount", "Dimmer": None}
    assert body["rowCount"] == 2
    assert body["previewRows"][0]["Fixture Type"] == "PAR64"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& .venv\Scripts\python.exe -m pytest tests/test_patch_import_api.py -q`
Expected: FAIL — 404 (route not registered)

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/routes.py — add near the top with the other imports:
import json
from .patch_import import (read_table, detect_header_row, guess_mapping,
                           apply_mapping)

# add this route (near the existing import_patch_sheet_excel route):
@bp.route('/api/patch-sheets/<int:patch_id>/import/analyze', methods=['POST'])
def analyze_patch_import(patch_id):
    try:
        if 'file' not in request.files:
            return {'error': 'No file uploaded'}, 400
        f = request.files['file']
        grid = read_table(f.read(), f.filename)
        if not grid:
            return {'error': 'The file appears to be empty.'}, 400
        hidx = detect_header_row(grid)
        headers = [('' if c is None else str(c)).strip() for c in grid[hidx]]
        named = [h for h in headers if h]
        data_rows = grid[hidx + 1:]
        mapping = guess_mapping(headers)
        preview = []
        for cells in data_rows[:5]:
            preview.append({
                headers[i]: (cells[i] if i < len(cells) else None)
                for i in range(len(headers)) if headers[i]
            })
        row_count = sum(
            1 for cells in data_rows
            if any(c not in (None, '') for c in cells)
        )
        return jsonify({
            'headerRowIndex': hidx,
            'theirColumns': named,
            'suggestedMapping': {h: mapping.get(h) for h in named},
            'previewRows': preview,
            'rowCount': row_count,
        })
    except Exception as e:
        current_app.logger.exception("Patch import analyze failed")
        return jsonify({'error': str(e)}), 500
```

- [ ] **Step 4: Run test to verify it passes**

Run: `& .venv\Scripts\python.exe -m pytest tests/test_patch_import_api.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes.py backend/tests/test_patch_import_api.py
git commit -m "feat(import): add /import/analyze endpoint (parse + guess mapping)"
```

---

### Task 7: `/import/commit` endpoint

**Files:**
- Modify: `backend/app/routes.py`
- Test: `backend/tests/test_patch_import_api.py`

**Interfaces:**
- Consumes: `read_table`, `apply_mapping` (Tasks 4,5); `PatchRow`, `db`
- Produces: `POST /api/patch-sheets/<int:patch_id>/import/commit` — form fields
  `file`, `mapping` (JSON string), `headerRowIndex` (int); inserts `PatchRow`s;
  returns `{inserted, skipped}`.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_patch_import_api.py
import io, json
from app import db
from app.models import Show, PatchSheet, PatchRow

def _make_patch(db):
    show = Show(name="T")
    db.session.add(show); db.session.commit()
    sheet = PatchSheet(name="U", show_id=show.id)
    db.session.add(sheet); db.session.commit()
    return sheet.id

def test_commit_inserts_rows_with_derivation(client, db):
    pid = _make_patch(db)
    csv = b"Fixture Type,DMX Addr,Ch,Dimmer\nPAR64,101,8,full\n"
    mapping = {"Fixture Type": "type", "DMX Addr": "address",
               "Ch": "channelCount", "Dimmer": None}
    data = {
        "file": (io.BytesIO(csv), "foreign.csv"),
        "mapping": json.dumps(mapping),
        "headerRowIndex": "0",
    }
    resp = client.post(f"/api/patch-sheets/{pid}/import/commit",
                       data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    assert resp.get_json()["inserted"] == 1
    row = PatchRow.query.filter_by(patch_id=pid).one()
    assert row.type == "PAR64"
    assert row.address == 101
    assert row.end_address == 108      # derived
    assert row.channel_count == 8
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& .venv\Scripts\python.exe -m pytest tests/test_patch_import_api.py -k commit -q`
Expected: FAIL — 404 (route not registered)

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/routes.py — add route:
@bp.route('/api/patch-sheets/<int:patch_id>/import/commit', methods=['POST'])
def commit_patch_import(patch_id):
    try:
        if 'file' not in request.files:
            return {'error': 'No file uploaded'}, 400
        f = request.files['file']
        mapping = json.loads(request.form.get('mapping', '{}'))
        header_idx = int(request.form.get('headerRowIndex', 0))
        grid = read_table(f.read(), f.filename)
        if not grid:
            return {'error': 'The file appears to be empty.'}, 400
        headers = [('' if c is None else str(c)).strip()
                   for c in grid[header_idx]]
        data_rows = grid[header_idx + 1:]
        canonical_rows = apply_mapping(headers, data_rows, mapping)
        for row in canonical_rows:
            db.session.add(PatchRow(
                patch_id=patch_id,
                set_name=row.get('set'),
                fixture=row.get('fixture'),
                universe=row.get('universe'),
                address=row.get('address'),
                end_address=row.get('endAddress'),
                type=row.get('type'),
                channel_count=row.get('channelCount'),
                location=row.get('location'),
                wattage=row.get('wattage'),
                weight=row.get('weight'),
                firmware=row.get('firmware'),
                notes=row.get('notes'),
            ))
        db.session.commit()
        non_blank = sum(1 for cells in data_rows
                        if any(c not in (None, '') for c in cells))
        inserted = len(canonical_rows)
        return jsonify({'inserted': inserted,
                        'skipped': max(0, non_blank - inserted)})
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Patch import commit failed")
        return jsonify({'error': str(e)}), 500
```

- [ ] **Step 4: Run the full backend suite to verify pass + no regressions**

Run: `& .venv\Scripts\python.exe -m pytest tests/ -q`
Expected: PASS (previous suite total + the new tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes.py backend/tests/test_patch_import_api.py
git commit -m "feat(import): add /import/commit endpoint (map + insert rows)"
```

---

### Task 8: `ImportWizard` modal + patch-editor wiring

**Files:**
- Create: `app/src/components/ImportWizard.jsx`
- Modify: `app/src/components/PatchTab.jsx` (replace the Import `<label>` with a
  button that opens the wizard; add `showImport` state; render `<ImportWizard>`)
- Manual test asset: `app/sample-foreign-patch.csv` (git-ignored scratch; not committed)

**Interfaces:**
- Consumes: `POST /api/patch-sheets/<patchId>/import/analyze` and `.../import/commit`
- Produces: `ImportWizard({ patchId, onClose, onImported })` — React component.
  `onImported(insertedCount)` is called after a successful commit.

- [ ] **Step 1: Create the ImportWizard component**

```jsx
// app/src/components/ImportWizard.jsx
import React, { useState } from 'react';

const FIELDS = [
  ['set', 'Set'], ['fixture', 'Fix #'], ['universe', 'Universe'],
  ['address', 'Address'], ['endAddress', 'End Addr'], ['type', 'Fixture Type'],
  ['channelCount', 'CH Count'], ['location', 'Location'], ['wattage', 'Wattage'],
  ['weight', 'Weight'], ['firmware', 'Firmware'], ['notes', 'Notes'],
];
const LABEL = Object.fromEntries(FIELDS);

export default function ImportWizard({ patchId, onClose, onImported }) {
  const [file, setFile] = useState(null);
  const [analysis, setAnalysis] = useState(null);   // analyze response
  const [mapping, setMapping] = useState({});       // {header: field|null}
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const analyze = async (f) => {
    setBusy(true); setError(null);
    try {
      const fd = new FormData();
      fd.append('file', f);
      const res = await fetch(`/api/patch-sheets/${patchId}/import/analyze`,
                             { method: 'POST', body: fd });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Analyze failed');
      setAnalysis(data);
      setMapping(data.suggestedMapping || {});
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };

  const onPick = (e) => {
    const f = e.target.files[0];
    if (!f) return;
    setFile(f);
    analyze(f);
  };

  const commit = async () => {
    setBusy(true); setError(null);
    try {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('mapping', JSON.stringify(mapping));
      fd.append('headerRowIndex', String(analysis.headerRowIndex));
      const res = await fetch(`/api/patch-sheets/${patchId}/import/commit`,
                             { method: 'POST', body: fd });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Import failed');
      onImported(data.inserted);
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };

  // duplicate-target detection
  const targets = Object.values(mapping).filter(Boolean);
  const dupes = targets.filter((t, i) => targets.indexOf(t) !== i);

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50">
      <div className="bg-surface border border-border rounded-lg p-6 w-[min(90vw,720px)] max-h-[85vh] overflow-auto shadow-xl">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold">Import Patch Sheet</h3>
          <button onClick={onClose} className="text-text-muted hover:text-text text-lg leading-none">×</button>
        </div>

        {error && (
          <div className="bg-brand-dim/30 border border-brand/40 text-brand-hi text-sm rounded px-3 py-2 mb-3">{error}</div>
        )}

        {!analysis ? (
          <label className="block border border-dashed border-border rounded-lg p-8 text-center cursor-pointer hover:border-muted">
            <div className="text-text-muted text-sm">Choose an .xlsx or .csv patch sheet</div>
            <input type="file" accept=".xlsx,.csv" className="hidden" onChange={onPick} />
          </label>
        ) : (
          <>
            <p className="text-text-muted text-sm mb-3">
              {analysis.rowCount} rows · header row {analysis.headerRowIndex + 1}. Map their columns to yours:
            </p>
            {dupes.length > 0 && (
              <div className="bg-warn/15 border border-warn/40 text-warn text-xs rounded px-3 py-2 mb-3">
                Two columns map to the same field ({[...new Set(dupes)].map(d => LABEL[d]).join(', ')}); the last one wins.
              </div>
            )}
            <table className="w-full text-sm mb-4">
              <thead>
                <tr className="text-text-muted text-xs uppercase tracking-wide">
                  <th className="text-left py-1">Their column</th>
                  <th className="text-left py-1">→ Your column</th>
                  <th className="text-left py-1">Sample</th>
                </tr>
              </thead>
              <tbody>
                {analysis.theirColumns.map(col => (
                  <tr key={col} className="border-t border-border">
                    <td className="py-1.5 pr-3 font-mono">{col}</td>
                    <td className="py-1.5 pr-3">
                      <select
                        value={mapping[col] || 'ignore'}
                        onChange={e => setMapping(m => ({ ...m, [col]: e.target.value === 'ignore' ? null : e.target.value }))}
                        className="bg-bg border border-border rounded px-2 py-1 text-text"
                      >
                        <option value="ignore">— Ignore —</option>
                        {FIELDS.map(([k, lbl]) => <option key={k} value={k}>{lbl}</option>)}
                      </select>
                    </td>
                    <td className="py-1.5 text-text-muted font-mono truncate max-w-[180px]">
                      {String(analysis.previewRows[0]?.[col] ?? '')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="flex justify-end gap-3">
              <button onClick={onClose} className="px-4 py-2 bg-surface-2 hover:bg-border rounded text-sm">Cancel</button>
              <button onClick={commit} disabled={busy}
                className="px-4 py-2 bg-online hover:brightness-110 text-bg rounded text-sm font-medium disabled:opacity-40">
                {busy ? 'Importing…' : `Import ${analysis.rowCount} rows`}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Wire it into PatchTab**

In `app/src/components/PatchTab.jsx`:
1. Add the import at top: `import ImportWizard from './ImportWizard';`
2. Add state near the other `useState`s: `const [showImport, setShowImport] = useState(false);`
3. Replace the existing Import `<label>…</label>` (the `.xlsx`-only file input) with:

```jsx
<button
  onClick={() => setShowImport(true)}
  className="px-3 py-1.5 bg-surface-2 hover:bg-border border border-border text-text text-sm rounded"
>
  Import
</button>
```

4. Delete the now-unused `handleImport` function.
5. Before the closing `</div>` of the component (next to the PatchForm/RepatchForm blocks), add:

```jsx
{showImport && (
  <ImportWizard
    patchId={patchId}
    onClose={() => setShowImport(false)}
    onImported={(n) => { setShowImport(false); alert(`Imported ${n} rows`); window.location.reload(); }}
  />
)}
```

- [ ] **Step 3: Manual verification in the browser**

Create a scratch file `C:\Users\antho\AppData\Local\Temp\claude\...\scratchpad\sample-foreign-patch.csv`:

```
Position,Fixture Type,DMX Addr,Ch,Dimmer
FOH,ARRI SkyPanel S60-C,101,13,50
Box Boom,Astera Titan Tube,201,49,full
```

Start backend + Vite (per handoff, kill stale python first). In the app: Patch → open a show → open/create a patch sheet → **Import**. Verify:
- The wizard shows 3 mapped columns (`Position→Location`, `Fixture Type→Fixture Type`, `DMX Addr→Address`, `Ch→CH Count`) and `Dimmer` set to Ignore.
- Sample column shows real values.
- Click `Import 2 rows` → table reloads with 2 rows; `End Addr` shows 113 and 249 (derived).

- [ ] **Step 4: Commit**

```bash
git add app/src/components/ImportWizard.jsx app/src/components/PatchTab.jsx
git commit -m "feat(import): ImportWizard modal with column-mapping confirm screen"
```

---

## Self-Review

**Spec coverage:**
- Two-step analyze/commit, stateless (file re-sent) — Tasks 6, 7, 8. ✅
- Header detection replaces row-5 assumption — Task 2. ✅
- Alias table + normalization + ambiguity calls — Task 1. ✅
- Derivation (fill missing, never overwrite) — Task 3. ✅
- Ignore unmatched columns / skip blank rows — Task 4. ✅
- xlsx + csv — Task 5. ✅
- Confirm-screen UI with live sample, dupe-target warning, Ignore — Task 8. ✅
- Error handling (empty file, unreadable, rollback) — Tasks 6, 7. ✅
- Out of scope (library-fill, dedupe) — not implemented, as specified. ✅

**Type consistency:** `read_table`, `detect_header_row`, `guess_mapping`,
`apply_mapping` signatures are defined in Tasks 1–5 and consumed unchanged in
Tasks 6–7. JSON keys (`headerRowIndex`, `suggestedMapping`, `theirColumns`,
`previewRows`, `rowCount`) are produced in Task 6 and consumed in Task 8.
`onImported(insertedCount)` defined and used in Task 8.

**Placeholders:** none — every step has concrete code and commands.

**Note for implementer:** confirm `Show`/`PatchSheet` constructor kwargs in
Task 7's `_make_patch` helper match `backend/app/models.py` (`Show(name=…)`,
`PatchSheet(name=…, show_id=…)`); adjust if the column names differ.
