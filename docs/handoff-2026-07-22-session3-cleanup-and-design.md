# Handoff — 2026-07-22 (session 3): flap fix, WIP cleanup, design restore

**Status:** DONE and pushed. `main` (GitHub default) = this work. Working tree clean.
Read this + `docs/network-state.md` + `docs/handoff-2026-07-22-network-monitor-flap.md`
to resume.

## What shipped this session

1. **Network Monitor device flapping — FIXED** (`d48004a`). Devices on every subnet
   flapped offline/online because `last_seen` refreshed only once per full discovery
   sweep (~165s measured), past the 90s `OFFLINE_THRESHOLD`. Split the scanner into two
   daemon threads: a cheap **keep-alive** (`quick_reprobe`, every 20s: ping known device
   IPs + read ARP cache, no sweep/SNMP) and the slow **discovery** sweep (`run_scan_now`,
   every 300s). Covered by `backend/tests/test_scanner_keepalive.py`. Verified: over-90s
   count 8+/40 → 1/41 (median 128s → 10s). Also killed a duplicate flask backend that was
   aggravating it.

2. **Stardust `10.0.5.1` unreachable — diagnosed** (not a code change). One-way
   reachability: ARP resolved but no ICMP/TCP/Art-Net reply, while another host reached it.
   Root cause: the unit had a **wrong subnet mask** (a `/24` with no gateway) so it couldn't
   reply to this host at `10.220.220.220`. On a flat router-less net every device needs the
   wide mask (sACN = `/8`, `255.0.0.0`) and **no gateway**. Operator fixed it on the unit.

3. **Cleared 2.5 weeks of uncommitted July WIP.** `docs/handoff` had claimed "everything's
   committed" — it was not. Reverted the working tree to committed `HEAD` and dropped the
   **RF Scanner**, the **effects engine**, the stale **backend rewrite** (`routes.py` etc.),
   and the stale **patch-sheet UI** overhaul, per operator decision. Gitignored `app/dist/`,
   `code-review/`, `.superpowers/` (`dc51943`).

4. **Fixed 3 latent bugs the revert exposed — the committed code was NOT self-contained:**
   - `config.py` never defined `ENABLE_NETWORK_TOOLS`, which `__init__.py` gates the entire
     network stack (scanner, sACN, `/api/network/*`) on → a clean checkout ran with the
     Network Monitor silently disabled. Now defined: **on by default in dev** (env
     `FIVE12_NETWORK_TOOLS=0` disables), **always on for desktop** (`be6cb24`).
   - `__init__.py` imported the deleted `network_tools.py` (RF backend). Decoupled (`be6cb24`).
   - `App.jsx` imported the never-committed `RFScanner.jsx` → the whole React app failed to
     mount (blank page). Removed the import/route/nav link (`2ba15d5`).

5. **Design system restored** (`b41fe05`). The revert had reduced `global.css` to a bare
   `@import "tailwindcss"`, dropping the `@theme` block the entire UI is built on (329
   token usages across 26 files → nothing). Rebuilt from `Five12 Logic Design System.pdf`,
   scheme **"1b Spotlight Stage"**: full oklch token set (surfaces, brand red, cyan/gel,
   green/online, amber/warn — dual names match the components' classes), Barlow Condensed /
   IBM Plex Sans / IBM Plex Mono, a dark theatrical base with a red spotlight wash, and
   `glow-*` utilities. Verified live.

## Environment — read before touching anything

- **Backend** (dev, MySQL): `cd backend; $env:FLASK_APP='app.py';
  .\.venv\Scripts\python.exe -m flask run --host=127.0.0.1 --port=5000 --no-reload`.
  Network tools are **on by default in dev now**. The venv python is a redirector — see
  `docs/network-state.md` for why process paths lie.
- **Frontend**: `cd app; npm run dev` → Vite on `:5173`.
- **The repo lives in OneDrive** — OneDrive sync and git can interfere; be aware.
- **Vite goes stale after a git branch switch.** If the UI renders content but is white /
  unstyled after a `checkout`/`merge`, the CSS module graph got thrashed: kill the vite
  node process, `rm -rf app/node_modules/.vite`, restart `npm run dev`. (Happened this
  session after fast-forwarding `main`.) The committed CSS was fine — only the dev server
  was stale.
- **Kill stale flask/vite before restarting** — multiple backends silently corrupt data
  (documented in `network-state.md`).
- **Tests**: `backend\.venv\Scripts\python.exe -m pytest tests/ -q` → 119 pass.

## Known follow-ups (NOT done)

- **Fonts come from the Google Fonts CDN** (`@import` in `global.css`). The **offline
  desktop build won't load them** — self-host Barlow Condensed / IBM Plex for desktop.
- **`NetworkMonitor.jsx` uses raw `monospace`**, not the design's `font-mono` / IBM Plex
  Mono. Point it at `font-mono` for the polished look.
- **Devices tab** briefly showed "backend unreachable / package 'stardust'" — confirm it's
  transient, not a real Stardust-panel regression (`device_routes.py` was untouched).
- **Stale local `master` branch** — orphan at `9ff7be0`, never on the remote. Safe to
  delete; the remote default is `main`.
- **`Console.jsx` + effect components** still import the deleted `src/engine/`. They're
  parked (not routed/loaded), so harmless until someone un-parks them.
- **Management sweep is still ~78s** (SNMP retries on 5 unconfigured Netgears) — configure
  SNMP or make enrichment non-blocking to shrink the discovery cycle.
- **HogNet Loopback adapter** (`172.31.210.220`) still squats on `172.31.x` — needs admin
  `Remove-NetIPAddress`.

## Branches

`main` (GitHub default; this work) · `edit_export` (working branch, at `b41fe05`) ·
`edit_patch` · `master` (stale local orphan — ignore/delete).
