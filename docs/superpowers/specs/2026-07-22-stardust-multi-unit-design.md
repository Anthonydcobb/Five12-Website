# Stardust multi-unit selector

**Date:** 2026-07-22
**Status:** approved

## Problem

Multiple Stardusts can be on the network. The panel's "Units on network" table
already lists them all by MAC, but the status header, A–H output cards, and LINK
buttons only ever reflect the **first** discovered unit (`hits[0]` in
`_real_status`). So a second unit's outputs can't be seen or linked.

## Design

Select one unit at a time; everything rich (status / outputs / LINK) targets the
selected unit's **MAC** (stable identity; IPs change, labels are MAC-keyed).

### Backend (`stardust.py`, `device_routes.py`)

- `get_status(mac=None)` / `_real_status(mac=None)`: filter discovered Stardusts to
  the requested MAC. No MAC → first unit (today's behaviour, backward compatible).
  Unknown MAC → `available: False`, reason `Stardust <mac> not found`.
- **Sticky availability keyed by MAC.** Replace the single `_last_stardust` slot with
  `_last_seen: {mac: {node, at}}`. `_sticky_node(mac)` returns that MAC's held node
  within `STARDUST_STICKY_SEC`; with no MAC, the most-recently-seen fresh node. This
  stops unit A's held reading leaking into unit B.
- `link_output(out_nr, mac=None)`: resolve the target unit's IP by MAC via
  `_stardust_ip(mac)` instead of always `hits[0]`.
- Status route forwards `?mac=` (stardust only); link route accepts `mac` in the body.
  MACs normalised to uppercase colon form (matches discovery output).
- `discover_units()` unchanged (already returns all units).

### Frontend (`Devices.jsx` StardustPanel)

- `useDevice(id, query='')` gains an optional query string so status/history can carry
  `?mac=`.
- Unit-selector **chip row** at the top of the panel: one chip per discovered unit,
  labelled `label || longName || shortName || mac`, selected highlighted. **Hidden when
  ≤1 unit** (single-unit setups unchanged). Defaults to the first unit; always visible
  even if the selected unit reads unavailable (so you can switch away).
- Status header, output cards, and LINK all use the selected MAC. LINK posts
  `{outputNr, mac}`.
- The "Units on network" table stays (MAC labelling across all units).

## Known limitation (v1)

The history **sparkline** stays shared across units (adapter has one history buffer).
True per-unit history is a larger change, deferred. Noted in code.

## Testing

Backend unit tests: status filters by MAC; unknown MAC → not-found; `link_output`
targets the right unit's IP; sticky is per-MAC. Existing sticky/link tests updated for
the new internals (behaviour unchanged). Frontend: `npm run build` + live check against
the two real units.
