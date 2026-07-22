# Session handoff — Stardust Outputs panel (2026-07-22)

Branch `edit_export` · HEAD `806d0a1`. Read `docs/network-state.md` first for the
standing device/network facts and environment traps; this file is the delta from
today's session.

## What shipped this session

**Feature:** a per-output **Outputs** table on the Devices-page Stardust panel —
Output · Name · Source · Universe/Addr · CRMX Type · Power — sourced read-only from
the Stardust's own WebSocket control plane (`ws://<ip>/ws`), which is the *only*
place port→universe mapping and CRMX radio type exist (Art-Net reports the `32767`
"unassigned" sentinel on all ports). Plus stability + readability fixes.

Verified live against the real unit at **10.0.1.3**: 8 real outputs returned over
`/ws`; discovery hit rate 8/8 after the contention fix. Backend suite **104 passed**.

### Feature commits (`7da2c83..806d0a1`, all on `edit_export`)
- `7da2c83` design spec · `8a4c734` implementation plan
- `ec245e1` `/ws` mapping helpers + `websocket-client` dep
- `3f5a39f` `_merge_outputs` join
- `c56b197` `/ws` poll wired into `_real_status` (read-only)
- `ffefdeb` simulator outputs
- `1943076` frontend Outputs table
- `c349b8e` pin `websocket-client==1.9.0`
- `b2889d2` **remove** the patch-sheet reconciliation selector from the panel (user: "not a thing")
- `0e3ac33` stabilize panel (cache `/ws` behind 20s TTL; frontend holds last-good 30s) + readable table
- `806d0a1` share Art-Net discovery across pollers (lock + 2.5s TTL) — fixes the flapping

## Key files
- `backend/app/integrations/stardust.py` — all backend logic. Constants: `WS_TIMEOUT=2.5`,
  `OUTPUTS_TTL=20.0`, `NODES_TTL=2.5`. Read-only helpers `_ws_fetch_settings` (sends ONLY the
  three `Get*Command` frames), `_merge_outputs`, `_cached_outputs`, `_discover_nodes_cached`.
- `app/src/pages/Devices.jsx` — `StardustPanel`. Sticky last-good via `useRef` + `STARDUST_HOLD_MS`
  (30s) + `RECONNECTING…` badge; Outputs table renders when `status.outputs?.length`.
- `backend/tests/test_stardust_outputs.py` — helpers, join, `_real_status` wiring, outputs-TTL
  cache, discovery-sharing cache, sim contract.
- `docs/superpowers/specs/2026-07-22-stardust-outputs-panel-design.md` — spec (frame types,
  address decode, verbatim CRMX label table).
- `docs/superpowers/plans/2026-07-22-stardust-outputs-panel.md` — the 5-task TDD plan.
- `.superpowers/sdd/progress.md` — SDD ledger (all tasks complete, final review READY TO MERGE).

## How the data flows (so you don't re-derive it)
- **sACN** `universe_map = {sacnUniverse: [outputNrs]}` → invert to output→universe.
- **ArtNet** `universe_map = {outputNr: addrInt}`, decode `net=(v>>8)&0x7F, sub=(v>>4)&0x0F,
  uni=v&0x0F` rendered `"net/sub/uni"`. Keys may be str or int; a present-but-null address → `source='None'`.
- **timo_sink** gives `universe_nrs[]`, `output_names[]`, `output_powers_mw[]`, `rf_protocols[]`,
  `enabled_universe_nrs[]`. `N = len(universe_nrs)` keys the CRMX table (2/4/6/8; unknown N → N=8 col;
  unknown raw → verbatim). The `²` in labels is literal U+00B2. Output nr → letter 1→A…8→H.
- On the live rig most outputs read **"unassigned / — / CRMX Classic"** — that is the real device
  config (only E and G have a source: sACN universes 43 and 1), not a display gap.

## Environment traps (the ones that bit us — see network-state.md)
- Python is the **venv**: `backend/.venv/Scripts/python.exe`. The bare `python` on PATH is a
  *different* interpreter without the deps — do NOT use it to run the backend.
- Backend must run on the current code. Stale/`--no-reload` servers caused "everything looks the
  same" twice this session. Before starting: kill stray flask, then start ONE venv backend:
  ```
  powershell -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*flask run*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
  ```
  then from `backend/`: `FLASK_APP=app.py ./.venv/Scripts/python.exe -m flask run --host=127.0.0.1 --port=5000 --no-reload`
  (If you normally let the app spawn its backend, just make sure it's the venv interpreter.)
- **The backend I started in this session runs in the background of the OLD session and will die
  with it.** A new session must restart the backend (above) before the panel shows live data.
- Tests: from `backend/`: `./.venv/Scripts/python.exe -m pytest tests/ -q` → expect 104 passed.
- Frontend: Vite on :5173 proxies `/api` → :5000; HMR picks up `Devices.jsx` edits.
- Read-only stance is binding: the `/ws` path sends ONLY the three `Get*Command` frames, never a
  `Settings` frame; `require_private_host` on every WS/discovery call.

## Open items / possible next steps
1. **Option B (declined, still available):** widen the discovery listen window `POLL_TIMEOUT 1.2→2.0s`
   for extra margin. With 8/8 hit rate after the contention fix it looked unnecessary; revisit only
   if flapping returns under heavier network load.
2. **No hardware-in-the-loop check of the `/ws` field names / CRMX enum tokens** — they're transcribed
   from the GUI bundle `main.7bc0d075.chunk.js`. If any are wrong, the panel degrades silently to
   `outputs=None` (sim/tests still pass). A field engineer diffing the live `/ws` frames against the
   parser would close this.
3. **Finishing the branch:** `edit_export` is a long-lived working branch carrying **58 unrelated
   in-flight files** (Patch/Label/Effects work) plus prior features (Bolero signal quality, subnet
   filters). Do NOT merge/discard the whole branch to ship just this feature. The Stardust feature is
   fully committed on the branch; the user chose "keep as-is."
4. RF% per universe and full RDM DMX-start-address (OpRdm GET) remain v2/out of scope.

## Don't redo
- The whole Stardust feature is done, reviewed clean (final whole-branch review: READY TO MERGE),
  and live-verified. Don't re-run the SDD tasks — trust `.superpowers/sdd/progress.md` and `git log`.
- The patch-sheet reconciliation UI was intentionally removed — do not add it back.
