# Active work — remove-astera-adapter

- **Owner:** Claude
- **Branch:** `chore/claude/remove-astera-adapter`
- **Workspace:** `C:\dev\five12-wt\astera-bench-plan`
- **Base SHA:** `20c911d`
- **Status:** review
- **Last updated:** 2026-08-04

## Goal

Remove the Astera ART7 device adapter. The 2026-08-04 bench session established
that it cannot work: see `docs/hardware-tests/astera-art7-stage-a.md`.

## Why removal rather than keeping it gated

The adapter polls a hypothesised HTTP server on the AsteraNext handset. That
server does not exist — a full TCP scan of all 65,535 ports with the app open and
connected found only two ephemeral listeners, neither of which speaks HTTP or
TLS, and the handset advertises nothing over mDNS.

It is dead against **both** hardware variants, not just the ART7-U on hand:

- **ART7-U** has no network interface at all, so the bridge can never be a target.
- **ART7-WIFI** has a WiFi radio, but it carries app↔bridge traffic in an
  undocumented protocol. It is not an HTTP API for third parties, so this adapter
  would not reach it either.

Keeping it gated would mean maintaining an adapter, a panel and 39 tests forever
for a feature that cannot exist, and leaving a Devices card that reads "disabled"
when the truth is "not achievable on this hardware". The hardware-test record
preserves everything learned, which is the part worth keeping.

## Reserved paths

- `backend/app/integrations/astera.py` (deleted)
- `backend/tests/test_astera_*.py` (deleted, 5 files)
- `app/src/components/devices/AsteraPanel.jsx`, `AsteraPanel.test.jsx` (deleted)
- `backend/app/integrations/__init__.py` (2 sites)
- `backend/config.py` (both config classes)
- `app/src/pages/Devices.jsx` (2 sites)

## Must-not-touch paths

- `backend/app/fixture_seed.py`, `backend/seed_fixtures.py`,
  `backend/app/integrations/stardust.py` — these contain **Astera fixture
  inventory** (Titan, Hyperion, AX3/AX5/AX10, Hydra Panel, Pixel Brick), which is
  unrelated to the ART7 bridge adapter and stays exactly as it is. Checked
  explicitly, because a careless `grep -i astera` sweep would have taken them.

## Interfaces and contracts

`ALL_DEVICE_IDS` drops `'astera'` and returns to
`('starlink', 'bolero', 'stardust', 'cintenna')`. `GET /api/devices` therefore
lists four devices instead of five. No route is added or removed; the Astera
integration never had routes of its own.

`ENABLE_ASTERA_TOOLS` / `FIVE12_ASTERA_TOOLS` no longer exist. Anyone with that
variable set in an environment can drop it — it was off by default and is now
inert either way.

## Dependencies and blockers

None. Depends only on the bench record already merged at `20c911d`.

## Decisions and trade-offs

**Removal over rewritten copy.** Rejected keeping the panel with honest wording,
because the maintenance cost is permanent and the feature is not merely
unavailable — it is unachievable on the hardware.

**Stage B is unaffected.** Any future direct-to-bridge work is Bluetooth, and
would share no code with this HTTP adapter. Removing it forecloses nothing. Per
the datasheets the ART7-U lists `Bluetooth Classic: Yes` where the ART7-WIFI
lists `No`, which puts Stage B on the Winsock/pywin32 branch rather than an
extension of `five12_ble/`.

## Checks run

| Command | Result | Evidence level |
|---|---|---|
| `Python312\python.exe -m pytest -q backend/tests` | **565 passed, 7 skipped, 0 failed** | n/a (software) |
| `npx vitest run` | **74 passed, 7 files** | n/a (software) |
| `npm run build` | passed (pre-existing chunk-size warning only) | n/a (software) |
| `grep -i astera` over `backend/app`, `backend/tests`, `app/src` | only fixture-inventory names remain | n/a (software) |

The 7 backend skips are the pre-existing BLE adapter-lock tests, which skip on
this rig because the Five12 app holds the Bluetooth adapter. Same as prior runs;
not caused by this change.

39 test functions were removed along with the five deleted backend test files.
I did not capture a pre-removal collection count on `main` to diff against, so
that figure is a count of the deleted files' own tests rather than a measured
delta.

## Risks and skipped checks

- Any operator environment setting `FIVE12_ASTERA_TOOLS=1` silently stops having
  an effect. It was off by default and the adapter never worked, so nothing
  observable changes.
- Not manually exercised in the running desktop app; the Devices tab change is
  the removal of one panel from a dict, covered by the frontend suite and build.

## Handoff / next action

For review per rule 5. The claims worth checking independently: that nothing
outside the Astera adapter was touched, that the fixture-inventory entries are
correctly excluded, and that the bench record actually supports removal rather
than deferral.
