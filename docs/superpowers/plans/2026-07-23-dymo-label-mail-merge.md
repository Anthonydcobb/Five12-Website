# DYMO Label Mail-Merge — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upload `.dymo` templates (named text boxes = variables), then batch-print labels fed by patch-sheet rows or a client-parsed CSV, with per-template remembered mappings and a live merged preview, printing via DYMO Connect's local web service.

**Architecture:** Pure-Python variable extraction + a new `DymoTemplate` model and a small `dymo` blueprint (upload/list/get/mapping/delete). All printing is frontend-direct: a vendored `dymo.connect.framework.js` talks to `https://127.0.0.1:41951`. A `DymoPrintDialog` handles template→source→mapping→preview→print, entered from the patch editor and a new DYMO tab on the Labels page.

**Tech Stack:** Flask/SQLAlchemy/Alembic, pytest; React 19 + Vite, Tailwind v4 tokens; DYMO Connect Framework (vendored JS).

## Global Constraints

- Backend commands use `backend/.venv/Scripts/python.exe`; run pytest from `backend/`: `& .venv\Scripts\python.exe -m pytest tests/ -q`.
- **Migrations apply to BOTH databases**: from `backend/` — `$env:FLASK_APP='app.py'; & .venv\Scripts\python.exe -m flask db upgrade` (MySQL), then `$env:FLASK_CONFIG='desktop'; & .venv\Scripts\python.exe -m flask db upgrade; Remove-Item Env:FLASK_CONFIG` (SQLite). Migration dir is `backend/migrations/`. After any backend run, kill survivor pythons.
- JSON keys camelCase (`labelXml`, `savedMappings`, `createdAt`).
- Frontend uses design tokens only (`bg-surface`, `border-border`, `text-text-muted`, `bg-brand`, `bg-online`, `text-bg`, `bg-warn`…); modals follow the ImportWizard pattern incl. its `readJson` defensive fetch helper (copy it locally).
- No CDN loads — the DYMO framework is vendored into the repo.
- DYMO local service base: `https://127.0.0.1:41951` (verified live on this machine); availability probe endpoint: `/DYMO/DLS/Printing/StatusConnected`.
- No JS test runner exists; frontend tasks end in `npm run build` + a manual checklist executed by the controller/operator.

---

### Task 1: Variable extraction (pure logic)

**Files:**
- Create: `backend/app/dymo_templates.py`
- Test: `backend/tests/test_dymo_templates.py`

**Interfaces:**
- Produces: `extract_variables(label_xml: str) -> list[str]` — named text-object names, document order, de-duplicated; raises `ValueError('invalid label XML')` on unparseable input; returns `[]` when no named text objects (route turns that into a 400).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_dymo_templates.py
import pytest
from app.dymo_templates import extract_variables

SAMPLE = """<?xml version="1.0" encoding="utf-8"?>
<DesktopLabel Version="1">
  <DYMOLabel Version="3">
    <ObjectInfo><TextObject><Name>FixNum</Name><Text>101</Text></TextObject></ObjectInfo>
    <ObjectInfo><TextObject><Name>Uni</Name><Text>1</Text></TextObject></ObjectInfo>
    <ObjectInfo><TextObject><Name></Name><Text>static</Text></TextObject></ObjectInfo>
    <ObjectInfo><BarcodeObject><Name>Code</Name></BarcodeObject></ObjectInfo>
    <ObjectInfo><TextObject><Name>FixNum</Name><Text>dup</Text></TextObject></ObjectInfo>
  </DYMOLabel>
</DesktopLabel>"""

def test_extracts_named_text_objects_in_order_deduped():
    assert extract_variables(SAMPLE) == ["FixNum", "Uni"]

def test_barcode_and_unnamed_objects_ignored():
    assert "Code" not in extract_variables(SAMPLE)

def test_invalid_xml_raises():
    with pytest.raises(ValueError):
        extract_variables("not xml at all <<<")

def test_no_variables_returns_empty():
    xml = '<DesktopLabel><DYMOLabel><ObjectInfo><TextObject><Name></Name></TextObject></ObjectInfo></DYMOLabel></DesktopLabel>'
    assert extract_variables(xml) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& .venv\Scripts\python.exe -m pytest tests/test_dymo_templates.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.dymo_templates'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/dymo_templates.py
"""Pure logic for DYMO label templates: extract the named text objects
(the mail-merge variables) from a .dymo label's XML. No Flask/DB deps."""
import xml.etree.ElementTree as ET


def extract_variables(label_xml):
    try:
        root = ET.fromstring(label_xml)
    except ET.ParseError as exc:
        raise ValueError('invalid label XML') from exc
    seen, out = set(), []
    # Text objects across DYMO's format generations end in 'TextObject'
    # (TextObject, StyledTextObject, ...). Only those carry merge variables.
    for obj in root.iter():
        if not obj.tag.endswith('TextObject'):
            continue
        name_el = obj.find('Name')
        name = (name_el.text or '').strip() if name_el is not None else ''
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& .venv\Scripts\python.exe -m pytest tests/test_dymo_templates.py -q`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/dymo_templates.py backend/tests/test_dymo_templates.py
git commit -m "feat(dymo): extract named text-object variables from label XML"
```

---

### Task 2: DymoTemplate model + migration (both DBs)

**Files:**
- Modify: `backend/app/models.py` (append after `LabelTemplate`)
- Create: migration under `backend/migrations/versions/` (autogenerated)

**Interfaces:**
- Produces: `DymoTemplate` model with `to_dict(include_xml=False)`; table `dymo_templates`.

- [ ] **Step 1: Add the model**

```python
# backend/app/models.py — append near LabelTemplate
class DymoTemplate(db.Model):
    __tablename__ = 'dymo_templates'
    id             = db.Column(db.Integer, primary_key=True)
    name           = db.Column(db.String(120), nullable=False)
    label_xml      = db.Column(db.Text, nullable=False)
    variables      = db.Column(db.JSON, nullable=False)
    # {"patch": {var: canonicalField}, "csv": {var: csvHeader}} — last used
    saved_mappings = db.Column(db.JSON, nullable=True)
    created_at     = db.Column(db.DateTime, nullable=False)

    def to_dict(self, include_xml=False):
        d = {
            'id': self.id,
            'name': self.name,
            'variables': self.variables,
            'savedMappings': self.saved_mappings or {},
            'createdAt': _utc_iso(self.created_at),
        }
        if include_xml:
            d['labelXml'] = self.label_xml
        return d
```

(`_utc_iso` already exists in models.py — reuse it, do not redefine.)

- [ ] **Step 2: Generate + inspect the migration**

Run from `backend/`:
`$env:FLASK_APP='app.py'; & .venv\Scripts\python.exe -m flask db migrate -m "dymo templates"`
Inspect the new file in `backend/migrations/versions/` — it must create only `dymo_templates`. Remove any unrelated autogen noise.

- [ ] **Step 3: Upgrade BOTH databases**

```powershell
& .venv\Scripts\python.exe -m flask db upgrade
$env:FLASK_CONFIG='desktop'; & .venv\Scripts\python.exe -m flask db upgrade; Remove-Item Env:FLASK_CONFIG
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force  # kill survivors
```
Expected: both upgrades apply cleanly.

- [ ] **Step 4: Run the full backend suite (no regressions)**

Run: `& .venv\Scripts\python.exe -m pytest tests/ -q`
Expected: all passing (same count as before + Task 1's 4).

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/migrations/versions/
git commit -m "feat(dymo): DymoTemplate model + migration (applied to MySQL and desktop SQLite)"
```

---

### Task 3: dymo blueprint endpoints

**Files:**
- Create: `backend/app/dymo_routes.py`
- Modify: `backend/app/__init__.py` (register blueprint — follow exactly how the existing `device_routes` blueprint is registered there)
- Test: append to `backend/tests/test_dymo_templates.py`

**Interfaces:**
- Consumes: `extract_variables` (Task 1), `DymoTemplate` (Task 2)
- Produces routes: `POST /api/dymo-templates`, `GET /api/dymo-templates`,
  `GET /api/dymo-templates/<id>`, `PUT /api/dymo-templates/<id>/mapping`,
  `DELETE /api/dymo-templates/<id>`.

- [ ] **Step 1: Write the failing endpoint tests**

```python
# append to backend/tests/test_dymo_templates.py
import io, json as _json

def _upload(client, xml=SAMPLE, name='Fixture Tag'):
    return client.post('/api/dymo-templates',
                       data={'file': (io.BytesIO(xml.encode()), 'tag.dymo'),
                             'name': name},
                       content_type='multipart/form-data')

def test_upload_and_list_roundtrip(client, db):
    r = _upload(client)
    assert r.status_code == 201
    body = r.get_json()
    assert body['name'] == 'Fixture Tag'
    assert body['variables'] == ['FixNum', 'Uni']
    lst = client.get('/api/dymo-templates').get_json()
    assert any(t['id'] == body['id'] for t in lst)
    assert 'labelXml' not in lst[0]
    one = client.get(f"/api/dymo-templates/{body['id']}").get_json()
    assert one['labelXml'].startswith('<?xml')

def test_upload_rejects_no_variables(client, db):
    xml = '<DesktopLabel><DYMOLabel/></DesktopLabel>'
    r = _upload(client, xml=xml, name='empty')
    assert r.status_code == 400
    assert 'named' in r.get_json()['error']

def test_upload_rejects_bad_xml(client, db):
    assert _upload(client, xml='<<<', name='bad').status_code == 400

def test_saved_mapping_put_and_merge(client, db):
    tid = _upload(client, name='MapMe').get_json()['id']
    r = client.put(f'/api/dymo-templates/{tid}/mapping',
                   json={'source': 'patch', 'mapping': {'FixNum': 'fixture'}})
    assert r.status_code == 200
    r = client.put(f'/api/dymo-templates/{tid}/mapping',
                   json={'source': 'csv', 'mapping': {'Uni': 'Universe Col'}})
    got = client.get(f'/api/dymo-templates/{tid}').get_json()['savedMappings']
    assert got == {'patch': {'FixNum': 'fixture'}, 'csv': {'Uni': 'Universe Col'}}

def test_delete(client, db):
    tid = _upload(client, name='Gone').get_json()['id']
    assert client.delete(f'/api/dymo-templates/{tid}').status_code == 200
    assert all(t['id'] != tid for t in client.get('/api/dymo-templates').get_json())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& .venv\Scripts\python.exe -m pytest tests/test_dymo_templates.py -q`
Expected: new tests FAIL with 404/405 (routes absent); Task 1 tests still pass.

- [ ] **Step 3: Implement the blueprint**

```python
# backend/app/dymo_routes.py
from datetime import datetime

from flask import Blueprint, jsonify, request

from . import db
from .models import DymoTemplate
from .dymo_templates import extract_variables

dymo = Blueprint('dymo', __name__, url_prefix='/api/dymo-templates')


@dymo.post('')
def upload_template():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    f = request.files['file']
    xml = f.read().decode('utf-8', errors='replace')
    try:
        variables = extract_variables(xml)
    except ValueError:
        return jsonify({'error': 'Not a valid DYMO label file'}), 400
    if not variables:
        return jsonify({'error': 'template has no named variables — name the '
                                 'text objects in DYMO Connect'}), 400
    name = (request.form.get('name') or f.filename or 'Untitled').rsplit('.', 1)[0][:120]
    t = DymoTemplate(name=name, label_xml=xml, variables=variables,
                     created_at=datetime.utcnow())
    db.session.add(t)
    db.session.commit()
    return jsonify(t.to_dict()), 201


@dymo.get('')
def list_templates():
    ts = DymoTemplate.query.order_by(DymoTemplate.name).all()
    return jsonify([t.to_dict() for t in ts])


@dymo.get('/<int:tid>')
def get_template(tid):
    return jsonify(DymoTemplate.query.get_or_404(tid).to_dict(include_xml=True))


@dymo.put('/<int:tid>/mapping')
def save_mapping(tid):
    t = DymoTemplate.query.get_or_404(tid)
    data = request.get_json(force=True) or {}
    source, mapping = data.get('source'), data.get('mapping')
    if source not in ('patch', 'csv') or not isinstance(mapping, dict):
        return jsonify({'error': "source must be 'patch'|'csv' with a mapping dict"}), 400
    merged = dict(t.saved_mappings or {})
    merged[source] = mapping
    t.saved_mappings = merged
    db.session.commit()
    return jsonify(t.to_dict())


@dymo.delete('/<int:tid>')
def delete_template(tid):
    t = DymoTemplate.query.get_or_404(tid)
    db.session.delete(t)
    db.session.commit()
    return jsonify({'deleted': tid})
```

Register in `backend/app/__init__.py` next to the existing device blueprint
registration (same import/register pattern):

```python
from .dymo_routes import dymo
app.register_blueprint(dymo)
```

- [ ] **Step 4: Run the full backend suite**

Run: `& .venv\Scripts\python.exe -m pytest tests/ -q`
Expected: all passing (prior count + 9 dymo tests total).

- [ ] **Step 5: Commit**

```bash
git add backend/app/dymo_routes.py backend/app/__init__.py backend/tests/test_dymo_templates.py
git commit -m "feat(dymo): template upload/list/get/mapping/delete endpoints"
```

---

### Task 4: Vendor the DYMO framework + JS service wrapper

**Files:**
- Create: `app/src/vendor/dymo.connect.framework.js` (downloaded)
- Create: `app/src/lib/dymo.js`

**Interfaces:**
- Produces (all async, lazy-loading the vendored framework on first use):
  - `dymoReady() -> Promise<boolean>` — service probe (`StatusConnected`)
  - `getPrinters() -> Promise<string[]>` — label-writer printer names
  - `renderPreview(labelXml, values: Record<string,string>) -> Promise<string>` — base64 PNG of the label with `values` applied via `setObjectText`
  - `printMerge(printerName, labelXml, records: Record<string,string>[]) -> Promise<void>` — LabelSetBuilder batch print, one label per record

- [ ] **Step 1: Vendor the framework**

Download the official file from the DYMO GitHub repo (record the commit in the commit message):

```bash
curl -L -o app/src/vendor/dymo.connect.framework.js https://raw.githubusercontent.com/dymosoftware/dymo-connect-framework/master/dymo.connect.framework.js
```
Sanity: file is non-trivial JS (>100 KB) and contains `dymo.label.framework`.
Note the upstream commit: `curl -s https://api.github.com/repos/dymosoftware/dymo-connect-framework/commits/master` → record the `sha` in the commit message.

- [ ] **Step 2: Write the wrapper**

```javascript
// app/src/lib/dymo.js — thin async wrapper over the vendored framework.
let _fw = null;

async function fw() {
  if (_fw) return _fw;
  await import('../vendor/dymo.connect.framework.js'); // attaches window.dymo
  const f = window.dymo.label.framework;
  await new Promise((res) => f.init(res));
  _fw = f;
  return f;
}

export async function dymoReady() {
  try {
    const f = await fw();
    const env = f.checkEnvironment();
    return !!(env && env.isBrowserSupported && env.isFrameworkInstalled);
  } catch { return false; }
}

export async function getPrinters() {
  const f = await fw();
  return f.getPrinters()
    .filter((p) => p.printerType === 'LabelWriterPrinter')
    .map((p) => p.name);
}

function applyValues(f, labelXml, values) {
  const label = f.openLabelXml(labelXml);
  for (const [name, val] of Object.entries(values)) {
    try { label.setObjectText(name, val ?? ''); } catch { /* absent object */ }
  }
  return label;
}

export async function renderPreview(labelXml, values) {
  const f = await fw();
  const label = applyValues(f, labelXml, values);
  return f.renderLabel(label.getLabelXml(), '', '');  // base64 PNG
}

export async function printMerge(printerName, labelXml, records) {
  const f = await fw();
  const set = new f.LabelSetBuilder();
  for (const rec of records) {
    const r = set.addRecord();
    for (const [name, val] of Object.entries(rec)) r.setText(name, val ?? '');
  }
  f.printLabel(printerName, '', labelXml, set.toString());
}
```

- [ ] **Step 3: Verify it compiles**

Run from `app/`: `npm run build`
Expected: build succeeds (framework is imported lazily; no test runner exists).

- [ ] **Step 4: Commit**

```bash
git add app/src/vendor/dymo.connect.framework.js app/src/lib/dymo.js
git commit -m "feat(dymo): vendor DYMO Connect framework (upstream <sha>) + async wrapper"
```

---

### Task 5: DymoPrintDialog component

**Files:**
- Create: `app/src/components/DymoPrintDialog.jsx`

**Interfaces:**
- Consumes: Task 3 endpoints; Task 4 wrapper (`dymoReady`, `getPrinters`, `renderPreview`, `printMerge`).
- Produces: `DymoPrintDialog({ patchRows, selectedRows, onClose })` — `patchRows` = array of canonical patch-row objects or `null` (CSV-only mode); `selectedRows` = subset or `[]`.

Patch-source columns are the canonical patch fields:
`['set','fixture','universe','address','endAddress','type','channelCount','location','wattage','weight','firmware','notes']`.

- [ ] **Step 1: Implement the dialog**

```jsx
// app/src/components/DymoPrintDialog.jsx
import React, { useEffect, useMemo, useState } from 'react';
import { dymoReady, getPrinters, renderPreview, printMerge } from '../lib/dymo';

const PATCH_FIELDS = ['set','fixture','universe','address','endAddress','type',
  'channelCount','location','wattage','weight','firmware','notes'];
const LAST_PRINTER_KEY = 'five12_dymo_printer';

async function readJson(res) {                      // same helper as ImportWizard
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { /* non-JSON */ }
  if (!res.ok) throw new Error((data && data.error) || `Request failed (${res.status})`);
  return data || {};
}

// tiny CSV parse (RFC-4180 quotes) — first row = headers
function parseCsv(text) {
  const rows = []; let row = [], cell = '', q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) {
      if (c === '"' && text[i + 1] === '"') { cell += '"'; i++; }
      else if (c === '"') q = false;
      else cell += c;
    } else if (c === '"') q = true;
    else if (c === ',') { row.push(cell); cell = ''; }
    else if (c === '\n' || c === '\r') {
      if (c === '\r' && text[i + 1] === '\n') i++;
      row.push(cell); cell = '';
      if (row.some(v => v !== '')) rows.push(row);
      row = [];
    } else cell += c;
  }
  row.push(cell);
  if (row.some(v => v !== '')) rows.push(row);
  const [headers, ...data] = rows;
  return { headers: headers || [], rows: data.map(r =>
    Object.fromEntries((headers || []).map((h, i) => [h, r[i] ?? '']))) };
}

// auto-guess: normalized variable name vs normalized column names
const norm = (s) => String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, '');
const GUESS = { fixnum: 'fixture', fix: 'fixture', fixture: 'fixture',
  uni: 'universe', universe: 'universe', addr: 'address', address: 'address',
  add: 'address', endaddr: 'endAddress', type: 'type', fixturetype: 'type',
  ch: 'channelCount', chcount: 'channelCount', loc: 'location',
  location: 'location', position: 'location', watt: 'wattage',
  wattage: 'wattage', weight: 'weight', notes: 'notes', name: 'type' };
function guessMapping(variables, columns) {
  const byNorm = Object.fromEntries(columns.map(c => [norm(c), c]));
  const out = {};
  for (const v of variables) {
    const n = norm(v);
    out[v] = byNorm[n] || byNorm[norm(GUESS[n] || '')] ||
             (GUESS[n] && columns.includes(GUESS[n]) ? GUESS[n] : '') || '';
  }
  return out;
}

export default function DymoPrintDialog({ patchRows, selectedRows, onClose }) {
  const [ready, setReady] = useState(null);          // null=probing
  const [templates, setTemplates] = useState([]);
  const [tpl, setTpl] = useState(null);              // full record incl labelXml
  const [source, setSource] = useState(patchRows ? 'sheet' : 'csv'); // sheet|selection|csv
  const [csv, setCsv] = useState(null);              // {headers, rows}
  const [mapping, setMapping] = useState({});        // {var: column}
  const [printers, setPrinters] = useState([]);
  const [printer, setPrinter] = useState(localStorage.getItem(LAST_PRINTER_KEY) || '');
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const probe = async () => {
    setReady(null);
    const ok = await dymoReady();
    setReady(ok);
    if (ok) {
      const ps = await getPrinters();
      setPrinters(ps);
      if (ps.length && !ps.includes(printer)) setPrinter(ps[0]);
    }
  };
  useEffect(() => { probe(); }, []);
  useEffect(() => {
    fetch('/api/dymo-templates').then(readJson).then(setTemplates).catch(e => setError(e.message));
  }, []);

  const columns = source === 'csv' ? (csv?.headers || []) : PATCH_FIELDS;
  const rows = source === 'csv' ? (csv?.rows || [])
    : source === 'selection' ? selectedRows : (patchRows || []);
  const records = useMemo(() => rows.map(r =>
    Object.fromEntries(Object.entries(mapping)
      .filter(([, col]) => col)
      .map(([v, col]) => [v, String(r[col] ?? '')])))
    .filter(rec => Object.values(rec).some(v => v !== '')), [rows, mapping]);

  const pickTemplate = async (id) => {
    setError(null); setPreview(null);
    if (!id) { setTpl(null); return; }
    try {
      const t = await fetch(`/api/dymo-templates/${id}`).then(readJson);
      setTpl(t);
      const srcKey = source === 'csv' ? 'csv' : 'patch';
      const saved = (t.savedMappings || {})[srcKey];
      setMapping(saved && Object.keys(saved).length
        ? Object.fromEntries(t.variables.map(v => [v, columns.includes(saved[v]) ? saved[v] : '']))
        : guessMapping(t.variables, columns));
    } catch (e) { setError(e.message); }
  };

  // live preview of the first record
  useEffect(() => {
    if (!tpl || !records.length || ready !== true) { setPreview(null); return; }
    let alive = true;
    renderPreview(tpl.labelXml, records[0])
      .then(png => { if (alive) setPreview(png); })
      .catch(() => { if (alive) setPreview(null); });
    return () => { alive = false; };
  }, [tpl, records, ready]);

  const doPrint = async () => {
    if (records.length > 200 &&
        !window.confirm(`Print ${records.length} labels?`)) return;
    setBusy(true); setError(null);
    try {
      await printMerge(printer, tpl.labelXml, records);
      localStorage.setItem(LAST_PRINTER_KEY, printer);
      const srcKey = source === 'csv' ? 'csv' : 'patch';
      await fetch(`/api/dymo-templates/${tpl.id}/mapping`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source: srcKey, mapping }) }).then(readJson);
      onClose();
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50">
      <div className="bg-surface border border-border rounded-lg p-6 w-[min(92vw,760px)] max-h-[88vh] overflow-auto shadow-xl">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold">Print DYMO Labels</h3>
          <button onClick={onClose} className="text-text-muted hover:text-text text-lg leading-none">×</button>
        </div>

        {error && <div className="bg-brand-dim/30 border border-brand/40 text-brand-hi text-sm rounded px-3 py-2 mb-3">{error}</div>}

        {ready === false && (
          <div className="bg-warn/15 border border-warn/40 text-warn text-sm rounded px-3 py-2 mb-3 flex items-center justify-between">
            <span>DYMO Connect isn't running — launch DYMO Connect, then retry.</span>
            <button onClick={probe} className="px-3 py-1 bg-surface-2 hover:bg-border rounded text-text text-xs">Retry</button>
          </div>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
          <label className="block">
            <span className="text-xs text-text-muted mb-1 block">Template</span>
            <select onChange={e => pickTemplate(e.target.value)} value={tpl?.id || ''}
              className="w-full bg-bg border border-border rounded px-2 py-1.5 text-text text-sm">
              <option value="">Choose…</option>
              {templates.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </label>
          <label className="block">
            <span className="text-xs text-text-muted mb-1 block">Source</span>
            <div className="flex gap-2 text-sm">
              {patchRows && <button onClick={() => setSource('sheet')}
                className={`px-3 py-1.5 rounded border ${source==='sheet' ? 'border-brand text-brand-hi' : 'border-border text-text-muted'}`}>
                Sheet ({patchRows.length})</button>}
              {selectedRows?.length > 0 && <button onClick={() => setSource('selection')}
                className={`px-3 py-1.5 rounded border ${source==='selection' ? 'border-brand text-brand-hi' : 'border-border text-text-muted'}`}>
                Selected ({selectedRows.length})</button>}
              <label className={`px-3 py-1.5 rounded border cursor-pointer ${source==='csv' ? 'border-brand text-brand-hi' : 'border-border text-text-muted'}`}>
                CSV…
                <input type="file" accept=".csv" className="hidden" onChange={async e => {
                  const f = e.target.files[0];
                  if (!f) return;
                  setCsv(parseCsv(await f.text()));
                  setSource('csv');
                }} />
              </label>
            </div>
          </label>
        </div>

        {tpl && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
            <table className="text-sm self-start">
              <thead><tr className="text-text-muted text-xs uppercase tracking-wide">
                <th className="text-left py-1">Text box</th><th className="text-left py-1">← Column</th></tr></thead>
              <tbody>
                {tpl.variables.map(v => (
                  <tr key={v} className="border-t border-border">
                    <td className="py-1.5 pr-3 font-mono">{v}</td>
                    <td className="py-1.5">
                      <select value={mapping[v] || ''} onChange={e => setMapping(m => ({ ...m, [v]: e.target.value }))}
                        className="bg-bg border border-border rounded px-2 py-1 text-text">
                        <option value="">— blank —</option>
                        {columns.map(c => <option key={c} value={c}>{c}</option>)}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="bg-bg border border-border rounded-lg p-3 flex items-center justify-center min-h-[140px]">
              {preview
                ? <img alt="label preview" className="max-w-full max-h-[220px]" src={`data:image/png;base64,${preview}`} />
                : <span className="text-text-muted text-xs">preview appears when mapped</span>}
            </div>
          </div>
        )}

        <div className="flex items-center justify-between gap-3">
          <label className="flex items-center gap-2 text-sm text-text-muted">
            Printer
            <select value={printer} onChange={e => setPrinter(e.target.value)}
              className="bg-bg border border-border rounded px-2 py-1 text-text">
              {printers.length === 0 && <option value="">none found</option>}
              {printers.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
          </label>
          <div className="flex gap-3">
            <button onClick={onClose} className="px-4 py-2 bg-surface-2 hover:bg-border rounded text-sm">Cancel</button>
            <button onClick={doPrint}
              disabled={busy || !tpl || !printer || records.length === 0 || ready !== true}
              className="px-4 py-2 bg-online hover:brightness-110 text-bg rounded text-sm font-medium disabled:opacity-40">
              {busy ? 'Printing…' : `Print ${records.length} labels`}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify it compiles**

Run from `app/`: `npm run build` → must succeed.

- [ ] **Step 3: Commit**

```bash
git add app/src/components/DymoPrintDialog.jsx
git commit -m "feat(dymo): DymoPrintDialog — template/source/mapping/live-preview/print"
```

---

### Task 6: Entry points — PatchTab button + Labels-page DYMO section

**Files:**
- Modify: `app/src/components/PatchTab.jsx`
- Create: `app/src/components/DymoSection.jsx`
- Modify: `app/src/pages/LabelsPage.jsx`

**Interfaces:**
- Consumes: `DymoPrintDialog` (Task 5), Task 3 endpoints.
- PatchTab passes `patchRows={rows}` and `selectedRows={rows.filter(r => selectedRowIds.includes(r.id))}`.

- [ ] **Step 1: PatchTab "Labels" button**

In `PatchTab.jsx`: `import DymoPrintDialog from './DymoPrintDialog';`, add
`const [showDymo, setShowDymo] = useState(false);`, and next to the Import/Export buttons add:

```jsx
<button onClick={() => setShowDymo(true)}
  className="px-3 py-1.5 bg-surface-2 hover:bg-border border border-border text-text text-sm rounded">
  Labels
</button>
```

Next to the ImportWizard render block:

```jsx
{showDymo && (
  <DymoPrintDialog
    patchRows={rows}
    selectedRows={rows.filter(r => selectedRowIds.includes(r.id))}
    onClose={() => setShowDymo(false)}
  />
)}
```

- [ ] **Step 2: DymoSection for the Labels page**

```jsx
// app/src/components/DymoSection.jsx
import React, { useEffect, useState } from 'react';
import DymoPrintDialog from './DymoPrintDialog';

async function readJson(res) {
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { /* non-JSON */ }
  if (!res.ok) throw new Error((data && data.error) || `Request failed (${res.status})`);
  return data || {};
}

export default function DymoSection() {
  const [templates, setTemplates] = useState([]);
  const [error, setError] = useState(null);
  const [showPrint, setShowPrint] = useState(false);

  const load = () => fetch('/api/dymo-templates').then(readJson)
    .then(setTemplates).catch(e => setError(e.message));
  useEffect(() => { load(); }, []);

  const upload = async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    setError(null);
    try {
      const fd = new FormData();
      fd.append('file', f);
      await fetch('/api/dymo-templates', { method: 'POST', body: fd }).then(readJson);
      load();
    } catch (err) { setError(err.message); }
    e.target.value = '';
  };

  const remove = async (id) => {
    if (!window.confirm('Delete this DYMO template?')) return;
    try { await fetch(`/api/dymo-templates/${id}`, { method: 'DELETE' }).then(readJson); load(); }
    catch (err) { setError(err.message); }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-text-muted uppercase tracking-wider">DYMO Templates</h2>
        <div className="flex gap-3">
          <label className="text-xs px-3 py-1.5 bg-brand hover:bg-brand-hi text-white rounded cursor-pointer">
            Upload .dymo
            <input type="file" accept=".dymo,.label,.xml" className="hidden" onChange={upload} />
          </label>
          <button onClick={() => setShowPrint(true)}
            className="text-xs px-3 py-1.5 bg-online hover:brightness-110 text-bg rounded font-medium">
            Print from CSV
          </button>
        </div>
      </div>
      {error && <div className="bg-brand-dim/30 border border-brand/40 text-brand-hi text-xs rounded px-3 py-2">{error}</div>}
      {templates.length === 0
        ? <p className="text-text-muted text-sm">No templates yet. Design one in DYMO Connect (name every text box), then upload it here.</p>
        : (
          <div className="space-y-2">
            {templates.map(t => (
              <div key={t.id} className="flex items-center justify-between bg-surface border border-border rounded-lg px-4 py-3">
                <div>
                  <span className="font-medium text-sm">{t.name}</span>
                  <div className="font-mono text-xs text-text-muted mt-0.5">vars: {t.variables.join(', ')}</div>
                </div>
                <button onClick={() => remove(t.id)} className="text-xs px-2 py-1.5 text-text-muted hover:text-brand-hi rounded">×</button>
              </div>
            ))}
          </div>
        )}
      {showPrint && <DymoPrintDialog patchRows={null} selectedRows={[]} onClose={() => setShowPrint(false)} />}
    </div>
  );
}
```

- [ ] **Step 3: Wire into LabelsPage**

Read `app/src/pages/LabelsPage.jsx` first; it has a tab strip ("Design",
"Patch", …). Add a `DYMO` tab following the exact existing tab pattern (state
value, tab button, conditional render of `<DymoSection />`). Do not restyle or
restructure anything else on the page.

- [ ] **Step 4: Verify compile + commit**

Run from `app/`: `npm run build` → must succeed.

```bash
git add app/src/components/DymoSection.jsx app/src/components/DymoPrintDialog.jsx app/src/components/PatchTab.jsx app/src/pages/LabelsPage.jsx
git commit -m "feat(dymo): Labels-page DYMO tab + patch-editor Labels button"
```

---

### Task 7: Live verification (controller/operator, real service)

**Files:** none (manual checklist; fixes fold back into prior tasks' files)

- [ ] **Step 1: Restart backend with the venv python** (new blueprint), refresh the app.
- [ ] **Step 2: Template CRUD** — on Labels → DYMO: upload a real `.dymo` made in DYMO Connect with named boxes; verify variables listed; upload a file with no named boxes → clear 400 message.
- [ ] **Step 3: Patch-source flow** — open a patch sheet → Labels button → pick template → mapping pre-guessed → live preview PNG renders with first row's values → printer listed.
- [ ] **Step 4: Operator test print** — ONE label, real printer. Verify content lands in the right boxes.
- [ ] **Step 5: Remembered mapping** — reopen dialog: mapping pre-filled from the save; change source to CSV, upload a small CSV, map, verify independent csv mapping saves.
- [ ] **Step 6: Service-down path** — quit DYMO Connect service? (optional if disruptive: skip) — else verify the warn banner + Retry works.
- [ ] **Step 7: Commit any fixes** discovered, run full backend suite once more.

---

## Self-Review

**Spec coverage:** upload/store templates + server-side extraction (T1-T3) ✅; both sources incl. client CSV parse (T5) ✅; mapping table + auto-guess + saved_mappings pre-fill + PUT after print (T3, T5) ✅; live re-rendering preview (T5 renderPreview effect) ✅; printer picker + localStorage memory (T5) ✅; 200-label confirm (T5 doPrint) ✅; vendored framework, no CDN (T4) ✅; service probe + retry banner (T5) ✅; both-DB migration (T2) ✅; entry points (T6) ✅; manual verification incl. real test print (T7) ✅; out-of-scope items not built ✅.

**Type consistency:** `extract_variables` (T1) used in T3; `to_dict(include_xml)` keys (`savedMappings`, `labelXml`) match T5's fetches; wrapper exports (T4) match T5 imports; `DymoPrintDialog` props (T5) match T6 call sites.

**Placeholders:** none — every step carries concrete code/commands.

**Note for implementer:** T3's blueprint registration must copy the exact
pattern used for the existing device blueprint in `backend/app/__init__.py`
(read it first). T6 Step 3 requires reading LabelsPage's tab mechanism before
editing.
