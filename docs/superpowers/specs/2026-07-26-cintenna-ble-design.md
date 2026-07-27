# Cintenna BLE Discovery and Control — Design

**Date:** 2026-07-26
**Status:** approved design, ready for implementation planning
**Branch:** `feat/cintenna-ble` (based on `main`)

## Problem

Five12's Devices page shows Starlink, Bolero, and Stardust — all discovered over
IP. LumenRadio TimoTwo-based gear (RatPac Cintenna 2, Satellite) is invisible to
it, because those radios are reachable only over Bluetooth Low Energy.

Operators currently need CRMX Toolbox on a phone to answer "what CRMX gear is in
this room, what mode is it in, and how much battery does it have left" — and
Toolbox cannot be used at the same time as anything else, because it holds the
BLE connection exclusively.

## Goal

Add a **Cintennas** tab to the Devices page listing nearby TimoTwo-compatible
radios with their status, then add guarded configuration control including TX
Link and RX Unlink.

## Inputs

Two verified references in the private KB, both authoritative for this work:

- `10-Lighting/References/LumenRadio/timotwo-ble-discovery-and-gatt.md` —
  protocol reference. Advertisement signature, manufacturer-data decoder, GATT
  characteristic map, confirmed enum semantics, HCI-capture conclusions.
- `10-Lighting/References/LumenRadio/five12-cintenna-ble-implementation-plan.md` —
  18-task plan, written without repository access.

Task 0 recon of this repository is complete and recorded in
[`docs/architecture/ble-integration-map.md`](../../architecture/ble-integration-map.md),
which resolves every placeholder in the plan and lists seven points where the
plan's assumptions did not match the codebase.

## Scope

**In scope.** Passive discovery; connected read-only status; guarded writes for
RX/TX mode, DMX Hold, TX output power, TX universe color, TX protocol; TX Link;
RX Unlink; evidence labelling; audit logging; sim mode; automated tests; Windows
hardware acceptance.

**Out of scope — release blockers, not preferences.** Reading, storing, logging,
or writing linking keys. CRMX Classic vs CRMX2 selection. Firmware update. RDM
discovery or control. BLE DMX streaming. Generic OEM RX/TX commands. Writes to
unknown characteristics. Automatic receiver-to-Stardust-output or sACN-universe
correlation. Background configuration writes without operator confirmation.

## Architecture

BLE differs from every existing adapter in two ways that drive the whole design:
`bleak` is async, and useful scanning is continuous rather than request-scoped.
A synchronous `get_status()` that scans on demand would block a Flask worker on
every 10-second Devices poll and could not track first-seen/last-seen/RSSI
history at all.

**A long-lived daemon thread owns the radio; the web layer reads its registry.**

```
┌─ BLE service thread (one per host, started from app factory) ──┐
│  bleak event loop                                              │
│  passive scan → registry{os_id: DiscoveredDevice}              │
│  connection_manager (single-owner lock)                        │
└────────────────────────────────────────────────────────────────┘
        ▲ read (sync)                    ▲ run_coroutine_threadsafe
        │                                │ (bounded timeout)
┌───────┴──────────────┐      ┌──────────┴─────────────────────┐
│ CintennaAdapter      │      │ /api/ble/* blueprint           │
│ detect/get_status    │      │ connect, snapshot, commands    │
│ → GET /api/devices   │      │ gated by ENABLE_BLE_TOOLS      │
│ → tab strip          │      └────────────────────────────────┘
└──────────────────────┘
```

This reuses both patterns the repo already has — `scanner.py`'s daemon-thread
discovery loop and `integrations/`'s adapter contract — rather than introducing
a third.

**Rejected: scan-on-request inside `get_status()`.** Simplest and fits the
adapter contract exactly, but blocks a worker on every poll and structurally
cannot satisfy the first-seen/last-seen/smoothed-RSSI requirements.

**Rejected for now: standalone sidecar process.** Best crash isolation and free
single-radio ownership, but requires wiring into `start.ps1`, `launch.bat`,
`Procfile`, and the Electron main process. Documented as the fallback if
`bleak` proves unstable on Windows under load.

### Module layout

```
backend/app/five12_ble/
  constants.py           verified UUIDs, IntEnums, immutable write allowlist
  advertisement.py       pure manufacturer-data decoder
  decoders.py            pure byte → display decoders
  models.py              DiscoveredDevice, Snapshot, FieldValue dataclasses
  scanner.py             owns bleak loop + registry
  connection_manager.py  single-owner connections, bounded timeouts
  gatt_client.py         read-only snapshot builder
  command_service.py     mode-gated, allowlisted writes
  errors.py              typed failures
  sim.py                 fake advertisements + fake GATT

backend/app/integrations/cintenna.py    CintennaAdapter (sync facade)
backend/app/ble_routes.py               /api/ble/* blueprint

app/src/components/devices/CintennaPanel.jsx
app/src/components/devices/BleEvidenceBadge.jsx
app/src/components/devices/BleActionDialog.jsx
app/src/lib/bleApi.js
```

`constants.py`, `advertisement.py`, and `decoders.py` are pure — no I/O, no
`bleak` import — which is what lets fixture-driven tests run without a radio or
the dependency installed.

### Feature gate

`ENABLE_BLE_TOOLS` from `FIVE12_BLE_TOOLS`, mirroring `ENABLE_NETWORK_TOOLS`'s
pattern in `backend/config.py` and the factory, with one deliberate difference:
**it defaults off.** `FIVE12_NETWORK_TOOLS` defaults on because probing the
operator's own LAN is expected; starting a radio scan without being asked is
not.

When the gate is off, `/api/ble/*` routes do not exist, and no BLE thread
starts. `CintennaAdapter.detect()` still returns `found: false` with
`detail: "BLE tools disabled"` — the tab stays visible and honest about why it
is empty. Adapter present but no Bluetooth hardware yields
`detail: "no Bluetooth adapter"`.

### Single radio ownership

The BLE thread starts from the app factory like `start_scanner`, plus a guard
the ARP scanner does not need: a process-local flag and an OS-level lock file,
so under gunicorn exactly one worker owns the adapter. Losing the lock is a
normal state, reported as "another Five12 process owns the Bluetooth adapter",
not an error.

### Frontend

`PANELS` in `app/src/pages/Devices.jsx` gains `cintenna: CintennaPanel`; the tab
button appears because `GET /api/devices` reports the device. The other three
panels stay inline in that file — extracting them is unrelated churn.

`CintennaPanel` is the largest of the four panels (roster, detail, evidence
drawer, confirmation dialogs) so it lives in its own file. Shape follows the
Stardust multi-unit precedent: roster list → select → detail.

State is local `useState` plus interval polling, matching sibling panels. No
store is introduced, because none exists.

## Data flow

**Read.** Passive scan never connects:

```
bleak scan loop → registry.upsert(os_id, name, rssi, mfr_data, seen_at)
  → CintennaAdapter.detect()     → GET /api/devices     → tab strip
  → CintennaAdapter.get_status() → GET /api/ble/devices → roster
```

**Connected.** Explicit and operator-initiated, never automatic:

```
POST /api/ble/devices/{id}/connect
  → acquire single-owner lock
  → enumerate services; read only characteristics advertising Read
  → per-field try/except: a failed read yields {value: null, error: "..."}
    and does not fail the whole snapshot
  → disconnect unless the UI holds an explicit management session
```

A *management session* is a short window in which the panel keeps one device
connected for consecutive operations rather than reconnecting per read. It is
opened only by an explicit operator action, has a bounded idle timeout, releases
the single-owner lock on close or timeout, and is the only circumstance in which
a BLE connection outlives a single request.

### Evidence model

Every field is `{raw, decoded, source, readAt}` where `source` is one of
`advertisement | gatt-read | mirror | user-write | post-write-readback`. The UI
renders this as a badge.

This makes the reference's language rules structural rather than conventional:

- *Nearby ≠ connected.* Roster entries carry no GATT fields until connection.
- *TimoTwo-compatible ≠ Cintenna 2.* `platform` and `product` are separate
  keys; `product` stays `null` absent OEM evidence.
- *Link accepted ≠ receiver linked.* The result field is
  `attAcknowledged: true`. There is deliberately no field named `linked`.
- *RSSI is not distance.* Displayed as signal bars and raw dBm, never metres.

Unknown enum values decode to `null`, never an exception. RX's
`OUTPUT_POWER = 0x80` and `TX_PROTOCOL = 0xFF` render as "not applicable in RX",
not as errors. Output power retains raw enum, official module figure, and
Toolbox label as three separate properties — the UI must not manufacture
precision by reconciling them.

### Write path

```
POST /api/ble/devices/{id}/commands  {command, expectedMode, confirmationToken}

1. allowlist     command name must be in the typed table
2. freshness     server re-reads MODE from the device; stale client snapshot rejected
3. mode gate     power/color/protocol/link require TX; unlink requires RX
4. confirmation  server-issued token bound to (device, command, snapshot version), 60s TTL
```

**The client cannot name a UUID or a payload byte.** It names `"link"`; the
server maps that to `45a41003 ← 0x05`. The release blocker "any arbitrary UUID
write path" is made structurally impossible rather than policed.

The UI disables impossible controls, but the backend re-checks every rule
independently. A disabled button is a courtesy, not a security boundary.

Characteristics are resolved **by UUID on every connection**. ATT handles are
never used in production code; the observed `0x003C` for `LINK_ACTION` is
session- and firmware-specific.

### Command policy table

| Command | Required mode | Payload | Verification |
|---|---|---|---|
| `set_mode_rx` | any known | `MODE=00` | reconnect, verify RX |
| `set_mode_tx` | any known | `MODE=01` | reconnect, verify TX |
| `set_dmx_hold` | RX or TX | `00`/`01` | verify same value |
| `set_output_power` | TX | `02`/`03`/`04`/`05` | verify same raw enum |
| `set_universe_color` | TX | three RGB bytes | verify same RGB |
| `set_tx_protocol` | TX | `00`/`01`/`03` | reconnect if dropped, verify |
| `link` | TX | `LINK_ACTION=05` | ATT acknowledgement only |
| `unlink` | RX | `LINK_ACTION=00` | ATT acknowledgement, refresh snapshot |

Hard rejections: unknown command, unknown UUID, wrong mode, malformed RGB,
invalid enum, stale snapshot, absent confirmation, device identity mismatch, and
any command issued while another operation owns the connection.

### Reboot-tolerant writes

`set_mode_*` and `set_tx_protocol` can restart the module, so they run a state
machine rather than expecting a clean response:

```
write accepted → expect disconnect → bounded rediscovery
  → reconnect → re-read field
  → report "verified" | "accepted, unverified" | "device did not return"
```

**"Accepted but unverified" is a first-class operator-visible outcome**, not an
error swallowed into a success.

## Error handling

Typed errors, each with operator-facing copy: BLE tools disabled, no adapter,
adapter powered off, device out of range, device busy, **CRMX Toolbox holds the
connection**, characteristic missing, timeout, disconnect during reboot, lock
contention.

The Toolbox conflict is the most likely failure in practice and gets explicit
detection with a message naming Toolbox and telling the operator to close it.

Per-field read failures degrade rather than cascade: a missing firmware
characteristic yields one null field, not a failed device.

## Audit logging

Recorded: timestamp, operation, device alias, mode, symbolic UUID name, payload
enum name, ATT accepted/rejected, readback result, error class, duration.

Never recorded: linking keys, opaque blobs (`10351003`), full OS identifiers by
default, unrelated BLE traffic, Android bug reports.

Exportable as a redacted diagnostic report containing only Five12 operations.

## Testing

**Backend** — pytest, flat in `backend/tests/` as `test_ble_*.py`.

Pure-module tests need no radio and no `bleak`:

- `test_ble_constants.py` — exact UUID strings; **write allowlist contains no
  UUID outside the verified set**. This test is the release gate for "no
  arbitrary write path".
- `test_ble_advertisement.py` — `03F14000004C55F140` decodes to hardware
  `F1400000`, ESTA `4C55`, model `F140`; case-insensitive service match;
  malformed payload returns partial without raising; `0x09E9` and `0xFFFF` both
  accepted as evidence, neither treated as enclosure identity; byte 0 preserved
  raw.
- `test_ble_decoders.py` — firmware `02 07 00 01` → `1.0.7.2`; unknown enums →
  `null`; RX `80`/`FF` → not-applicable.

`FakeBleakClient` records writes so command tests assert exact wire bytes:

```python
fake.assert_write("45a41003-2ccd-80a5-b844-095c73b6c7e3", bytes([0x05]), response=True)
```

Plus wrong-mode rejection, missing-confirmation rejection, stale-snapshot
rejection, scanner lifecycle (coalescing, RSSI update, stale expiry,
cancellation), connection timeout, disconnect handling, Toolbox-conflict error,
and the reboot/reconnect state machine.

**Frontend** — Vitest + React Testing Library, newly added, **scoped to BLE
components only**. Existing untested components are not backfilled; that is
unrelated to this feature. Covers roster rendering, mode-dependent control
enable/disable, confirmation dialogs, and error states.

**Sim mode** — `?sim=1` / `FIVE12_DEVICE_SIM=1` fabricates advertisements and
GATT values matching the captured fixtures, following the existing adapter
convention, so the panel is developable and demoable without hardware.

**Hardware acceptance** — the plan's Task 17 checklist on the Windows 11
ThinkPad against the known Cintenna at firmware `1.0.7.2`. Includes deliberately
opening Toolbox to confirm the conflict error is useful, and disabling BLE tools
to prove Patch/Labels/Network still work.

## Build sequence

```
0  recon .......................... DONE (docs/architecture/ble-integration-map.md)
1  gate + capabilities endpoint
2  constants + allowlist
3  advertisement decoding          ─┐
4  passive scanner + registry       │
5  connection manager               │ read-only
6  GATT decoders                    │
7  read-only snapshot               │
8  /api/ble read endpoints          │
9  Cintenna tab + roster UI        ─┘
   ═══ READ-ONLY GATE — demo on real gear ═══
10 command policy
11 guarded config writes
12 TX Link
13 RX Unlink
14 config panel + confirmations
15 audit log
16 automated test gate
17 Windows hardware acceptance
18 release gate + operator docs
```

Tasks 1–9 cannot write to a radio because `command_service.py` does not exist
yet at that point. **The gate is structural, not a promise.**

## Definition of done

- Five12 passively discovers a nearby TimoTwo-compatible device on Windows.
- BLE devices are visually and structurally distinct from Ethernet/Art-Net gear.
- Device identity is evidence-based and does not overclaim enclosure model.
- Connected reads match the verified fixture captures.
- TX Link writes `05` to `45a41003…` and receives an ATT response.
- RX Unlink writes `00` to `45a41003…` and receives an ATT response.
- Commands are allowlisted, mode-gated, confirmed, and read back where possible.
- Reboot/disconnect never leaves a stuck UI session.
- Toolbox conflicts produce a clear operator message.
- No linking-key, firmware-update, RDM, DMX-streaming, or unknown-write
  capability exists in the release.
- Automated tests pass without hardware.
- The Windows acceptance checklist passes on the known Cintenna.
- `FIVE12_BLE_TOOLS` unset leaves Patch, Labels, Network, and Devices fully
  functional.

## Open risks

- **`bleak` on Windows** is unproven in this app. Task 1 validates adapter
  enumeration on the ThinkPad before any further work. If it proves unstable,
  the sidecar-process architecture is the documented fallback.
- **BLE identity is not stable.** Resolvable private addresses may rotate; the
  captured unit reports address resolution supported. Roster identity is
  best-effort and labelled as such.
- **ATT acknowledgement is not RF association.** Proven by HCI capture that the
  device accepts the write; nothing more. The UI must never imply otherwise.
- **Link testing pairs nearby unlinked receivers.** Hardware acceptance for
  Task 12 needs RF isolation or accepted risk to other gear in range.
