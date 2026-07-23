# DYMO recent CSV sources — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist recently-used CSV sources on the backend so a user can reload one and reprint without re-importing the file, with per-entry delete and an auto-cap.

**Architecture:** New `dymo_csv_sources` table (JSON columns, mirroring `DymoTemplate`) + a second blueprint in `dymo_routes.py` exposing CRUD with upsert-by-name and a 20-entry cap. `DymoPrintDialog.jsx` saves each uploaded CSV, lists recent ones, and loads/deletes them.

**Tech Stack:** Flask 3 + SQLAlchemy 2 + Flask-Migrate/Alembic (MySQL dev, desktop SQLite); React 19 + Vite.

## Global Constraints

- **Migration in the same change as the model, applied to BOTH databases:** `flask db upgrade` (MySQL) and `FLASK_CONFIG=desktop flask db upgrade` (SQLite). A model change without a matching migration 500s the app on restart.
- **Backend interpreter is `backend/.venv/Scripts/python.exe`** — never a bare `python`. Run flask/pytest through it.
- **Kill stale backends after backend changes:** `Get-Process python | Stop-Process -Force` (PowerShell) — a survivor silently reverts data.
- JSON API responses use camelCase keys (`rowCount`, `createdAt`). `row_count` is computed server-side, never trusted from the client.
- Migration head to build on: `e85115f40999`. Branch: `feat/dymo-label-merge`.
- Auto-cap constant = **20**. Upsert key = `name`.

---

### Task 1: Model + migration (`dymo_csv_sources`)

**Files:**
- Modify: `backend/app/models.py` (add `DymoCsvSource` after `DymoTemplate`)
- Create: `backend/migrations/versions/c5f1a2b3d4e6_dymo_csv_sources.py`

**Interfaces:**
- Produces: `DymoCsvSource` model with `to_dict(include_rows=False)` returning `{id, name, headers, rowCount, createdAt}` (+ `rows` when `include_rows`). Consumed by Task 2.

- [ ] **Step 1: Add the model**

In `backend/app/models.py`, immediately after the `DymoTemplate` class (before the `_utc_iso` definition is fine — it's module-level and resolved at call time), add:

```python
class DymoCsvSource(db.Model):
    __tablename__ = 'dymo_csv_sources'
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(200), nullable=False)
    headers    = db.Column(db.JSON, nullable=False)   # ["Fixture ID", "Address", ...]
    rows       = db.Column(db.JSON, nullable=False)    # [{header: value, ...}, ...]
    row_count  = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False)

    def to_dict(self, include_rows=False):
        d = {
            'id': self.id,
            'name': self.name,
            'headers': self.headers,
            'rowCount': self.row_count,
            'createdAt': _utc_iso(self.created_at),
        }
        if include_rows:
            d['rows'] = self.rows
        return d
```

- [ ] **Step 2: Write the migration**

Create `backend/migrations/versions/c5f1a2b3d4e6_dymo_csv_sources.py`:

```python
"""dymo csv sources

Revision ID: c5f1a2b3d4e6
Revises: e85115f40999
Create Date: 2026-07-23 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c5f1a2b3d4e6'
down_revision = 'e85115f40999'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('dymo_csv_sources',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('headers', sa.JSON(), nullable=False),
    sa.Column('rows', sa.JSON(), nullable=False),
    sa.Column('row_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('dymo_csv_sources')
```

- [ ] **Step 3: Apply the migration to BOTH databases**

From `backend/` (PowerShell), kill stale backends first, then upgrade both DBs:

```powershell
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
$env:FLASK_APP='app.py'
& .venv\Scripts\python.exe -m flask db upgrade
$env:FLASK_CONFIG='desktop'
& .venv\Scripts\python.exe -m flask db upgrade
Remove-Item Env:\FLASK_CONFIG
```

Expected: each `flask db upgrade` runs `c5f1a2b3d4e6` with no error; a second run reports "already at head". 

- [ ] **Step 4: Verify the table exists and the model imports**

```powershell
& .venv\Scripts\python.exe -c "from app import create_app, db; from app.models import DymoCsvSource; app=create_app(); ctx=app.app_context(); ctx.push(); print('cols:', [c.name for c in DymoCsvSource.__table__.columns]); print('count:', DymoCsvSource.query.count())"
```

Expected: `cols: ['id', 'name', 'headers', 'rows', 'row_count', 'created_at']` and `count: 0` (no error).

- [ ] **Step 5: Commit**

```bash
cd "/c/Users/antho/OneDrive/Documents/Five12-TheApp"
git add backend/app/models.py backend/migrations/versions/c5f1a2b3d4e6_dymo_csv_sources.py
git commit -m "feat(dymo): DymoCsvSource model + migration (MySQL + desktop SQLite)"
```

---

### Task 2: CRUD API + tests

**Files:**
- Modify: `backend/app/dymo_routes.py` (add a `csv_sources` blueprint)
- Modify: `backend/app/__init__.py` (register it)
- Test: `backend/tests/test_dymo_csv_sources.py`

**Interfaces:**
- Consumes: `DymoCsvSource` (Task 1).
- Produces: `/api/dymo-csv-sources` — `GET ''` (list, no rows), `GET '/<sid>'` (with rows), `POST ''` (upsert-by-name + cap 20), `DELETE '/<sid>'`. Consumed by Task 3.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_dymo_csv_sources.py`:

```python
def _post(client, name='rig.csv', headers=None, rows=None):
    headers = ['A', 'B'] if headers is None else headers
    rows = ([{'A': '1', 'B': 'x'}, {'A': '2', 'B': 'y'}] if rows is None else rows)
    return client.post('/api/dymo-csv-sources',
                       json={'name': name, 'headers': headers, 'rows': rows})

def test_post_inserts_with_server_row_count(client, db):
    r = _post(client, rows=[{'A': '1'}, {'A': '2'}, {'A': '3'}])
    assert r.status_code == 201
    body = r.get_json()
    assert body['name'] == 'rig.csv'
    assert body['rowCount'] == 3          # computed server-side
    assert 'rows' not in body             # list-shape omits rows

def test_list_omits_rows_get_one_includes(client, db):
    sid = _post(client).get_json()['id']
    lst = client.get('/api/dymo-csv-sources').get_json()
    assert any(e['id'] == sid for e in lst)
    assert all('rows' not in e for e in lst)
    one = client.get(f'/api/dymo-csv-sources/{sid}').get_json()
    assert one['rows'] == [{'A': '1', 'B': 'x'}, {'A': '2', 'B': 'y'}]

def test_upsert_by_name_updates_in_place(client, db):
    first = _post(client, name='same.csv', rows=[{'A': '1'}]).get_json()
    second = _post(client, name='same.csv', rows=[{'A': '9'}, {'A': '8'}]).get_json()
    assert second['id'] == first['id']    # same row, updated
    lst = client.get('/api/dymo-csv-sources').get_json()
    assert len([e for e in lst if e['name'] == 'same.csv']) == 1
    assert client.get(f"/api/dymo-csv-sources/{first['id']}").get_json()['rows'] == [{'A': '9'}, {'A': '8'}]

def test_auto_cap_keeps_20_newest(client, db):
    for i in range(21):
        _post(client, name=f'f{i}.csv')
    lst = client.get('/api/dymo-csv-sources').get_json()
    assert len(lst) == 20
    names = {e['name'] for e in lst}
    assert 'f0.csv' not in names          # oldest dropped
    assert 'f20.csv' in names

def test_list_is_newest_first(client, db):
    _post(client, name='old.csv')
    _post(client, name='new.csv')
    lst = client.get('/api/dymo-csv-sources').get_json()
    assert lst[0]['name'] == 'new.csv'

def test_delete(client, db):
    sid = _post(client, name='gone.csv').get_json()['id']
    assert client.delete(f'/api/dymo-csv-sources/{sid}').status_code == 200
    assert all(e['id'] != sid for e in client.get('/api/dymo-csv-sources').get_json())
    assert client.delete(f'/api/dymo-csv-sources/{sid}').status_code == 404

def test_post_validation(client, db):
    assert client.post('/api/dymo-csv-sources', json={'name': '', 'headers': [], 'rows': []}).status_code == 400
    assert client.post('/api/dymo-csv-sources', json={'name': 'x', 'headers': 'no', 'rows': []}).status_code == 400
    assert client.post('/api/dymo-csv-sources', json={'name': 'x', 'headers': [], 'rows': 'no'}).status_code == 400
```

- [ ] **Step 2: Run the tests to verify they fail**

```powershell
cd backend
& .venv\Scripts\python.exe -m pytest tests/test_dymo_csv_sources.py -q
```

Expected: FAIL — 404s on `/api/dymo-csv-sources` (route not registered yet).

- [ ] **Step 3: Add the blueprint**

In `backend/app/dymo_routes.py`, add the imports at the top (`datetime` is already imported; add `desc`) and append a new blueprint after the existing routes:

```python
from sqlalchemy import desc

from .models import DymoTemplate, DymoCsvSource

CSV_SOURCE_CAP = 20

csv_sources = Blueprint('dymo_csv', __name__, url_prefix='/api/dymo-csv-sources')


@csv_sources.get('')
def list_csv_sources():
    ss = (DymoCsvSource.query
          .order_by(desc(DymoCsvSource.created_at), desc(DymoCsvSource.id)).all())
    return jsonify([s.to_dict() for s in ss])


@csv_sources.get('/<int:sid>')
def get_csv_source(sid):
    return jsonify(DymoCsvSource.query.get_or_404(sid).to_dict(include_rows=True))


@csv_sources.post('')
def save_csv_source():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()[:200]
    headers, rows = data.get('headers'), data.get('rows')
    if not name or not isinstance(headers, list) or not isinstance(rows, list):
        return jsonify({'error': 'name (non-empty), headers (list) and rows (list) are required'}), 400

    existing = DymoCsvSource.query.filter_by(name=name).first()
    created = existing is None
    s = existing or DymoCsvSource(name=name)
    s.headers = headers
    s.rows = rows
    s.row_count = len(rows)
    s.created_at = datetime.utcnow()
    if created:
        db.session.add(s)
    db.session.flush()  # assign s.id before the cap query

    # cap: keep the CSV_SOURCE_CAP newest, delete the rest
    stale = (DymoCsvSource.query
             .order_by(desc(DymoCsvSource.created_at), desc(DymoCsvSource.id))
             .offset(CSV_SOURCE_CAP).all())
    for old in stale:
        db.session.delete(old)

    db.session.commit()
    return jsonify(s.to_dict()), (201 if created else 200)


@csv_sources.delete('/<int:sid>')
def delete_csv_source(sid):
    s = DymoCsvSource.query.get_or_404(sid)
    db.session.delete(s)
    db.session.commit()
    return jsonify({'deleted': sid})
```

(Update the existing `from .models import DymoTemplate` line to also import `DymoCsvSource`, as shown.)

- [ ] **Step 4: Register the blueprint**

In `backend/app/__init__.py`, right after the existing DYMO registration (`app.register_blueprint(dymo_bp)`), add:

```python
    from .dymo_routes import csv_sources as dymo_csv_bp
    app.register_blueprint(dymo_csv_bp)
```

- [ ] **Step 5: Run the tests to verify they pass**

```powershell
cd backend
& .venv\Scripts\python.exe -m pytest tests/test_dymo_csv_sources.py -q
```

Expected: all tests PASS, output pristine.

- [ ] **Step 6: Commit**

```bash
cd "/c/Users/antho/OneDrive/Documents/Five12-TheApp"
git add backend/app/dymo_routes.py backend/app/__init__.py backend/tests/test_dymo_csv_sources.py
git commit -m "feat(dymo): recent-CSV-source API (upsert-by-name, cap 20) + tests"
```

---

### Task 3: Dialog — recent CSV list, save-on-upload, load, delete

**Files:**
- Modify: `app/src/components/DymoPrintDialog.jsx`

**Interfaces:**
- Consumes: `/api/dymo-csv-sources` (Task 2). Uses the existing `readJson` helper, `parseCsv`, and `setCsv`/`setSource` state already in the file.

Note: this file was recently changed by the jog+scope work — locate anchors by content, not line numbers.

- [ ] **Step 1: Add recent-CSVs state and loader**

After the existing `csv` state (`const [csv, setCsv] = useState(null);`), add:

```jsx
  const [recentCsvs, setRecentCsvs] = useState([]);
```

With the other `useEffect` mounts (next to the `fetch('/api/dymo-templates')` effect), add a loader and keep a reusable function:

```jsx
  const loadRecentCsvs = () =>
    fetch('/api/dymo-csv-sources').then(readJson).then(setRecentCsvs).catch(() => {});
  useEffect(() => { loadRecentCsvs(); }, []);
```

- [ ] **Step 2: Save each uploaded CSV to the backend**

In the CSV file `<input type="file">` `onChange` handler, after `setCsv(parseCsv(await f.text()))` and `setSource('csv')`, the parsed data is needed to POST. Refactor the handler to keep the parsed result and save it (fire-and-forget). Replace the existing handler body with:

```jsx
                onChange={async e => {
                  const f = e.target.files[0];
                  if (!f) return;
                  const parsed = parseCsv(await f.text());
                  setCsv(parsed);
                  setSource('csv');
                  e.target.value = '';
                  // remember this CSV for reprinting (never blocks printing)
                  fetch('/api/dymo-csv-sources', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: f.name, headers: parsed.headers, rows: parsed.rows }),
                  }).then(readJson).then(loadRecentCsvs).catch(e => console.warn('CSV history save failed:', e));
                }}
```

- [ ] **Step 3: Add load + delete handlers**

Near the other handlers (e.g. after `pickTemplate`), add:

```jsx
  const loadRecentCsv = async (id) => {
    try {
      const full = await fetch(`/api/dymo-csv-sources/${id}`).then(readJson);
      setCsv({ headers: full.headers, rows: full.rows });
      setSource('csv');
    } catch (e) { setError(e.message); }
  };

  const deleteRecentCsv = async (id, ev) => {
    ev.stopPropagation();
    try {
      await fetch(`/api/dymo-csv-sources/${id}`, { method: 'DELETE' }).then(readJson);
      loadRecentCsvs();
    } catch (e) { setError(e.message); }
  };
```

- [ ] **Step 4: Render the Recent CSVs panel**

In the Source area (inside the `Source` `<label>` block, right after the row of source buttons that contains the `CSV…` file input), add a panel shown only when there are entries:

```jsx
            {recentCsvs.length > 0 && (
              <div className="mt-2 border border-border rounded max-h-40 overflow-auto">
                <div className="text-xs text-text-muted px-2 py-1 border-b border-border">Recent CSVs</div>
                {recentCsvs.map(rc => (
                  <div key={rc.id} onClick={() => loadRecentCsv(rc.id)}
                    className="flex items-center justify-between gap-2 px-2 py-1 text-sm cursor-pointer hover:bg-surface-2">
                    <span className="truncate">{rc.name}</span>
                    <span className="flex items-center gap-2 shrink-0">
                      <span className="text-xs text-text-muted">{rc.rowCount} rows · {new Date(rc.createdAt).toLocaleDateString()}</span>
                      <button type="button" aria-label={`delete ${rc.name}`}
                        onClick={(ev) => deleteRecentCsv(rc.id, ev)}
                        className="text-text-muted hover:text-brand-hi leading-none">×</button>
                    </span>
                  </div>
                ))}
              </div>
            )}
```

- [ ] **Step 5: Verify the build**

```bash
cd "/c/Users/antho/OneDrive/Documents/Five12-TheApp/app" && npm run build
```

Expected: builds with no errors (the pre-existing chunk-size advisory is fine).

- [ ] **Step 6: Manual verification in the browser**

Servers running (backend :5000, Vite :5173). In the DYMO print dialog:
- Upload a CSV → it appears under **Recent CSVs** (name · N rows · date).
- Hard-reload the app → the entry persists (backend-stored).
- Click the entry → it loads as the CSV source; pick the template and the preview/print work.
- Re-upload the same filename → the entry moves to the top, not duplicated.
- Click `×` on an entry → it disappears and stays gone after reload.

- [ ] **Step 7: Commit**

```bash
cd "/c/Users/antho/OneDrive/Documents/Five12-TheApp"
git add app/src/components/DymoPrintDialog.jsx
git commit -m "feat(dymo): Recent CSVs in print dialog — save on upload, reload, delete"
```

---

## Self-Review

**Spec coverage:**
- Backend table + both-DB migration → Task 1. ✓
- GET list (no rows) / GET one (rows) / POST upsert-by-name + cap 20 / DELETE, server-computed rowCount, validation → Task 2 (+ tests for each). ✓
- Save-on-upload, Recent CSVs panel, click-to-load (data only), per-entry delete → Task 3. ✓
- Auto-cap = 20 constant; upsert key = name → `CSV_SOURCE_CAP`, `filter_by(name=...)` in Task 2. ✓

**Placeholder scan:** No TBD/TODO; every step has complete code; commands have expected output. The migration revision id `c5f1a2b3d4e6` is fixed (not a placeholder) with `down_revision = 'e85115f40999'`.

**Type consistency:** `to_dict(include_rows)` shape (`id, name, headers, rowCount, createdAt`, +`rows`) defined in Task 1, asserted in Task 2 tests, consumed in Task 3 (`rc.name`, `rc.rowCount`, `rc.createdAt`, and `full.headers`/`full.rows`). Endpoint paths identical across tasks. `CSV_SOURCE_CAP = 20` matches the "keep 20 newest" test.

**Migration safety:** Task 1 applies the migration to BOTH databases before any route/model is exercised by the app; Task 2/3 depend on it. Stale-backend kill included per environment rules.
