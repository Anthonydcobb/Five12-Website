# Astera Integration Map

Task 0 of the Hermes spec `five12-art7-asteranext-device-integration-spec.md`
(KB repo `anthonydcobb/hermes-lighting-networking-kb`, branch
`plan/five12-art7-device-integration`, spec commit `ada6841`).

Written against **`origin/main` @ `aaca308`** — the real repository, not a
placeholder. Every path below was read, not assumed. Companion review with the
verdict and blockers: `docs/agent-reviews/2026-07-29-claude-review-of-astera-integration-spec.md`.

Follows the format of `docs/architecture/ble-integration-map.md`, which the
Cintenna work created on `feat/cintenna-ble` for the same purpose.

## Placeholder resolution

| Spec placeholder | Real value |
|---|---|
| `<BACKEND_ROOT>/integrations/astera/` (package) | `backend/app/integrations/astera.py` (one module — siblings are single files) |
| `<BACKEND_TEST_ROOT>/integrations/astera/` | `backend/tests/test_astera_*.py` (the tests dir is flat) |
| `app/src/lib/asteraApi.js` | Not needed on `main`; sibling panels call `axios` inline. `app/src/lib/bleApi.js` exists only on `feat/cintenna-ble` |
| `app/src/components/devices/Astera*.js` | `app/src/components/devices/AsteraPanel.jsx` — directory exists only on `feat/cintenna-ble`; extension is `.jsx` |
| "the Devices store" | **No store exists.** Local `useState` + `setInterval` per panel |
| "device aggregator" | `ALL_DEVICE_IDS` + `get_adapter()` in `backend/app/integrations/__init__.py` |
| Base branch `edit_export` | **Stale.** `origin/edit_export` is 0 ahead / 54 behind `origin/main`. Base on `main` |
| Windows checkout `…\Five12-TheApp` | Not verifiable from this environment. Authoritative remote is `github.com/Anthonydcobb/Five12-Website` |

## Backend

**Framework and entry point.** Flask 3 (WSGI, **synchronous**), app factory
`create_app()` in `backend/app/__init__.py:12`. Dev entry `backend/app.py`,
desktop entry `backend/run_desktop.py`, WSGI entry `backend/wsgi.py`. There is
no ASGI server, no event loop in a request, and no `async def` route anywhere in
`backend/app/`. Blueprints are registered in the factory.

**Dependencies.** `backend/requirements.txt`, pinned, hand-edited (no
pyproject/poetry/Pipfile). `requests==2.32.3` is already present — Stage A adds
no new dependency.

**The device integration seam.** `backend/app/integrations/__init__.py`:

| Symbol | Line | What it is |
|---|---|---|
| `sim_enabled(request_args)` | 24 | `?sim=1` or `FIVE12_DEVICE_SIM=1` |
| `require_private_host(host)` | 30 | Resolves, rejects non-private/non-link-local, **returns the resolved IP** |
| `tcp_reachable(host, port)` | 43 | 0.6 s connect probe, used by `detect()` |
| `HistoryRing` | 51 | Bounded, thread-safe, throttled in-memory telemetry ring |
| `check_thresholds(status, rules)` | 78 | Shared alerts primitive |
| `DeviceAdapter` | 99 | **The interface**: `detect()`, `get_status()`, `get_history(n)` |
| `get_adapter(device_id, sim)` | 125 | Registry, cached per `(device_id, sim)` for process life |
| `ALL_DEVICE_IDS` | 141 | `('starlink', 'bolero', 'stardust')` |

`DeviceAdapter` is synchronous and has exactly three methods. There is no
`start()`, `stop()`, `snapshot()`, `health()`, or `capabilities()`, and nothing
in the codebase is a `typing.Protocol`.

**Existing adapters.** `starlink.py` (gRPC), `bolero.py` (HTTP REST),
`stardust.py` (RDM-over-Art-Net + a `/ws` socket), and on `feat/cintenna-ble`
`cintenna.py` (thin sync reader over a background BLE scan service).

**Closest analog to Stage A: `bolero.py`.** Env-configured private host,
fixed endpoint constants, one private fetch helper, sim mode:

```
backend/app/integrations/bolero.py:32   ENDPOINTS = {...}      # fixed paths, module constant
backend/app/integrations/bolero.py:84   self.host = os.getenv('FIVE12_BOLERO_HOST', ...)
backend/app/integrations/bolero.py:90   detect()               # require_private_host + tcp_reachable
backend/app/integrations/bolero.py:116  _fetch_json(path)      # re-validates host every call
backend/app/integrations/bolero.py:122  requests.get(f'http://{ip}{path}', timeout=3)
backend/app/integrations/bolero.py:205  _sim_status()          # hardware-free development
```

`_fetch_json` takes a path from a module constant, never from request input, and
builds the URL from the **resolved IP** — so there is no second DNS lookup to
rebind. This is the pattern Astera copies.

**HTTP surface.** `backend/app/device_routes.py`, blueprint `devices`,
`url_prefix='/api/devices'`:

```
GET /api/devices                       list_devices()   :28  — detect() for every ALL_DEVICE_IDS
GET /api/devices/<device_id>/status    device_status()  :48
GET /api/devices/<device_id>/history   device_history() :59  — n capped at 2880
```

Plus Stardust-specific routes (`/stardust/units`, `/stardust/label`,
`/stardust/link`, `/stardust/reconcile/<id>`). A new device family normally adds
**no new routes** — it appears through the generic three.

The module docstring states the security invariant verbatim
(`device_routes.py:7-9`):

> Security: adapters only ever contact fixed or operator-configured PRIVATE
> addresses (see integrations/__init__.require_private_host). **No target is
> ever taken from request input.**

**Feature gates.** `backend/config.py`, read as Flask config, checked at
blueprint-registration time in the factory:

```
config.py:26   ENABLE_NETWORK_TOOLS = os.getenv("FIVE12_NETWORK_TOOLS", "1") == "1"   # default ON
app/__init__.py:51   if app.config.get('ENABLE_NETWORK_TOOLS'):  register network_bp
```

On `feat/cintenna-ble` the same file adds the pattern a new radio/off-by-default
feature should copy:

```
ENABLE_BLE_TOOLS = os.getenv("FIVE12_BLE_TOOLS", "0") == "1"   # default OFF, in BOTH config classes
```

Device integrations themselves are currently **ungated** — `device_routes` is
registered unconditionally (`app/__init__.py:36-39`) because all four adapters
are cross-platform, read-only and have a sim mode.

**Background threads.** Only two on `main`, both started from the factory and
both because their transport is push/continuous rather than request-shaped:

```
app/__init__.py:67   start_scanner(app)          # ARP/ping sweep, backend/app/scanner.py
app/__init__.py:76   start_sacn_listener(app)    # passive sACN on 5568
```

`feat/cintenna-ble` adds a third (`start_ble_service`) for the same reason.
**No HTTP integration has a backend polling loop.** Starlink, Bolero and
Stardust fetch inside the request that asks for status.

**Per-process caveat, already documented** (`app/__init__.py:65-66`, `:71-76`):
under gunicorn every worker runs its own scanner and its own `_registry`, so
adapter-held state (history ring, last-known-good) is per worker. Desktop mode —
the actual target — is single-process.

## Frontend

**Entry.** `app/src/main.jsx` → `App.jsx` (React Router 7). `/devices` →
`app/src/pages/Devices.jsx` (`App.jsx:38`).

**No store.** No Redux, Zustand, or Context. `Devices.jsx` is 529 lines holding
every panel, its own primitives, and its own polling.

**The polling model is client-side** (`Devices.jsx`):

```
:12   const POLL_MS = 3000;
:64   useDevice(id, query)   — GET /api/devices/:id/status every 3 s
                             — GET /api/devices/:id/history every 12 s
:84   cleanup: alive = false; clearInterval(...)   on unmount / id change
:483  page shell polls GET /api/devices every 10 s
```

A panel polls only while it is mounted, i.e. only while its tab is selected.

**Page shape.** A flat strip of detection cards (one per entry returned by
`GET /api/devices`) acting as tabs, and one panel below (`Devices.jsx:473-527`):

```jsx
const PANELS = { starlink: StarlinkPanel, bolero: BoleroPanel, stardust: StardustPanel };
```

The card renders `<Dot ok={d.found} /> {d.name}` and a second line of
`{d.address || 'found'} · {d.detail}` — so **`found` is a boolean and `detail` is
free text**; nuanced state is expressed in `detail`, not in the dot.

Shared primitives `Dot`, `Tile`, `AlertChips`, `Sparkline`, `Unavailable` are
declared at module scope in `Devices.jsx` and are **not exported**.

**Adding a family is two lines in `Devices.jsx`** — the import and the `PANELS`
entry — exactly as `feat/cintenna-ble` did.

**Frontend tests.** None on `main`: no Vitest/Jest, no `test` script in
`app/package.json`. `feat/cintenna-ble` adds Vitest + Testing Library + jsdom,
`app/vite.config.mjs` `test:` block, `src/test/setup.js`, and `npm run test`.

## Test infrastructure

```
# backend (from backend/)
pytest                      # 164 tests at aaca308

# frontend (from app/)
npm run test                # EXISTS ONLY ON feat/cintenna-ble
```

`backend/tests/` is **flat** — `test_bolero_normalize.py`, `test_stardust_outputs.py`,
`test_scanner_discovery.py`, and 12 × `test_ble_*.py` on the Cintenna branch. No
`tests/integrations/` subtree, no `tests/fixtures/` directory. `conftest.py`
gives `app` (session-scoped, SQLite in-memory, `TESTING=True`), `client`, `db`.

Sanitized protocol fixtures have no existing home: the BLE work used inline byte
constants in the test modules. JSON payloads big enough to hurt readability
should go in a new `backend/tests/fixtures/astera/`.

## Identity

There is nothing to deduplicate. `GET /api/devices` returns one entry per
`ALL_DEVICE_IDS` — identity **is** the adapter id. A configured host change does
not create a second card for Bolero and would not for Astera.

The one persisted-identity precedent is Stardust, which keys operator labels by
Ethernet MAC on the `NetworkDevice` row (`device_routes.py:68-103`) so a unit
survives DHCP moves. The BLE map explicitly ruled that path closed for
non-Ethernet devices ("do not widen `NetworkDevice`"), and an ART7 has no
network identity at all — it is behind the phone.

## Documentation conventions

- `docs/architecture/` — exists on `feat/cintenna-ble` only (`ble-integration-map.md`,
  `cintenna-ble-handoff.md`). Created here on `main`'s line of descent.
- `docs/agent-reviews/` — **does not exist and is not declared** in `CLAUDE.md`
  or `AGENTS.md`. Created by this work at Hermes's request.
- `docs/coordination/reviews/` — a second, parallel review folder living only on
  `docs/hermes/agent-coordination`. See the review's non-blocking notes.
- `docs/superpowers/plans|specs/` — dated plan/spec pairs per feature.
- `docs/handoff-*.md` — dated session handoffs at `docs/` root.

## Exact files Stage A touches

| File | Change |
|---|---|
| `backend/config.py` | `ENABLE_ASTERA_TOOLS` in both config classes, default OFF |
| `backend/app/integrations/astera.py` | **new** — `AsteraAdapter(DeviceAdapter)`, fixed route constants, `_fetch_json`, normalizers, redaction, sim |
| `backend/app/integrations/__init__.py` | 2 lines: `get_adapter` classes map + `ALL_DEVICE_IDS` |
| `backend/tests/test_astera_endpoint.py` | **new** — host policy, port lock, path allowlist, redirect/size/content-type refusals |
| `backend/tests/test_astera_normalize.py` | **new** — status/target normalization, unknown vs missing, stale, PIN redaction |
| `backend/tests/test_astera_adapter.py` | **new** — gate off, no host, failure cache, last-known-good, sim |
| `backend/tests/fixtures/astera/*.json` | **new** — sanitized bench captures |
| `app/src/components/devices/AsteraPanel.jsx` | **new** — overview / targets / disabled-fixtures sections |
| `app/src/pages/Devices.jsx` | 2 lines: import + `PANELS` entry |
| `docs/hardware-tests/astera-art7-stage-a.md` | **new** — bench evidence (Task 5) |

Not touched: `routes.py`, `models.py`, `migrations/`, `network_routes.py`,
`scanner.py`, `sacn_listener.py`, `five12_ble/`, any lockfile, `.env*`.

## Plan deviations, summarized

| # | Spec says | Reality | Resolution |
|---|---|---|---|
| 1 | `async` `DeviceProvider` protocol | Sync `DeviceAdapter`, 3 methods, Flask WSGI | Subclass `DeviceAdapter` |
| 2 | Backend polling loop + task cancellation (Task 6) | HTTP integrations are polled by the browser | Drop the loop; failure cache + last-known-good in the cached adapter |
| 3 | `POST/PATCH/DELETE /integrations` with an endpoint (Task 7) | "No target is ever taken from request input" | Env config `FIVE12_ASTERA_HOST`, like Bolero |
| 4 | Multiple configured integrations, `integrationId` UUIDs | One adapter instance per device id | One endpoint, no synthetic ids |
| 5 | Card + detail panel, three-section Devices page | Tab strip + one panel, no store | One tab, sections inside `AsteraPanel` |
| 6 | New endpoint validator | `require_private_host()` already exists | Reuse it; add redirect/size/content-type caps locally |
| 7 | `integrations/astera/` package, `tests/integrations/astera/` | Single-file adapters, flat tests | `astera.py`, `test_astera_*.py` |
| 8 | Base `edit_export` | 54 commits stale | Base on `main` @ `aaca308` |
| 9 | Frontend test requirements | No JS test infra on `main` | Sequence behind `feat/cintenna-ble`, or backend-only tests |
| 10 | (absent) | Every adapter has a sim mode | Build sim first, before hardware day |
