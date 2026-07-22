# Handoff — 2026-07-22 (session 2): Stardust flap fix, sim removal, output cards + CRMX Link

Continues from `docs/handoff-2026-07-22-stardust.md` (the Stardust Outputs feature).
Branch: **`edit_export`**. Nothing pushed. All work committed.

## What shipped this session (4 commits)

| Commit | What |
|--------|------|
| `4c912f3` | **Fix status flap.** Stardust answers ArtPoll only intermittently → ~10% of polls returned `available:false` → UI flapped RECONNECTING. Fixed backend-only: **sticky availability** (`STARDUST_STICKY_SEC`, holds last-seen unit through a missed poll, flags `stale`) + **ArtPoll retry** (`POLL_RESEND_SEC`, re-broadcasts within the existing window). Live-verified 22/22 available. |
| `113214d` | **Removed sim mode** (frontend only — the Devices "SIM MODE" toggle, defaulted on). Backend sim endpoints/tests left intact. **Parked the Console** — removed `/console` route + nav link; `Console.jsx`, engine, `LightSimulator.jsx` kept on disk with a PARKED banner. |
| `6e1642b` | **Output cards light up.** The U1–U8 grid keyed off Art-Net transmitting (never reported by a real Stardust → all grey). Now driven by `status.outputs` (A–H), lit when `enabled && source != 'None'`, showing source/universe/CRMX type. |
| `1786528` | **CRMX Link button** + prominent universe. `link_output()` = the integration's ONE hardware write. |
| `d7c2637` | **Multi-unit selector.** Multiple Stardusts on the net; select one by MAC. `get_status(mac)`/`link_output(out_nr, mac)`, sticky re-keyed per MAC (`_last_seen`), chip-row selector (hidden when ≤1 unit). Live-verified with 2 real units (`D8:3A:DD:1A:70:D1` @10.0.5.5, `E4:5F:01:AC:24:D4` @10.31.1.201). Spec: `docs/superpowers/specs/2026-07-22-stardust-multi-unit-design.md`. Known limit: history sparkline still shared across units. |

## Key facts learned (verified against the live rig at 10.0.1.3)

- **Outputs are lettered A–H by fixed number: A=1 … H=8**, independent of the device's
  `universe_nrs` order (real unit reports `[7,8,1,2,3,4,5,6]`). So "Output E" is always #5.
- Real unit's sources: **sACN univ 1 → out G(#7)**, **sACN univ 43 → out E(#5)**; no Art-Net; all CRMX (→ "CRMX Classic"). Only E and G are active.
- **LinkCommand** (captured live from the GUI `/ws`):
  - send `{"universe_nrs":[N],"_type_":"dmx_sink.timo_sink.LinkCommand"}`
  - device replies `LinkingStarted`, then `LinkingEnded` ~8s later.
- The Stardust does **not** answer ArtTodRequest and doesn't advertise SwOut over Art-Net
  (documented in stardust.py) — that's why RDM fixtures = 0 and per-universe Art-Net data is useless.

## Key files

- `backend/app/integrations/stardust.py` — sticky/retry, `_merge_outputs` (+`outputNr`), `link_output()` + `_ws_open`/`_stardust_ip`/`_await_type`. Constants: `POLL_TIMEOUT`, `POLL_RESEND_SEC`, `NODES_TTL`, `STARDUST_STICKY_SEC`, `WS_TIMEOUT`, `LINK_TIMEOUT`, `OUTPUTS_TTL`.
- `backend/app/device_routes.py` — `POST /api/devices/stardust/link`.
- `backend/tests/test_stardust_outputs.py` — 111 backend tests pass.
- `app/src/pages/Devices.jsx` — StardustPanel: output-card grid + LINK button (confirm + linking state). Sim wiring removed.
- `docs/superpowers/specs/2026-07-22-stardust-output-cards-design.md` — the design/spec.

## Next up (diagnosed, not yet built)

- **Network Monitor devices flap offline/online** (sACN/HogNet/Bolero). Root cause
  CONFIRMED: scan cycle over the huge subnets (a /8 + two /16s) exceeds the 90s offline
  threshold, so devices age out between sweeps. Full diagnosis, live evidence, fix
  options, and verify command in **`docs/handoff-2026-07-22-network-monitor-flap.md`**.
  Recommended fix: fast per-cycle re-probe of known device IPs; quick stopgap: raise the
  threshold (both scanner.py and NetworkMonitor.jsx). Gear is fine — it's a monitor
  artifact, not a real network issue.

## Open items / decisions

- **UNLINK intentionally NOT exposed** — operator's explicit call. Do not add without a new decision.
- **Universe conflict / branch:** the prior handoff noted ~58 unrelated in-flight files on this branch — still true, keep as-is. Only the files above were touched.
- Nothing pushed; committing only, per operator preference.

## Don't redo (done + verified)

- Flap fix, sim removal, Console park, output cards, Link button — all built, tested, and (except the actual live link click) verified. The live LINK click pairs real hardware — leave that to the operator.

## Environment traps (important)

- **The backend dies when the session that started it ends.** A new session must restart it
  before live data/link work:
  ```
  cd backend && ./.venv/Scripts/python.exe -m flask run --host=127.0.0.1 --port=5000 --no-reload
  ```
- The venv `python.exe` is a **launcher** that spawns a system-python worker child — seeing
  two `python.exe` for one `flask run` is NORMAL, not two competing backends.
- Art-Net UDP 6454 sockets are opened per-poll and closed immediately, so they only appear
  bound transiently.
- **Electron is installed** and `electron/main.js` launches its own Flask subprocess — if the
  desktop app is running it can race for port 5000. Not today's issue, but watch for it.

## To resume next session

1. Read this file + `docs/network-state.md`.
2. Restart the venv backend (command above), refresh `:5173`.
3. If continuing device work, the Stardust `/ws` control plane is the source of truth for outputs; add writes ONLY as deliberate, confirmed, single-frame commands (see `link_output` as the pattern).
