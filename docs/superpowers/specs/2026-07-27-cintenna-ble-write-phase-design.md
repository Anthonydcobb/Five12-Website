# Cintenna BLE Write Phase — Mode, Link, Unlink — Design

**Date:** 2026-07-27
**Status:** approved design, ready for implementation planning
**Branch:** `feat/cintenna-ble` (continues the read-only phase)

## Problem

The read-only phase shipped a Cintennas tab that discovers TimoTwo-compatible
radios and reads their status. It cannot change anything. An operator who needs
to flip a Cintenna between receiver and transmitter, pair a receiver to a
transmitter, or drop a receiver off its transmitter still has to reach for CRMX
Toolbox on a phone — and Toolbox holds the BLE connection exclusively, so it
cannot be used alongside Five12.

## Goal

Operator-initiated, mode-gated, confirmed writes for exactly three operations:
switch a radio between RX and TX, Link from a transmitter, Unlink a receiver.

## Prerequisite met

The read-only phase was parked pending the hardware gate in
[`../../architecture/cintenna-ble-handoff.md`](../../architecture/cintenna-ble-handoff.md).
**That gate is now met:** on 2026-07-27 a real Cintenna appeared in the passive
scan roster and a connected status read returned battery, firmware, and mode.
Design decisions below can be grounded in observed behaviour rather than
inference — with the exception of reboot timing, which is explicitly deferred to
acceptance (see [Open questions](#open-questions)).

## Inputs

- Read-only phase design:
  [`2026-07-26-cintenna-ble-design.md`](2026-07-26-cintenna-ble-design.md) —
  its command policy table and evidence model are carried forward, not restated
  from scratch.
- Handoff and release blockers:
  [`../../architecture/cintenna-ble-handoff.md`](../../architecture/cintenna-ble-handoff.md)
- Protocol source of truth, private KB:
  `10-Lighting/References/LumenRadio/timotwo-ble-discovery-and-gatt.md`

## Decisions taken in this design

Recorded because each was a genuine fork, and the reasoning matters more than
the outcome:

| Decision | Chosen | Rejected |
|---|---|---|
| Command scope | Four commands only | All eight from the original table — five extra commands nobody asked for, each carrying its own hardware-acceptance cost |
| Write gate | Second env var, `FIVE12_BLE_WRITE` | Reusing `FIVE12_BLE_TOOLS` — discovery and writing are different risks and deserve different switches |
| Mode + action | Separate deliberate steps | Chaining "switch to TX then link" behind one confirmation — hides a reboot inside an unrelated action |
| Confirmation | Modal, checkbox-gated, per write | `window.confirm` (used by the Stardust panel) — accepts on Enter, which is exactly the failure mode to design out |
| Operating assumption | Live show, gear on air | Bench-only friction |

## Scope

**In scope.** `set_mode_rx`, `set_mode_tx`, `link`, `unlink`. Server-issued
confirmation tokens. Mode-gated command policy. Reboot-tolerant verification.
Audit logging. Write-side sim support. Automated tests. Hardware acceptance.

**Out of scope — unchanged release blockers from the read-only phase.** Reading,
storing, logging, or writing linking keys. Firmware update. RDM. BLE DMX
streaming. Generic OEM commands. Writes to unknown characteristics. Any write
without operator confirmation. Any claim that a radio is "linked".

**Deliberately deferred, not rejected.** `set_dmx_hold`, `set_output_power`,
`set_universe_color`, `set_tx_protocol`. The policy table is data; each is one
row plus its own acceptance run when wanted.

## Architecture

No new architecture. The read-only phase's daemon-thread-owns-the-radio design
holds unchanged; this adds one module and one route pair to it.

```
backend/app/five12_ble/command_service.py    NEW — the entire write surface
backend/app/ble_routes.py                    + POST commands/prepare, POST commands
app/src/components/devices/BleActionDialog.jsx   NEW — confirmation modal
app/src/components/devices/CintennaPanel.jsx     + Control section
app/src/lib/bleApi.js                            + prepare/execute wrappers
```

The existence of `command_service.py` is itself the phase boundary. Tasks 1–9
could not write to a radio because this file did not exist; that was structural,
not a promise. The same structure now confines every write to one module.

### Feature gate

`ENABLE_BLE_WRITE` from `FIVE12_BLE_WRITE`, defaulting off, **in addition to**
`ENABLE_BLE_TOOLS`. Both must be on for the command routes to be registered.
With `FIVE12_BLE_TOOLS=1` alone the app behaves exactly as the read-only phase
shipped: discovery and status reads, no write routes in the URL map, no write
controls in the UI.

A machine that can only ever read is worth keeping as the default.

## Command policy

The whole write surface, frozen, in `command_service.py`:

| Command | Characteristic | Payload | Required mode | Verification |
|---|---|---|---|---|
| `set_mode_rx` | `MODE` `33b5376f-…` | `0x00` | any *known* mode | reboot-tolerant, re-read `MODE` |
| `set_mode_tx` | `MODE` `33b5376f-…` | `0x01` | any *known* mode | reboot-tolerant, re-read `MODE` |
| `link` | `LINK_ACTION` `45a41003-…` | `0x05` | TX | ATT acknowledgement only |
| `unlink` | `LINK_ACTION` `45a41003-…` | `0x00` | RX | ATT acknowledgement, then refresh snapshot |

`WRITABLE_UUIDS` is **derived from this table**, never hand-written. It resolves
to exactly `{MODE, LINK_ACTION}`, both already members of the captured constant
set in `constants.py`.

**The client cannot name a UUID or a payload byte.** It posts
`{"command": "link"}` and the server performs the mapping. The release blocker
"no arbitrary UUID write path" is therefore structurally impossible rather than
policed by review.

Characteristics are resolved by UUID on every connection. ATT handles are never
used in production code — the observed `0x003C` for `LINK_ACTION` is session-
and firmware-specific.

An unknown current mode is not a reason to guess. `set_mode_*` requires the
device to report a *known* mode first, so a radio whose `MODE` decodes to `null`
gets no write path at all until that is understood.

## Write path

Two steps, because a confirmation the server did not issue is not a
confirmation.

```
POST /api/ble/devices/{osId}/commands/prepare   {command}
  → connect, read current MODE and hardware id
  → {token, ttlS: 60, deviceAlias, currentMode, warning}

POST /api/ble/devices/{osId}/commands           {command, expectedMode, confirmationToken}
```

The token is server-issued, single-use, 60-second TTL, and bound to *(osId,
hardware id, command, mode observed at prepare)*. A stale browser tab cannot
replay it, and a token minted for one command cannot execute another.

`warning` is server-supplied text, rendered verbatim by the dialog, so the copy
the operator agrees to is the copy the server enforces.

### Checks on execute, in order

Every check runs server-side regardless of what the UI did. A disabled button is
a courtesy, not a security boundary.

1. **Gates** — both on, or the route does not exist
2. **Allowlist** — command name is in the typed table
3. **Token** — valid, unexpired, unused, matches this device *and* this command
4. **Freshness** — server re-reads `MODE` from the radio; reject if it no longer
   matches the client's `expectedMode`. Someone may have turned a knob since the
   dialog opened.
5. **Identity** — hardware id from manufacturer data matches the token's. BLE
   addresses rotate; this stops a write landing on the wrong radio.
6. **Mode gate** — `link` requires TX, `unlink` requires RX
7. **Ownership** — single-owner connection lock, or reject as busy

Hard rejections, each with operator-facing copy: unknown command, wrong mode,
unknown or absent mode, stale snapshot, missing/expired/replayed token, identity
mismatch, another operation owns the connection.

### Reboot-tolerant verification

Writing `MODE` restarts the module, so mode commands run a state machine rather
than expecting a clean response:

```
write accepted → expect disconnect → bounded rediscovery
  → reconnect → re-read MODE
  → "verified" | "accepted-unverified" | "device-did-not-return"
```

**"Accepted, unverified" is a first-class operator-visible outcome**, never
smoothed into a success and never reported as an error.

### Result shape

```json
{"command": "link",
 "attAcknowledged": true,
 "verification": "ack-only",
 "mode": {"decoded": "tx", "source": "post-write-readback"},
 "durationMs": 412}
```

`verification` is a closed set of four values: `ack-only` (link, unlink),
`verified`, `accepted-unverified`, `device-did-not-return` (mode writes).

There is deliberately no field named `linked`. An ATT acknowledgement proves the
radio accepted the write and nothing more; it is not evidence of RF
association, and no layer of this system will imply otherwise.

### Capabilities

`capabilities()` gains `bleWriteEnabled`. Unlike the existing
`bleToolsEnabled: True` — a tautology, since the route only exists when tools
are on — this one carries real information: the read routes exist whenever tools
are enabled, but writes may still be off. This is also what finally gives
`bleApi.fetchBleCapabilities` a caller; it has been exported and tested but
unused since the read-only phase.

### Sim

`sim.py` gains a write side so the panel stays developable without hardware:
commands mutate the fake GATT state, `link`/`unlink` acknowledge, and a mode
write simulates the reboot by dropping the device from the roster and returning
it after a short delay. Shape parity with the real path is asserted, as it
already is for reads.

## Frontend

### Control section

The detail card in `CintennaPanel.jsx` gains a Control section, rendered only
when all of the following hold — otherwise absent, not merely disabled:

- the server reports the write gate on, via the capabilities endpoint
- a snapshot has been read, so the real mode is known
- the radio is still in the roster (`selectedNearby`)

With the write gate off, the panel states why, matching the copy pattern the
read gate already uses.

### Mode toggle and the action button

A segmented `[ RX ][ TX ]` control shows the radio's reported mode as the active
segment with its evidence badge. Clicking the other segment is the write.

The action button is **never both**: `mode === 'tx'` renders Link, `mode ===
'rx'` renders Unlink. Mode `null` renders neither.

This is the "separate steps" decision made structural — there is no path from an
RX radio to the Link button except through a completed, verified mode change.

### Confirmation dialog

`BleActionDialog.jsx`, a real modal, deliberately **not** `window.confirm`.

- Titled with advertised name **and** hardware id
- Renders the server-supplied `warning` verbatim
- Confirm disabled until an "I understand" checkbox is ticked
- **Enter does nothing.** Esc cancels.
- While a command is in flight, roster buttons and other controls are disabled

Warning copy per command:

- **Link** — any unlinked receiver in range will pair to this transmitter
- **Unlink** — this receiver loses its transmitter; anything it feeds goes dark
- **Mode** — the radio will restart and disappear for several seconds

### Outcome copy

Mode change shows live progress through the reboot with the bounded timer
visible, resolving to verified, "accepted, unverified" (amber, prompting a
status re-read), or "device did not return".

Link resolves to: *"Write accepted by {name}. A receiver in range may now be
paired. This is not confirmation that a link was made."* There is no green
"Linked ✓" state, because the system has no evidence that would justify one.

## Testing

### Inverted guard tests

The read-only phase's four guards assert a write path does not exist. They are
**inverted, not deleted** — the guarantee gets narrower, not removed.

| Test | Was | Becomes |
|---|---|---|
| `test_ble_constants.py` | no write allowlist exists | `WRITABLE_UUIDS` is exactly `{MODE, LINK_ACTION}` and a subset of the captured constants |
| `test_ble_routes.py` | no mutating route in `url_map` | the only mutating routes are `/commands` and `/commands/prepare`, and both are absent with the write gate off |
| `test_ble_gatt_client.py` | read client exposes no write method | unchanged and still true — writes live in a separate object |
| `CintennaPanel.test.jsx` | no Link/Unlink control renders | nothing renders with the gate off; Link only in TX; Unlink only in RX; never both |

### New coverage

`test_ble_command_service.py`, using the existing `FakeBleakClient` to assert
exact wire bytes:

```python
fake.assert_write('45a41003-2ccd-80a5-b844-095c73b6c7e3', bytes([0x05]), response=True)
```

Plus rejection of wrong mode, unknown mode, unknown command, missing/expired/
replayed token, stale `expectedMode`, identity mismatch, and concurrent
ownership; all three reboot-state-machine outcomes; and an audit-log assertion
that entries carry symbolic names and never key material.

Frontend Vitest coverage: mode-gated rendering, checkbox gating, Enter does not
confirm, and the "accepted, unverified" copy.

### Debt paid while here

The handoff flagged this as *"do it before the write phase"*: add a direct
assertion that every UUID in `gatt_client._FIELDS` is a member of
`READABLE_UUIDS`, so that constant enforces something instead of holding only
transitively.

## Hardware acceptance

Two items need care beyond a normal checklist run:

- **Link pairs any unlinked receiver in range.** This run needs RF isolation or
  knowingly accepted risk to other CRMX gear present.
- **Reboot timing is measured, not chosen.** The rediscovery timeout is set from
  observed behaviour on the real radio.

Also: Toolbox conflict *during* a write, write gate off leaves the read-only
build intact, and both gates off leaves Patch/Labels/Network/Devices working.

## Open questions

- Rediscovery timeout after a `MODE` write — deliberately unset until measured.
- Whether device identity survives a mode-change reboot, or the OS presents a
  new address. Affects whether the UI can re-select the radio automatically or
  must ask the operator to pick it again from the roster.

## Definition of done

- A Cintenna can be switched between RX and TX from the Devices page, with the
  reboot surfaced honestly.
- Link writes `0x05` to `45a41003-…` in TX and reports an ATT acknowledgement
  without claiming a link was made.
- Unlink writes `0x00` to `45a41003-…` in RX and refreshes the snapshot.
- Every write is allowlisted, mode-gated, token-confirmed, and identity-checked.
- No linking-key, firmware-update, RDM, DMX-streaming, or unknown-write
  capability exists.
- `FIVE12_BLE_WRITE` unset yields exactly the read-only build.
- `FIVE12_BLE_TOOLS` unset leaves Patch, Labels, Network, and Devices fully
  functional.
- Automated tests pass without hardware; the acceptance checklist passes with it.
