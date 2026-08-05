# Archived work — astera-tablet-mirror

- **Owner:** Claude
- **Branch:** `feat/claude/astera-mirror-impl` (merged; the original
  `docs/claude/astera-mirror-spec` carried the design only)
- **Workspace:** `C:\dev\five12-wt\astera-bench-plan` (removed on archive)
- **Base SHA:** `ce51e20`
- **Merged at:** `c2dcbd3` on `main`, 2026-08-05, PR #8 (rebase-merge, 19 commits)
- **Status:** merged — implemented, tested, and verified on the real tablet
- **Last updated:** 2026-08-05

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

## Closure — 2026-08-05

Shipped and merged as PR #8 (`c2dcbd3`). The design in
`docs/superpowers/specs/2026-08-04-astera-tablet-mirror-design.md` survived
contact with hardware; one of its numbers did not.

**Verified on actual gear** (Samsung SM-T290, Android 11, serial
`R9WR90CBTMH`, USB):

- `wm size` -> `Physical size: 800x1280`, no `Override size:` line. The
  coordinate-space concern that blocked the input task does not arise on this
  device. Confirmed in use: a tap at device `(400, 130)` landed on the correct
  one of five tabs across an 800 px width.
- `screencap -p` round-trip **514-644 ms, mean 529 (~1.9 fps)**, not the
  200-400 ms / 2-3 fps the spec estimated from an S21. The spec's reasoning
  held - the cost is on-device capture, not the link - but this tablet is
  slower than the phone it replaced. The design doc now carries the measured
  figure.
- End-to-end through the running app: **538 ms per frame** via the Vite proxy,
  matching raw adb almost exactly. The adapter adds nothing measurable.
- Nav keys all work. `Back` is intercepted by AsteraNext's own "leave the
  AsteraApp?" dialog rather than exiting.

**Two corrections the measurements forced:** the frame poll was a fixed 400 ms
`setInterval`, shorter than a single capture, which stacked four concurrent
requests under test; it now chains from capture completion at 750 ms.
`CAPTURE_TIMEOUT` dropped 8s -> 3s.

**Transport is USB, not wireless.** Wireless adb measured 0.05 MB/s against
18.18 MB/s cabled. Wireless debugging is off on the tablet. Re-enabling it
would also reintroduce the `sACN` `10.0.0.0/8` hazard recorded in the spec's
security model.

### Open, carried forward

- **Every timing number came from an idle tablet.** `screencap` will be slower
  while AsteraNext drives fixtures over Bluetooth - exactly when the mirror
  matters. 750 ms is the value to re-measure at a bench session with real gear.
- **Injected taps may pass through a dismissing dialog.** One `input tap` that
  dismissed a modal also appeared to select the item beneath it. Unproven and
  not reproduced deliberately; the panel binds only `onPointerDown` plus a
  window `pointerup`, so it is not a double-fire in the client. Worth pinning
  down before anyone drives this panel near modal prompts.
- This note's own process failure: no active note was ever opened for the
  implementation branch. Scope was claimed for the design only, and the
  implementation ran under it. Rule 3 wants one per task.
