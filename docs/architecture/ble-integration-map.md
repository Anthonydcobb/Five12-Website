# BLE Integration Map

Task 0 deliverable for the [Five12 Cintenna BLE Implementation Plan][plan]. The
plan was written without access to this repository and left `<BACKEND_ROOT>`
style placeholders throughout. This file replaces every one of them with the
real path, and records where the plan's assumptions do not match the codebase.

Verified against `main` @ `53034a0` on 2026-07-26.

[plan]: https://github.com/Anthonydcobb/hermes-lighting-networking-kb/blob/main/10-Lighting/References/LumenRadio/five12-cintenna-ble-implementation-plan.md

## Placeholder resolution

| Plan placeholder | Real path |
|---|---|
| `<BACKEND_ROOT>` | `backend/app/` |
| `<BACKEND_ROOT>/five12_ble/` | `backend/app/five12_ble/` |
| `<BACKEND_TEST_ROOT>/five12_ble/` | `backend/tests/` (flat, `test_ble_*.py`) |
| `app/src/components/devices/*.js` | `app/src/components/devices/*.jsx` (dir does not exist yet) |
| "Existing Devices page/store" | `app/src/pages/Devices.jsx` — no store exists |
| Base branch `edit_export` | `main` — see Branch below |

## Backend

**Entry point.** `backend/app.py` → `backend/app/__init__.py` (app factory
`create_app`) → blueprints registered inside the factory.

**Framework.** Flask 3 + SQLAlchemy 2 + Flask-Migrate. Not FastAPI; there are no
`APIRouter`s and no WebSocket server. Routes are Blueprints with `url_prefix`.

**Dependencies.** `backend/requirements.txt`, plain pip, virtualenv at `venv/`.
No Poetry, no lock file. `bleak` is added here and pinned.

**Config / feature gates.** `backend/config.py`. The existing pattern is:

```python
ENABLE_NETWORK_TOOLS = os.getenv("FIVE12_NETWORK_TOOLS", "1") == "1"
```

consumed in the factory to conditionally register a blueprint, so a disabled
feature's routes *do not exist* rather than returning 403:

```python
if app.config.get('ENABLE_NETWORK_TOOLS'):
    from .network_routes import net as network_bp
    app.register_blueprint(network_bp)
```

`ENABLE_BLE_TOOLS` follows this exactly, with one deliberate difference: it
defaults **off** (`FIVE12_BLE_TOOLS`, absent means disabled). Scanning radio
without being asked is not equivalent to probing the operator's own LAN.

**Existing device-discovery service.** `backend/app/integrations/` is a small
adapter framework, already the shape this feature needs:

- `DeviceAdapter` base class — `detect() -> {found, address, detail}` and
  `get_status() -> camelCase dict including 'available' and 'alerts'`
- `get_adapter(device_id, sim)` — caches one adapter instance per
  `(device_id, sim)` so history accumulates
- `ALL_DEVICE_IDS = ('starlink', 'bolero', 'stardust')`
- `HistoryRing` — bounded, thread-safe, throttled telemetry ring
- `sim_enabled(request_args)` — `?sim=1` or `FIVE12_DEVICE_SIM=1`
- `require_private_host(host)` — SSRF guard; not applicable to BLE, which has
  no network target, but the same "never take a target from request input"
  principle applies to UUIDs

Adapters: `starlink.py`, `bolero.py`, `stardust.py`. All read-only in v1 except
one deliberate write (`stardust_link`).

**Existing routes.** `backend/app/device_routes.py`, blueprint `devices` at
`/api/devices`:

```
GET  /api/devices                        auto-detect all known device types
GET  /api/devices/<device_id>/status
GET  /api/devices/<device_id>/history
GET  /api/devices/stardust/units
PUT  /api/devices/stardust/label
POST /api/devices/stardust/link
GET  /api/devices/stardust/reconcile/<patch_id>
```

`list_devices()` iterates `ALL_DEVICE_IDS` and calls `adapter.detect()` on each.
**Adding `'cintenna'` to `ALL_DEVICE_IDS` is what makes the tab appear.** No
change to `list_devices()` itself is required.

**Background-thread precedent.** `backend/app/scanner.py::start_scanner(app)`
runs two daemon threads (discovery sweep, keep-alive) launched from the factory
under `ENABLE_NETWORK_TOOLS`, each loop wrapped in try/except so a failed beat
is skipped rather than fatal. The BLE scan loop follows this pattern.

Known caveat, documented in that file: under gunicorn every worker runs its own
scanner. Redundant ARP pings are merely wasteful; **two processes contending for
one Bluetooth adapter is broken**, so the BLE service adds single-owner
enforcement the ARP scanner does not need.

**Persistence.** MySQL in dev via Alembic (`migrations/`), SQLite on desktop
where the factory calls `db.create_all()`. `NetworkDevice` carries
`mac_address` + `device_type` and is reused by Stardust to persist operator
labels. **Cintenna cannot reuse this directly** — see Identity below.

**Tests.** pytest, flat in `backend/tests/`, with `conftest.py`. No `pytest.ini`.
Run from `backend/`:

```
pytest
```

Existing files are named `test_<subject>.py` (`test_bolero_normalize.py`,
`test_scanner_discovery.py`, …). BLE tests follow as `test_ble_<subject>.py`.
The plan's `tests/five12_ble/` subdirectory is **not** used — matching the
repository beats matching the plan's placeholder.

## Frontend

**Framework.** React 19 + Vite 5 + Tailwind 4 + React Router 7. Entry
`app/src/main.jsx` → `App.jsx` → `src/pages/`.

**Devices page.** `app/src/pages/Devices.jsx`, 529 lines. Structure:

```javascript
const PANELS = { starlink: StarlinkPanel, bolero: BoleroPanel, stardust: StardustPanel };

export default function Devices() {
  const [detected, setDetected] = useState([]);   // from GET /api/devices, 10s poll
  const [tab, setTab] = useState('starlink');
  const Panel = PANELS[tab];
  ...
}
```

All three panels are defined **inline in this file**. The tab strip renders from
`detected`, so tabs are data-driven by the backend, not hardcoded.

**Adding the Cintenna tab** therefore needs exactly two frontend changes:
`PANELS.cintenna = CintennaPanel`, and an import. The button appears because the
backend reports the device.

**API access.** `axios` called inline in components (`axios.get('/api/devices')`).
There is no shared API client. `app/src/lib/` holds `dymo.js`, `labelMerge.js`,
`rangeExpr.js` — so a `lib/bleApi.js` wrapper fits the existing convention.

**State management.** None. No zustand, redux, jotai, or context store. Panels
own local `useState` and poll on an interval. The plan's references to "the
frontend store" describe something that does not exist; BLE state stays local to
`CintennaPanel` with the same polling convention.

**Vite proxy.** `/api/*` → `http://localhost:5000` (`app/vite.config.js`).

**Tests.** None. No Vitest, Jest, or testing-library; no test script in
`app/package.json`. Vitest + React Testing Library are added by this work,
scoped to the new BLE components only — existing untested components are not
backfilled, as that is unrelated to this feature.

## Identity: why Cintenna cannot reuse `NetworkDevice.mac_address`

Stardust persists labels keyed by Ethernet MAC. On Windows, the identifier
`bleak` returns for a BLE peripheral is an OS-level handle, and the peripheral
may use a resolvable private address that rotates. The captured unit reports
`Address resolution: supported` (`0x2AA6`).

Cintenna identity is therefore **evidence-based and best-effort**: OS
identifier + advertised local name + decoded hardware ID, presented as "same
device, best effort" rather than a stable key. Operator annotations, if added
later, need their own keying strategy — do not widen `NetworkDevice`.

## Development commands

```
# backend  (from backend/)
flask run
pytest

# frontend (from app/)
npm run dev
npm run test      # added by this work

# both servers must run concurrently; Vite proxies /api/* to :5000
```

## Branch

The plan instructs implementing from `edit_export`. **That is stale.** As of
2026-07-26:

```
origin/main ...51 commits ahead of... origin/edit_export
origin/edit_export ...0 commits ahead of... origin/main
main:        53034a0  2026-07-23
edit_export: b41fe05  2026-07-22
```

`edit_export` is fully merged into `main` and carries nothing unique. Work is
based on `main` via `feat/cintenna-ble`.

## Plan deviations, summarized

| # | Plan says | Reality | Resolution |
|---|---|---|---|
| 1 | Standalone `five12_ble/` package | `integrations/` adapter framework exists | Keep `five12_ble/` module boundaries; add a thin `CintennaAdapter` facade so the Devices page works unchanged |
| 2 | Tests in `tests/five12_ble/` | `backend/tests/` is flat | Flat `test_ble_*.py` |
| 3 | `components/devices/*.js` | Directory absent; repo uses `.jsx` | Create the directory, use `.jsx` |
| 4 | "The frontend store" | No store exists | Local state + polling, matching sibling panels |
| 5 | Frontend test suite | No JS test infra | Add Vitest + RTL scoped to BLE |
| 6 | Base branch `edit_export` | 51 commits stale | Base on `main` |
| 7 | Adapter contract assumed sync-friendly | BLE is async + long-lived | Background daemon thread owns the bleak loop; adapter reads its registry synchronously |
