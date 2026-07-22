# Bolero beltpack battery panel — design

Date: 2026-07-22 · Branch `edit_export` · Status: approved, ready to implement

## Goal

Show, in the Devices page Bolero panel, the visible Riedel antennas and the
beltpacks attached to each, with live battery life — from the real hardware,
not the simulator. The panel UI already exists (`app/src/pages/Devices.jsx`
`BoleroPanel`); this wires it to verified live data.

## Verified API (from a real unit, HAR 2026-07-22)

- Base `http://192.168.1.11/rest/…`, plain HTTP. Auth: HTTP Basic, the factory
  read-only account the GUI itself uses (`user` / `userPass`). No login flow.
- `GET /rest/nodeConfig` — antenna identity: `nodeId → name`, ip, isLocal.
  (`132651929` = "MBS LM 2" = .11; `163060633` = "MBS LM 1" = .12)
- `GET /rest/nodeStatus` — antennas + **live per-pack battery**. Each node has
  `bp[]` of the packs *currently connected to that antenna*; each pack:
  `id`, `battery{status(=charge %), currentCharge(mAh), usbPower, batteryTemperature,
  batteryHealth, maxCharge}`, `signalLevel`, `timeslots{…}`. Node also carries
  `temperature`, `ptpStatus{lockState,…}`.
- `GET /rest/bp` — roster mapping DECT `id → bpConfig.bpName` (the crew name,
  e.g. 34 → "Anthony"). ~98 KB.
- `ws://192.168.1.11/wsapp` exists for live push — **out of scope v1**.

## Design

### Backend — finish `backend/app/integrations/bolero.py`

Read-only, polling. Keeps the existing adapter interface and the simulator.

- `ENDPOINTS` → the three real paths. `VERIFIED_AGAINST_UNIT = True`.
- Credentials via env `FIVE12_BOLERO_USER` / `FIVE12_BOLERO_PASS`, defaulting to
  the documented read-only account. Host stays `FIVE12_BOLERO_HOST`.
- `_real_status()` each poll: GET `nodeStatus` + `nodeConfig` (small, ~6 KB),
  join pack → antenna → crew name, normalize.
- **Name cache:** `/rest/bp` is large, so fetch it at most every 300 s and cache
  the `{id: name}` map on the adapter. Live battery still polls every cycle.
- `_normalize()` output (unchanged contract the frontend already reads):
  - `antennas[]`: `{id, name, online, ptpSynced, packCount}`
    (`ptpSynced` = `ptpStatus.lockState == 2`).
  - `beltpacks[]`: `{id, name, batteryPct, mAh, healthPct, tempC, charging,
    antenna, online}`, sorted lowest-battery-first. `online=True` for any pack
    present in a node's `bp[]` (that is what "attached" means here).
  - `packsOnline`, `lowestBatteryPct`, `ptpSynced` (all antennas), plus the
    existing `alerts` via the current threshold rules.
- All outbound requests go only to the validated private `FIVE12_BOLERO_HOST`
  (`require_private_host`), never to anything derived from request input.

### Frontend — minimal edits to the existing `BoleroPanel`

- Replace the placeholder "Signal" column with **Health %** and show a ⚡ in the
  State column when `charging`. (`signalLevel` is a 0/1 scale, not a percent —
  showing it as "%" would mislead, so it is dropped in favour of health, which
  is real and meaningful.)
- Update the footer note from "endpoint map unverified" to note it is verified,
  read-only REST.
- Simulator gains `healthPct` + `charging` so `?sim=1` still matches the shape.

## Testing

- Unit tests over `_normalize` using the real captured payloads (fixtures):
  correct pack→antenna→name join, battery/health/charging mapping, lowest-first
  sort, `packsOnline`/`lowestBatteryPct`, and the alert thresholds.
- Name-cache TTL: `/rest/bp` fetched once then reused within the window.
- Live check against `.11` (read-only GETs) before calling it done.

## Out of scope (v1)

WebSocket live push; party-line / audio-channel views; anything that writes to
the intercom; per-pack RF-quality visualization from `timeslots`.
