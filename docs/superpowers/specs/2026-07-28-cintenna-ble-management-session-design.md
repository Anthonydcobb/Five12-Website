# Cintenna BLE Management Session — Design

**Date:** 2026-07-28
**Status:** approved design, ready for implementation planning
**Branch:** `feat/cintenna-ble` (continues the write phase)

## Problem

The write phase works on real hardware, but it is too slow to use on a show.

Measured on the actual Cintenna (`F12L - 1946`, firmware `1.0.7.2`) on 2026-07-28:

| Operation | Cost | Why |
|---|---|---|
| One connect → read → disconnect | **5.8 – 8.2 s** | Windows BLE connect plus GATT service discovery |
| Link or Unlink | **~12 – 16 s** | `prepare` pays one full cycle, `execute` pays another |
| Mode change | **~25 – 35 s** | those two, plus a 2 s wait, plus reconnect polling across the reboot |

CRMX Toolbox performs the same operations in well under a second. The
difference is not the write — it is that Toolbox connects **once** and holds
that connection for the whole session, while Five12 sets up and tears down a
connection for every operation, twice per action.

The operator's words: *"on a production environment speed is helpful."* A
15-second Link is not usable during a show.

## Goal

Hold one connection open while the operator is working with a radio, so the
~7-second setup is paid once instead of twice per action. Link and Unlink
become effectively instant; a mode change costs only the reboot itself.

## Prerequisite met

The write phase's hardware gate passed on 2026-07-28: a real Cintenna was
discovered, read, and written to successfully from the Devices page. This
design optimises a path that is known to work, rather than one inferred from
capture files.

## Decisions taken

| Decision | Chosen | Rejected, and why |
|---|---|---|
| Release rule | 90 s idle, counting operator actions only | 5 min (a radio walked away from stays locked too long); hold-until-deselect (a closed lid wedges the radio until the backend restarts) |
| When the session opens | **Lazily, on the operator's first action** | On selection — idly clicking through a roster would seize radios one after another, each grab blocking Toolbox |
| Status refresh | Re-read after a write completes | Background polling every 5 s — more traffic, and it forces the idle timer to distinguish operator actions from its own reads. Deferred, not rejected; easy to add later |
| Authority for release | Server-side | Browser-side — a closed tab, a slept laptop, or a crashed renderer never sends the close |

## Architecture

One new module owns every open connection. Nothing else may hold one.

```
backend/app/five12_ble/session_manager.py   NEW — at most one live connection
backend/app/five12_ble/connection_manager.py   + session-aware acquisition
backend/app/five12_ble/command_service.py      routes through the session
backend/app/ble_command_routes.py              + session close endpoint
app/src/components/devices/CintennaPanel.jsx   + held indicator, close on switch
```

The session manager lives on the scan service's existing event loop, for the
same reason every other BLE operation does: `bleak`/WinRT tolerates exactly one
loop driving the adapter, and the scan service already owns it.

**At most one session exists process-wide.** Not one per device — the adapter is
a single resource, and a second held connection would contend with the first.
Acquiring a session for a different radio closes the previous one first.

### Session lifecycle

```
first operator action on radio X
  → no session, or session belongs to another radio
      → close any existing session
      → open a connection to X, record it, stamp last-activity
  → session belongs to X and is live
      → reuse it, stamp last-activity

release when ANY of:
  - 90 s elapse since the last operator action
  - the operator selects a different radio, or leaves the Cintennas tab
  - the radio disconnects on its own (out of range, or a mode-change reboot)
  - the backend shuts down
```

The idle sweep runs on the scan loop. It is the authority: the browser is a
hint, never a guarantee.

### Interaction with the existing device lock

`connection_manager` currently takes a per-device lock for the duration of one
`connect()` context. A held session extends that hold to as long as 90 seconds.
Two consequences the implementation must handle rather than discover:

- The passive scan must keep running while a session is held. Discovery and
  connection are separate concerns in `bleak`; if they prove not to be on
  Windows, the roster going stale during a session is a defect, not a
  tolerable side effect.
- A second Five12 process must still fail cleanly with the existing
  `DeviceBusy` / `NotOwner` copy rather than blocking.

## What does not change

**Every safety check stays exactly where it is.** Before each write the server
still re-reads the radio's live mode and re-checks the allowlist, the
confirmation token, device identity, snapshot freshness, and the mode gate.

These are gates, not optimisations. Holding the connection makes them nearly
free; it does not make them optional. The speed comes from removing connection
setup, never from removing a check. An implementation that skips the freshness
re-read because "we just read it" has broken the feature, not optimised it.

## Frontend

Selecting a radio does nothing over Bluetooth. The first action — normally
**Read status** — opens the session, and everything after that reuses it.

**The panel shows when a radio is held.** This is not decoration. While Five12
holds the connection, CRMX Toolbox gets a bare failure with no explanation, so
anyone standing beside the operator with a phone deserves to know why. It also
tells the operator whether the next click is instant or costs seven seconds.

Switching radios or leaving the tab sends a best-effort close. The server's
idle timer is the real guarantee.

After a successful command the panel re-reads status automatically instead of
requiring another click — the operator's original request, and nearly free on a
held connection.

## Error handling

- **Session dropped, operator acts** — open a fresh connection transparently.
  One slow action, not an error.
- **Mode-change reboot** — expected to kill the session. Discard it and let the
  existing reboot-verification state machine reconnect as it already does. The
  hazard is a stale session object that believes it is still connected, so the
  manager must detect the drop rather than assume liveness.
- **Toolbox holds the radio** — unchanged; still reported by name.
- **Close on a session that no longer exists** — succeeds silently. It is a
  best-effort hint from a client that may be out of date.

## Testing

The load-bearing assertion: **two consecutive commands cause exactly one
connect.** Without it the feature could silently regress to today's
connect-per-operation behaviour and every other test would still pass.

Also covered, each with a fake clock so no test waits real seconds:

- idle expiry releases at 90 s, and operator actions push the deadline out
- acquiring a session for a second radio closes the first
- an explicit close releases, and a close for an unknown session is a no-op
- a dropped connection is detected, not assumed live
- a mode-change reboot leaves no stale session behind
- the freshness re-read still happens on every command inside a held session —
  this is the regression test protecting the safety-versus-speed boundary

## Open questions

- Whether a held connection degrades passive scan throughput on Windows.
  Measure during acceptance; if the roster goes stale while connected, the
  session must yield periodically.
- Whether 90 s is right in practice. It is a starting point chosen against a
  show workflow, not a measured figure.

## Definition of done

- Link and Unlink complete in well under a second once a session is open.
- The ~7 s setup is paid once per radio, not twice per action.
- A forgotten browser tab releases its radio within 90 seconds.
- The panel shows when a radio is held.
- Status refreshes itself after a write.
- Every write still passes allowlist, token, identity, freshness and mode gate.
- `FIVE12_BLE_WRITE` unset still yields exactly the read-only build.
