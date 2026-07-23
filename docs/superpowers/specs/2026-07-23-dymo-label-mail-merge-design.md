# DYMO Label Mail-Merge

**Date:** 2026-07-23
**Status:** Approved (design) — pending spec review
**Component:** label printing (new backend model/endpoints, new frontend dialog, DYMO Connect local service)

## Problem

Fixture/cable labels are designed in DYMO Connect but filling them per-fixture
is manual. The app holds the per-fixture data (patch sheets) and already has a
column-mapping importer. Goal: upload a DYMO template once, then batch-print
labels ("mail merge") fed by patch-sheet rows or an uploaded CSV.

## Verified environment facts (2026-07-23, this machine)

- DYMO Connect for Desktop installed (`C:\Program Files (x86)\DYMO\DYMO Connect`).
- Its local web service is LIVE: `https://127.0.0.1:41951/DYMO/DLS/Printing/StatusConnected`
  → `200 true` (`DYMO.WebApi.Win.Host` process, `DYMOConnectPnPService` service).
- Printing model: browser-side JS (`dymo.connect.framework.js`) talks to that
  localhost service; the printer must be attached to the machine whose browser
  runs the app. Works identically in the Electron build.
- Mail merge primitive: `dymo.label.framework.LabelSetBuilder` — one record per
  label (`record.setText(objectName, value)`), converted to labelSetXml and
  passed to `printLabel(printer, printParams, labelXml, labelSetXml)`; one print
  job, N labels.
- Template variables = **named text objects** in the `.dymo` label XML. Objects
  must be named at design time in DYMO Connect.

## Decisions (from brainstorming)

1. **Data sources: BOTH** — first-class merge from patch-sheet rows (whole
   sheet or current selection), plus CSV upload for foreign data.
2. **Templates: uploaded and stored in the app DB** (name + label XML +
   extracted variable list), picked from a list per print session.
3. **Architecture: frontend-direct printing** — the browser talks to
   `127.0.0.1:41951` (DYMO's intended model; service ships permissive CORS).
   Backend never proxies print traffic. **Variable extraction is server-side**
   at upload (Python parses the `.dymo` XML once).
4. `dymo.connect.framework.js` is **vendored into the repo** (self-hosted, no
   CDN), consistent with the offline-desktop direction.

## Data model & API

New model `DymoTemplate` (`backend/app/models.py`):

```python
class DymoTemplate(db.Model):
    __tablename__ = 'dymo_templates'
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(120), nullable=False)
    label_xml  = db.Column(db.Text, nullable=False)      # raw .dymo contents
    variables  = db.Column(db.JSON, nullable=False)      # ["FixNum", "Uni", ...]
    created_at = db.Column(db.DateTime, nullable=False)  # UTC
```

Migration in the same change as the model, applied to **BOTH** databases
(MySQL via `flask db upgrade`; desktop SQLite via `FLASK_CONFIG=desktop`).

Endpoints (camelCase JSON, matching app conventions):

- `POST /api/dymo-templates` — multipart `file` (+ optional `name`, default =
  filename stem). Parses the XML, extracts named text-object names in document
  order (de-duplicated), rejects with 400 + reason when the file isn't valid
  label XML or has **zero** named objects ("template has no named variables —
  name the text objects in DYMO Connect"). Returns the stored record.
- `GET /api/dymo-templates` — `[{id, name, variables, createdAt}]` (list omits
  `labelXml`).
- `GET /api/dymo-templates/<id>` — full record incl. `labelXml` (the print
  dialog fetches it when selected).
- `DELETE /api/dymo-templates/<id>`.

Variable extraction rule: any element with a `Name` child/attribute belonging
to a text-type object in the label XML (DYMO label formats name objects
uniformly; extraction keys on object `Name` values, excluding DYMO's unnamed
auto objects). Implemented in a pure helper (`backend/app/dymo_templates.py`)
with unit tests against a real sample `.dymo` XML fixture.

## Frontend

**Vendored SDK:** `app/src/vendor/dymo.connect.framework.js`, imported lazily
by the dialog (not on app boot).

**`DymoPrintDialog`** (new component), opened from two places:

1. **Patch editor toolbar — "Labels" button** (`PatchTab.jsx`): preseeded with
   this sheet's rows; source toggle "Whole sheet (N)" / "Selected rows (n)"
   (selection = the existing row-selection state).
2. **Labels page — new "DYMO" section** (`LabelsPage.jsx`): template
   management (list / upload / delete) + "Print from CSV" entry.

Dialog steps:

1. **Template** — pick from stored list (shows its variables); upload lives on
   the Labels page section.
2. **Source** — patch rows (preseeded) or CSV upload. The CSV path is parsed
   **client-side** (first row = column names; minimal RFC-4180 parser, no
   external dep) and never touches the patch-import endpoints — no DB writes
   are involved, so the browser alone is sufficient.
3. **Mapping** — table of template variables, each with a select of source
   columns (+ Ignore/blank), auto-guessed with the same normalize/alias logic
   family as the importer (e.g. `FixNum` → fixture, `Uni` → universe,
   `Addr` → address, `Type` → type, `Loc` → location); patch-source columns are
   the canonical patch fields, CSV-source columns are the CSV headers. Live
   sample column shows the first row's value per variable.
4. **Preview & print** — the framework renders a PNG preview of the FIRST
   merged label (service-side render); printer picker via `getPrinters()`
   (last choice remembered in `localStorage`); `Print N labels` builds a
   `LabelSetBuilder` (one record per row; fully-blank rows skipped; unmapped
   variables get empty string) and calls `printLabel` once. A confirm warning
   appears above 200 labels (stock protection).

Design tokens throughout (surface/border/brand/online etc.), modal pattern
matching ImportWizard (incl. defensive response parsing; Esc/backdrop close
per the deferred-Minor convention if being touched anyway).

## Error handling

- **Service down:** on dialog open, probe `StatusConnected`; failure shows
  "DYMO Connect isn't running — launch DYMO Connect, then Retry" with a Retry
  button. No raw fetch errors.
- **No printers:** clear message after `getPrinters()` returns empty.
- **Upload errors:** 400 reasons surfaced verbatim (invalid XML / no named
  variables).
- **Print failure:** framework exception message surfaced in the dialog's
  error banner; dialog stays open (mapping preserved).

## Testing

- Backend (pytest, existing suite): variable extraction from a sample `.dymo`
  XML fixture (named objects found, unnamed skipped, dedupe, zero-var reject);
  endpoint CRUD round-trip incl. 400 paths. Both on in-memory SQLite fixtures.
- Frontend: no JS runner — manual verification against the LIVE local service:
  upload a real template, map patch rows, verify PNG preview renders, finish
  with a single-label real test print triggered by the operator.

## Out of scope (YAGNI)

- Designing/editing DYMO layouts in-app (stays in DYMO Connect).
- Multi-template batch jobs; image/barcode variable mapping (text objects only
  in v1).
- Changes to the existing LabelTemplate/LabelDesigner path — untouched,
  parallel feature.
- Backend proxying of print traffic.
