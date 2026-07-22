# Stardust output cards — light up active outputs

**Date:** 2026-07-22
**Status:** approved, display-only scope

## Problem

On the Devices → Stardust panel, the 8 "U1–U8" cards are always greyed out. They
render from `status.universes[].transmitting`, which is derived from Art-Net port
data — and a real Stardust does not advertise per-universe port/SwOut state over
Art-Net (documented `[VERIFIED 2026-07-20]` behaviour). So `transmitting` is
`None` for all 8 and every card dims, even when outputs are actively sourcing DMX.

## Key data (captured from a live unit, 2026-07-22 via ws://10.0.1.3/ws)

```
timo_sink.Info: universe_nrs = [7, 8, 1, 2, 3, 4, 5, 6]   # outputs are NOT 1..8 in order
sacn_source:    universe_map = {"1": [7], "43": [5]}       # sACN univ 1 -> out G(#7); univ 43 -> out E(#5)
artnet_source:  universe_map = {}                          # no Art-Net sources
rf_protocols:   all "CRMX"                                 # -> "CRMX Classic"
```

The meaningful per-output truth lives in the `/ws` outputs config, which the
backend already merges into `status.outputs`. Each entry is:
`{output (letter A–H), name, source ('sACN'|'ArtNet'|'None'), universe (str|null),
crmxType, powerMw, enabled}`, sorted by output letter. The existing Outputs
*table* already renders this correctly — so no backend change is needed.

## Design (frontend only)

Replace the `status.universes`-driven U1–U8 grid in
`app/src/pages/Devices.jsx` (StardustPanel) with an **A–H outputs grid** driven by
`status.outputs`:

- One card per output (all 8, sorted A–H, matching the GUI's "Output A/B/…").
- **Active** = `enabled && source !== 'None'`. Active cards render un-greyed;
  inactive/unassigned cards stay dimmed (as the GUI itself greys them).
- Active card shows: **Out {letter}**, optional **name**, and a detail line
  **{source} {universe} · {crmxType}** (e.g. `sACN 43 · CRMX Classic`).
- Inactive card shows **Out {letter}** + `unassigned`.
- If `status.outputs` is empty/unavailable (a failed `/ws` fetch), show a single
  muted line `outputs config unavailable (/ws)` instead of an empty grid.

Everything else on the panel (units table, the detailed Outputs table, RDM
discovery table, footer) is unchanged. The backend stays fully read-only.

## Follow-up: LINK button — BUILT 2026-07-22 (commit 1786528)

The LINK button was added after this display work. The `/ws` LinkCommand frame was
captured live from the GUI:

```
sent:     {"universe_nrs":[5],"_type_":"dmx_sink.timo_sink.LinkCommand"}   # output E = #5
received: {"universe_nrs":[5],"_type_":"dmx_sink.timo_sink.LinkingStarted"}
received: {"universe_nrs":[5],"_type_":"dmx_sink.timo_sink.LinkingEnded"}   # ~8s later
```

Implemented as `StardustAdapter.link_output(out_nr)` + `POST /api/devices/stardust/link`,
with a confirm dialog and "linking…" state on active output cards. `outputNr` is fixed
(A=1..H=8, independent of `universe_nrs` order).

**UNLINK is intentionally NOT exposed** — the operator explicitly did not want unlink
reachable from this app. Do not add it without a new decision.

## Testing

No frontend test harness exists in this repo (only backend pytest + engine mjs
tests). Verify via `npm run build` (compile) and a live check against the running
backend that active outputs (E, G) render lit with their universes and the other
six stay dimmed.
