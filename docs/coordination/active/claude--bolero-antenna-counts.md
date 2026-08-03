# Active work — per-antenna beltpack counts from the Bolero websocket

- **Owner:** Claude
- **Branch:** `feat/claude/bolero-websocket-antenna`
- **Workspace:** local Windows worktree, `C:\dev\five12-wt\bolero-ws`
- **Base SHA:** `7084e91` (`origin/main`)
- **Status:** in progress
- **Last updated:** 2026-07-30

## Goal

Show per-antenna beltpack counts on the Devices page, the way the Bolero's own
GUI does, sourced from the `audioPorts` stream on `ws://<host>/wsapp`.

Protocol findings that drive every decision here are in
`docs/architecture/bolero-websocket-protocol.md` — established against the live
rig and a devtools capture.

## Scope boundary, and why this stops short of the runtime manager

Anthony asked for this "with the runtime manager." **The runtime manager does not
exist yet and is not mine to build.** The hardening plan's own matrix:

```text
| Runtime service contract      | Hermes | Claude | No downstream implementation until approved |
| RuntimeManager and startup    | Hermes | Claude | No |
```

and section 8.4 prohibits parallel work on `backend/app/__init__.py` startup
lifecycle. Hermes is mid-flight on `fix/hermes/doctor-ref-failclosed` right now.

So this branch builds the **service**, not the manager:

- a self-contained listener implementing the lifecycle shape Task 3.1 specifies
  — idempotent `start()`, idempotent `stop()`, a deterministic `status()`
  snapshot — so registering it later is a few lines
- **nothing is wired into `create_app()` or `run_desktop.py`.** The service is
  inert unless something starts it. Under the current tree, nothing does.
- no `backend/app/services/` package and no `contracts.py`. Those are Hermes'
  files; conforming to the published field list is not the same as creating them

If Anthony would rather I build the manager too, that is a reassignment and the
plan says it must be recorded in the active note before editing — it has not
been, so it is not done here.

## The design, and the two things it refuses to do

### It does not report a per-pack antenna

Antenna assignment changes several times a second — pack 30 moved three times in
450 ms in the capture. A per-pack column would be stale before it rendered. The
Bolero GUI does not show one either. See the protocol doc.

### It does not claim a count it has not converged on

The socket takes no requests, so there is no snapshot: a fresh listener starts
knowing nothing and learns only as packs are announced. Until every pack in
`packsOnline` has been seen at least once, the counts are incomplete, and
incomplete counts that look complete are the exact failure this whole thread
began by removing.

So the service reports `converged: false` and withholds counts until it has seen
every connected pack, and the panel shows the honest blank until then.

### The unresolved question, and how the design survives it

It is not known whether a pack can hold bearers on several antennas at once —
`audioPorts` only ever says `registered: true`, with no deregistration observed.
Anthony has asked to proceed anyway, which is his call.

The model is therefore **last-announcement-wins**: a pack counts toward the
antenna named in the most recent `audioPorts` message about it. That is
well-defined under either reading of the protocol — it is the current assignment
if handover is exclusive, and the most-recently-announced bearer if it is not.
It can never double-count, because a pack maps to exactly one antenna at a time.

If the multi-bearer reading turns out to be correct, the counts will still sum to
`packsOnline` and will still track the GUI; what would change is the *meaning*,
from "attached to" to "most recently announced on". That distinction is recorded
in the module docstring rather than papered over.

## Reserved paths

- `backend/app/integrations/bolero_ws.py` (new)
- `backend/tests/test_bolero_ws.py` (new)
- `docs/coordination/active/claude--bolero-antenna-counts.md`
- `docs/architecture/bolero-websocket-protocol.md` (already on this branch)

## Must-not-touch paths

- `backend/app/services/**`, `backend/app/__init__.py`, `backend/run_desktop.py`
  — runtime manager and startup lifecycle, Hermes'
- `scripts/`, `start.ps1`, doctor tests — Hermes until `f60c52f` lands
- `backend/app/fixture_library*.py`, `app/src/pages/Database.*` — Hermes' W2
- `backend/app/integrations/bolero.py` — the polling adapter stays as it is;
  joining the counts into its payload is a later step, once there is a manager
  to own the listener's lifecycle

## Checks run

To be filled in.
