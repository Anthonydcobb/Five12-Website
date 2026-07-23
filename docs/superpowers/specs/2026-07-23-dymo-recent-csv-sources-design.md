# DYMO — recent CSV sources (reprint without re-importing)

Date: 2026-07-23
Branch: `feat/dymo-label-merge` (extends the unmerged DYMO print work)
Areas: backend (`models.py`, `dymo_routes.py`, a migration) + frontend (`DymoPrintDialog.jsx`)

## Problem

To print labels from a CSV you must re-run the file-import picker every time,
even to reprint the exact same data. There is no memory of CSVs you've used.

## Goals

- Keep a backend list of recently used CSV sources so you can reload one and
  print again without re-importing the file.
- Remove entries: a per-item delete, plus an automatic cap so the list can't
  grow unbounded.

Non-goals: a print audit log (who/when/what printed); remembering patch-sheet
sources (already one click from the sheet); column mapping storage (already
handled per-template by `saved_mappings` — picking the template re-derives it).

## Behavior

- Uploading a CSV in the print dialog also saves it to the backend (name = the
  file's name), fire-and-forget — a save failure never blocks printing.
- **Upsert by name:** re-uploading a CSV whose name already exists updates that
  entry's rows and moves it to the top (bumps `created_at`) instead of adding a
  duplicate.
- **Auto-cap = 20:** after each save, only the 20 most recent entries are kept;
  older ones are deleted. Single constant, easy to change.
- Clicking a Recent CSV loads it as the source (populates the dialog's `csv`
  state and switches source to CSV). The user then picks a template — whose
  remembered mapping auto-fills — and prints. (Per the design decision, the
  history restores the CSV **data only**, not the template/mapping.)
- A `×` on each entry deletes it.

## Data model

New table `dymo_csv_sources`, mirroring `DymoTemplate`'s JSON-column style:

```python
class DymoCsvSource(db.Model):
    __tablename__ = 'dymo_csv_sources'
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(200), nullable=False)
    headers    = db.Column(db.JSON, nullable=False)   # ["Fixture ID", "Address", ...]
    rows       = db.Column(db.JSON, nullable=False)   # [{header: value, ...}, ...]
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

Entries are small (≤100 rows × a handful of columns, a few KB); 20 of them is
negligible. `MEDIUMTEXT`-style concerns don't apply at this size, but `rows` is
JSON like the existing columns.

## Migration

One Alembic migration in `backend/migrations/versions/` creating
`dymo_csv_sources`. Applied to **both** databases in the same change:
`flask db upgrade` (MySQL dev) and `FLASK_CONFIG=desktop flask db upgrade`
(desktop SQLite). Per the environment rules, a model change shipped without a
matching migration on both DBs 500s the app the moment it (or the app-spawned
backend) restarts.

## API (`/api/dymo-csv-sources`, in `dymo_routes.py`)

- `GET ''` → list newest-first; each item is `to_dict()` (no `rows` — keeps the
  list light). Fields: `id, name, headers, rowCount, createdAt`.
- `GET '/<int:sid>'` → `to_dict(include_rows=True)` (the full data to restore).
- `POST ''` → body `{name, headers, rows}`.
  - Validate: `name` non-empty string (trimmed, ≤200 chars, default `'Untitled'`);
    `headers` a list; `rows` a list. Else 400.
  - Upsert by name: if a row with that `name` exists, replace its `headers`,
    `rows`, `row_count` and set `created_at = utcnow()`; else insert.
  - Then cap: delete all but the 20 newest by `created_at`.
  - Return `to_dict()` (201 on insert, 200 on update).
- `DELETE '/<int:sid>'` → delete, return `{'deleted': sid}` (404 if absent).

`row_count = len(rows)` is computed server-side, not trusted from the client.

## Frontend (`DymoPrintDialog.jsx`)

- On mount, `GET /api/dymo-csv-sources` → `recentCsvs` state.
- CSV upload handler: after `parseCsv`, in addition to setting local state,
  `POST` `{name: file.name, headers, rows}` (fire-and-forget; on success refresh
  the list; on failure `console.warn`, do not surface — printing is unaffected).
- A **Recent CSVs** panel in the Source area, shown when `recentCsvs.length > 0`:
  each entry a clickable row `name · {rowCount} rows · {date}` with a `×`.
  - Click → `GET /<id>` for rows → `setCsv({headers, rows})`, `setSource('csv')`.
  - `×` → `DELETE /<id>` → refresh the list (stopPropagation so it doesn't also
    load the entry).
- No change to the print path, mapping, jog, or scope work.

## Testing

Backend (pytest, `backend/tests/`, mirroring `test_dymo_templates.py`):
- POST inserts and returns the entry with a server-computed `rowCount`.
- POST with an existing name updates in place (no duplicate; `created_at`
  bumped; list length unchanged) — assert by re-listing.
- Auto-cap: inserting a 21st distinct entry leaves exactly 20, and the dropped
  one is the oldest.
- GET list omits `rows`; GET one includes `rows`.
- DELETE removes it (and 404 for a missing id).
- POST validation: non-list `rows`/`headers` or empty name → 400.

Frontend: manual in the dialog — upload a CSV, see it appear in Recent CSVs;
reload the app, it persists; click it to load as source and print; `×` removes
it; re-uploading the same filename moves it to the top without duplicating.

## Files

- `backend/app/models.py` — add `DymoCsvSource`.
- `backend/migrations/versions/<rev>_dymo_csv_sources.py` — create table.
- `backend/app/dymo_routes.py` — the four routes above.
- `backend/tests/test_dymo_csv_sources.py` — the backend tests.
- `app/src/components/DymoPrintDialog.jsx` — recent list, save-on-upload, load, delete.
