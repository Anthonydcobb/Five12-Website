# Active work — astera-tablet-mirror

- **Owner:** Claude
- **Branch:** `docs/claude/astera-mirror-spec`
- **Workspace:** `C:\dev\five12-wt\astera-bench-plan`
- **Base SHA:** `ce51e20`
- **Status:** planned — design only, no implementation
- **Last updated:** 2026-08-04

## Goal

Put the AsteraNext control screen inside the Five12 Devices tab, mirrored from a
dedicated Android tablet, with tap control. Replaces the removed telemetry
adapter with something that reports a link we can actually verify.

## Acceptance criteria

- [x] Design agreed and written
- [ ] Implementation plan written (writing-plans)
- [ ] Implemented and reviewed per rule 5

## Reserved paths

Claimed only when implementation starts, not by this branch:

- `backend/app/integrations/android_mirror.py`
- `backend/app/integrations/__init__.py`, `backend/config.py`
- `backend/app/device_routes.py`
- `app/src/components/devices/AsteraMirrorPanel.jsx`
- `app/src/pages/Devices.jsx`

## Must-not-touch paths

- Astera **fixture inventory** in `fixture_seed.py`, `seed_fixtures.py`,
  `stardust.py` — DMX fixtures, unrelated, same trap as the removal branch.

## Interfaces and contracts

`ALL_DEVICE_IDS` regains `'astera'`, so `GET /api/devices` returns five again.
Two new device-specific routes under `/api/devices/astera/`. This is a **new**
adapter reporting mirror-link state, not a revival of the removed ART7 telemetry
adapter — the distinction is spelled out in the spec and must stay legible in the
module docstring.

## Dependencies and blockers

- Dedicated Android tablet not yet purchased. Not blocking: development and tests
  run against the already-paired S21.
- Whether AsteraNext is usable on a tablet-sized screen is unverified.

## Decisions and trade-offs

**Screencap polling over real video, for v1.** Ceiling is ~2–3 fps, set by
on-device `screencap` latency, not the network. Accepted so something ships into
the existing Flask/React shape without a video pipeline; approach B (H.264 +
WebCodecs) is staged as v2 and replaces the transport under the same tab.
Rejected `ws-scrcpy` outright — a Node sidecar and an uncontrolled dependency on
a show machine.

**iOS rejected.** `adb`/`scrcpy` are Android-only and Apple offers no supported
control path from Windows. AirPlay to a Windows receiver is view-only.

**Security follows the invariant this repo already states.** Serial from config,
never from request input; closed adb command allowlist; loopback-only backend;
gate default off. Layers that stop other people are the loopback bind and adb
pairing; the allowlist stops Five12 itself becoming the weak point.

## Plan or spec

- `docs/superpowers/specs/2026-08-04-astera-tablet-mirror-design.md`

## Checks run

| Command | Result | Evidence level |
|---|---|---|
| none — design only, no code | n/a | n/a |

## Risks and skipped checks

- 2–3 fps may prove unusable for the colour/intensity work Anthony actually does,
  which would make v2 mandatory rather than optional. Unknown until v1 is used.
- Executing processes from an HTTP endpoint is new to this codebase. The gate,
  the allowlist and the config-only serial exist to bound it; the tests must
  prove all three rather than assert them.

## Handoff / next action

Design approved 2026-08-04. Next step is the implementation plan via
writing-plans, in a fresh session — this one ended at the spec.
