# Active work — per-antenna beltpack counts from the Bolero websocket

- **Owner:** Claude
- **Branch:** `feat/claude/bolero-websocket-antenna`
- **Workspace:** local Windows worktree, `C:\dev\five12-wt\bolero-ws`
- **Base SHA:** `7084e91` (`origin/main`)
- **Status:** BLOCKED — the approach does not work; see the live result below
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
450 ms in the capture — so a per-pack column would be stale before it rendered.

**The second half of this reasoning was wrong and is retracted.** I wrote that
the Bolero GUI does not show a per-pack antenna either. It does: the `Device`
column in the Beltpacks view. I had generalised from the Network Devices view
without checking the others, and then used it to justify a design decision. The
churn argument still stands on its own evidence; the appeal to vendor behaviour
does not, and the vendor in fact does the opposite.

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

| Command | Result | Evidence level |
|---|---|---|
| `pytest -q backend/tests/test_bolero_ws.py` | **17 passed** | software verification (Windows rig) |
| Live listener against `192.168.1.11` for 120 s | **did not converge** — see below | **verified on actual gear** |

The accumulator's 11 tests were written first and watched failing. The 6
lifecycle tests are characterisation: the listener class was written alongside
them rather than before, and that is recorded rather than presented as TDD.

## The approach does not work, and the live rig proved it

```text
REST says 9 packs online: [2, 4, 6, 30, 32, 33, 34, 35, 37]

  t+  2.0s  known=1   awaiting=8
  ...
  t+120.0s  known=5   awaiting=4
NOT CONVERGED in 120s - known 5, awaiting 4

listener status: state=running messages=54 restarts=0
stopped cleanly: state=stopped
```

The listener itself is fine — connected first try, 54 messages, zero restarts,
clean shutdown. It simply never learned where four of the nine packs were.

**`audioPorts` fires on handover. A pack that is not moving is never announced,
so a listen-only client cannot ever see it.** Two minutes of a real rig got 5 of
9. The remaining four would appear only when somebody carrying them walks
between antennas.

So the feature as designed would sit blank on a stable rig and populate only
while people move around — which is the opposite of useful, and precisely why
the `converged` guard exists. The guard worked: it refused to render 5 of 9 as
though it were the whole picture. That is the one part of this worth keeping.

## The contradiction that has to be resolved first

The Bolero GUI *does* show complete counts — 7 + 1 + 2 = 10, matching every
connected pack. And the devtools capture proves the GUI sends nothing but pings.
Both of those cannot be true alongside "the server only announces handovers",
so one of the following is the case and it is not yet known which:

1. the server pushes a full `audioPorts` set on connect under some condition the
   listener did not meet — a subprotocol, a header, or something tied to the
   `connectionToken` the server issues;
2. the GUI had simply been open long enough to see every pack hand over at least
   once, and would also show an incomplete picture on a cold load;
3. there is another message kind carrying full state that neither the 45 s nor
   the 120 s listen happened to catch.

**Distinguishing (1) from (2) is one observation:** open the Bolero GUI in a
fresh private window with devtools already recording, and watch whether the
antenna Beltpacks column is complete immediately or fills in over a minute or
two. If it is complete immediately, the server does send state on connect and
the listener is missing something recoverable. If it fills in gradually, then
the Bolero GUI has the same limitation and nobody can build this from this
protocol.

## What is kept

`BoleroAntennaCounts` and `BoleroAntennaListener` are sound and tested, and the
listener is wired into nothing, so nothing is at risk from leaving them in
place. If (1) turns out to be the answer, the accumulator is already correct and
only the connect handshake changes.

**Not merged, and should not be**, until the question above is settled. Shipping
it now would add a panel element that is blank almost always.
