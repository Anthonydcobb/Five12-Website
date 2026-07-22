# Stardust Outputs panel — design (2026-07-22)

Branch `edit_export`. Add a per-output **Outputs** table to the Devices-page
Stardust panel showing, for each CRMX output A–H: the source protocol and
universe/address feeding it, the CRMX radio type, output power, name, and
enabled state.

## Problem

The Stardust panel today shows universes U1–U8 (transmitting dot, RF%, RDM
fixtures), all sourced over the standards path (Art-Net `ArtPoll`/`ArtPollReply`
+ RDM-over-Art-Net TOD in `backend/app/integrations/stardust.py`). Two things
the operator asked for are **not** available over that path and never will be:

- **Which universe each output transmits** — a real Stardust reports the
  Art-Net "unassigned" sentinel (`32767`) on all 8 `ArtPollReply` ports
  (verified, see `stardust.py` `UNIVERSE_UNASSIGNED`), so port→universe mapping
  is absent from Art-Net.
- **CRMX radio type** (CRMX Classic / CRMX² / W-DMX) — LumenRadio-proprietary
  radio config, not in any DMX standard.

Both live only in the Stardust's own control plane.

## Data source (verified from the GUI bundle, 2026-07-22)

The LumenRadio web GUI (`http://<ip>/app/...`, backend `uvicorn`/Python) is a
React SPA driven **entirely by a WebSocket** at `ws://<ip>/ws`. Frames are JSON
objects tagged with a `_type_` field; the client sends `*.GetSettingsCommand`
and receives `*.GetSettingsResponse` / `*.SettingsChanged`. Mapped from
`main.7bc0d075.chunk.js` in the captured HAR.

This is a clean machine API (like Bolero's REST), **not** HTML scraping — it is
the acceptable integration surface. It is, however, the device's live control
plane: the same socket accepts `*.Settings` frames that reconfigure the unit
mid-show. **We send only `Get*Command` frames and never a `Settings` frame.**

### Frames we send (all read-only)

- `{"_type_":"dmx_sink.timo_sink.GetSettingsCommand"}`
- `{"_type_":"dmx_source.sacn_source.GetSettingsCommand"}`
- `{"_type_":"dmx_source.artnet_source.GetSettingsCommand"}`

### Responses we parse

`dmx_sink.timo_sink.GetSettingsResponse` → `.settings`, parallel arrays indexed
by the same `i`:

- `universe_nrs[i]` — the output/universe number (1-based) for slot `i`
- `output_names[i]` — user name for that output
- `output_powers_mw[i]` — TX power in mW
- `rf_protocols[i]` — raw CRMX enum (see mapping below)
- `enabled_universe_nrs[]` / `disabled_universe_nrs[]` — which outputs are on

`dmx_source.sacn_source.GetSettingsResponse` → `.settings.universe_map` =
`{ sacnUniverse: [outputNr, ...] }` (one sACN universe can feed several outputs).

`dmx_source.artnet_source.GetSettingsResponse` → `.settings.universe_map` =
`{ outputNr: artnetAddrInt }`. Decode the int exactly as the GUI does:
`net = (v >> 8) & 0x7F`, `sub = (v >> 4) & 0x0F`, `uni = v & 0x0F`, rendered
`"net/sub/uni"`.

Output number → letter: `1→A, 2→B, … 8→H`.

### CRMX type label (exact, from the bundle's `It` table)

The label depends on `N`, the device's output count (2/4/6/8). CRMX² can be
split across outputs, so the same raw value renders differently by `N`:

| raw `rf_protocols[i]` | N=2 | N=4 | N=6 | N=8 |
|---|---|---|---|---|
| `CRMX` | CRMX Classic | CRMX Classic | CRMX Classic | CRMX Classic |
| `CRMX2_1_4` | CRMX² | 1/2 CRMX² | 1/3 CRMX² | 1/4 CRMX² |
| `CRMX2_2_4` | — | CRMX² | 2/3 CRMX² | 2/4 CRMX² |
| `CRMX2_3_4` | — | — | CRMX² | 3/4 CRMX² |
| `CRMX2` | — | — | — | CRMX² |
| `WDMX_G3` | W-DMX G3 | W-DMX G3 | W-DMX G3 | W-DMX G3 |
| `WDMX_G4S` | W-DMX G4S | W-DMX G4S | W-DMX G4S | W-DMX G4S |

`N` = `len(universe_nrs)`. If `N` is not in {2,4,6,8}, or a raw value is
unrecognized, fall back to the N=8 column / the raw value verbatim so the panel
degrades to "show what we got" rather than erroring.

## Architecture

Keep the existing Art-Net/RDM path (`detect`, `discover_units`, `_real_status`,
`reconcile`) exactly as-is — it owns discovery, MAC-persistent labels, and RDM
fixtures. Add a **complementary WebSocket poll** for the outputs config.

### Backend — `backend/app/integrations/stardust.py`

New pieces, each small and independently testable:

1. **`OUTPUT_LETTERS` / `_output_letter(n)`** — `1→A … 8→H`, `" "` otherwise
   (mirrors the GUI's `toOutputLetter`).
2. **`CRMX_LABELS` (the table above) + `_crmx_label(raw, n)`** — pure mapping,
   no I/O.
3. **`_artnet_addr(v)`** — int → `"net/sub/uni"`, pure.
4. **`_merge_outputs(timo, sacn, artnet)`** — pure join of the three parsed
   `.settings` dicts into a list of dicts:
   `{output, name, source, universe, crmxType, powerMw, enabled}` where
   `source ∈ {"sACN","ArtNet","None"}` and `universe` is the sACN universe
   number, the ArtNet `net/sub/uni`, or `None`. This is the unit under test.
5. **`_ws_fetch_settings(ip)`** — the only I/O: `require_private_host(ip)`, open
   `ws://ip/ws` via `websocket-client` with a short timeout, send the three Get
   frames, read frames until all three responses arrive (or timeout), return the
   three `.settings` dicts. Read-only; closes the socket in a `finally`.
6. Wire into `_real_status`: after the existing Art-Net status is built, resolve
   the WS target (`node['ip']` from discovery, else `FIVE12_STARDUST_HOST`), try
   `_ws_fetch_settings` + `_merge_outputs`, and attach `status['outputs']`. On
   any WS failure, log and set `status['outputs'] = None` — the panel keeps
   working from Art-Net data alone (no regression).

The status contract gains one key: `outputs` (list or `None`). Nothing existing
changes.

### Backend — simulator (`_sim_status`)

Add a plausible `outputs` list to the sim so `?sim=1` renders the new table:
a mix of sACN and ArtNet sources across A–H, a couple of CRMX² split outputs,
one W-DMX output, and one disabled output — built through the same
`_output_letter` / `_crmx_label` / `_artnet_addr` helpers so sim and real agree.

### Frontend — `app/src/pages/Devices.jsx` `StardustPanel`

Add an **Outputs** section (only when `status.outputs?.length`) above or beside
the existing universe grid: a compact mono table with columns
**Output · Name · Source · Universe/Addr · CRMX Type · Power**. Disabled outputs
render at reduced opacity (matching the existing `opacity-50` pattern). Uses only
theme tokens already in the file. Small presentational bits (e.g. a source
badge) follow the existing `Dot`/badge idioms.

### Dependency

Add `websocket-client` to `backend/requirements.txt` and install into
`backend/.venv`. Small, standard, synchronous — fits the polling adapter with no
async plumbing.

## Error handling

- WS host is re-validated with `require_private_host` on every call; never
  derived from request input.
- Connect/read timeout is short (≈2–3s) so a missing or busy device can't hang
  the status poll; on timeout we return whatever responses arrived and
  `_merge_outputs` fills the rest as `None`.
- Any exception in the WS path is caught, logged, and yields
  `status['outputs'] = None`. The Art-Net-sourced panel is unaffected.
- We send **zero** mutating frames. A code review / test asserts the only frames
  emitted are the three `Get*Command`s.

## Testing

Extend `backend/tests/` (new `test_stardust_outputs.py` or additions to an
existing stardust test) over the **pure** functions with trimmed real payloads:

- `_output_letter` for 1–8 and out-of-range.
- `_artnet_addr` for known ints (e.g. the GUI's `k()` results).
- `_crmx_label` across the full enum for N=2/4/6/8 plus unknown-N / unknown-raw
  fallbacks.
- `_merge_outputs` join: sACN-fed output, ArtNet-fed output (address decoded),
  an output in neither map (`source="None"`), and disabled outputs — asserting
  the exact per-output dicts.
- Sim contract: `BoleroAdapter`-style test that `?sim=1` exposes `outputs` with
  all six fields on each entry.

`_ws_fetch_settings` (the I/O) is exercised by stubbing it in a status-level test
(as the Bolero tests stub `_fetch_json`), so the suite needs no live device.

Verify with `& .venv\Scripts\python.exe -m pytest tests/ -q`. Frontend has no
suite; the new table mirrors existing `StardustPanel` patterns and theme tokens.

## Environment

Per `docs/network-state.md`: Python is `backend/.venv/Scripts/python.exe`; kill
stray python before starting the backend; the app spawns its own backend so no
model/migration changes here (this is read-only, no DB). Live-verify against the
real unit at `10.0.1.3` after implementation, then confirm the panel fills in on
its poll.

## Out of scope (YAGNI)

- No writes / no `Settings` frames — read-only, same stance as Bolero v1.
- No live WS push subscription (`SettingsChanged` streaming) — we poll like the
  rest of the panel.
- No RF spectrum, blocked-channels, WiFi/Ethernet, or RDM-controller data from
  the WS — only the outputs config the operator asked for.
