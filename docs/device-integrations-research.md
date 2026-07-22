# Five12 — Device Integration Research & Brainstorm

**Devices:** Riedel Bolero (wireless intercom), LumenRadio Stardust (CRMX transmitter), SpaceX Starlink (satellite uplink)
**Author:** research pass for Ant, 2026-07-04
**Context:** all three are IP-networked devices you'd have on a show / set / OB network. Five12 already has a Network Monitor that discovers devices by IP/MAC and an IP-config tool — so these integrations are natural extensions: device-aware panels that pull live telemetry (and, carefully, push settings).

**Accuracy labels** (same convention as the effects spec):
- **[VERIFIED]** — stated in a manufacturer/community source; cited.
- **[INFERRED]** — follows from verified facts.
- **[NEEDS VERIFICATION]** — plausible; confirm against a real unit before building.

**One important lesson from your own codebase:** we just removed the GigaCore/Swisson node-config code because it scraped device HTML and had an SSRF hole. Two of these three integrations tempt you toward the same pattern (screen-scraping a web UI). Where a *documented protocol* exists (RDM, gRPC), use it instead of scraping — it's the difference between a feature that survives a firmware update and one that silently breaks. Start every integration **read-only**; add "push settings" only once monitoring is solid.

---

## 1. SpaceX Starlink — *highest value, highest feasibility, do this first*

### What's exposed
- **[VERIFIED]** The dish ("Dishy") runs an **unauthenticated gRPC server on `192.168.100.1:9200`** (HTTP/2) with server reflection enabled — reachable from any device on the LAN, no credentials.
- **[VERIFIED]** Telemetry available: online/offline state, `uptime_s`, `obstruction_fraction` (% of sky blocked), SNR / signal quality, throughput (down/up), stow/unstow state, and alerts.
- **[VERIFIED]** Mature community tooling exists: `sparky8512/starlink-grpc-tools` (reverse-engineered `.proto` files + Python that dumps to CSV/InfluxDB), `starlink-cli` (Go), and "Dishyworld" (Prometheus/Grafana dashboard).
- **[VERIFIED]** No *official* API — it's reverse-engineered but stable and widely used.

### Why it matters for you
On a remote set or OB truck, the Starlink uplink **is** the show — if it's degrading you want to know *before* the stream drops, not after. A panel that shows "obstruction climbing / SNR falling / 3 outages in the last hour" is genuinely valuable and nobody else in your app's niche surfaces it.

### Integration ideas
- **Monitor panel (read-only):** big online/offline status, uptime, current down/up throughput, latency, obstruction %, and a rolling outage log. Color-state like your Network Monitor (green/red).
- **Alerts:** flag when obstruction > X%, when an outage occurs, or when it goes offline — tie into a future notifications system.
- **History:** log samples to your SQLite/MySQL so you can show "connectivity over the last N hours" — the same shape as your `LocationSnapshot` model.
- **Settings (limited):** the API supports `reboot` and `stow/unstow` the dish. Push actions are riskier — gate behind a confirm, and treat as v2.

### How it'd fit your stack
Flask backend talks gRPC to the dish. Two implementation paths:
1. **`grpcio` + the community proto** compiled into the backend — clean, in-process, no subprocess. Preferred.
2. **Shell out to `starlink-grpc-tools`** (`dish_grpc_text.py status`) and parse JSON/CSV — faster to prototype, but adds a Python-subprocess dependency (you just spent effort *removing* subprocess-shelling from `routes.py`, so lean toward path 1).

A new `starlink_routes.py` blueprint exposing `GET /api/starlink/status` (and later `/history`), plus a React `StarlinkMonitor` page mirroring your `NetworkMonitor` layout. The dish's fixed IP (`192.168.100.1`) means you can even auto-detect its presence from the existing network scan and only show the panel when it's on the network.

### Feasibility: **HIGH.** Effort: **~1–2 days** for a read-only panel. Risk: low (community protos are stable). Caveat: reverse-engineered, so a Starlink firmware change *could* shift fields — pin to a known proto version and handle missing fields gracefully.

---

## 2. Riedel Bolero — *high value (battery!), medium feasibility*

### What's exposed
- **[VERIFIED]** The **Standalone** system is configured over IP **via a web browser**.
- **[VERIFIED]** It has a **REST API** — the third-party app "DECT" ("speaks the same REST API as the original interface"), which proves the API exists and is usable, and that it's the same surface the official web UI uses.
- **[VERIFIED]** **Live WebSocket updates** carry **battery, signal strength, antenna status, PTP sync, and temperature** — exactly the telemetry you'd want.
- **[VERIFIED]** The web UI shows antennas and beltpacks at a glance: **battery, signal, capacity, mic gain**; and per-beltpack config: 7 keys (function/destination/mode/volume/priority/groups) and audio (headset levels, speaker, sidetone, limiters, mic VOX, Bluetooth).
- **[VERIFIED]** Beltpack batteries are Li-Ion 3.6 V / 4.8 Ah / 17.3 Wh.
- **[NEEDS VERIFICATION]** Exact REST endpoints and WebSocket message schema — **not publicly documented**; DECT reverse-engineered them. You'd need to inspect a real unit's browser traffic (DevTools → Network/WS) to map them.

### Why it matters for you
A dead beltpack mid-take is a real on-set problem. "All packs, battery %, sorted by lowest" on the same screen as your patch/network tools is a legitimately useful crew-facing view — and the WebSocket means it's live, not polled.

### Integration ideas
- **Beltpack battery board (read-only):** roster of packs with battery bars, signal, antenna they're on, temperature; sort/alert on low battery. This is the headline feature.
- **Antenna health:** antenna status + PTP sync state (PTP loss = audio problems) surfaced like a device row in your Network Monitor.
- **Settings (careful):** rename packs, adjust per-pack volume/sidetone, reassign keys. High value to an A1/comms tech, but you're now *writing* to a live intercom system during a show — gate hard, confirm every write, and consider making config read-only in v1.

### How it'd fit your stack
Flask backend proxies the Bolero REST API and holds a server-side WebSocket client to the unit, pushing live battery/signal to your React frontend (via your own WS or SSE, or just poll the backend cache). A `bolero_routes.py` blueprint + a `BoleroMonitor` page. Because the API is undocumented, **build a thin adapter layer** so that when a firmware update moves an endpoint, you fix it in one place.

### Feasibility: **MEDIUM.** Effort: **~3–5 days** *after* you've mapped the API against a real unit (the mapping is the gating task — you can't do it from docs). Risk: medium (unofficial API, could change; writing to a live comms system is operationally sensitive). Do read-only battery/signal first; it's the 80/20.

---

## 3. LumenRadio Stardust — *medium value, medium feasibility, cleanest via RDM*

### What's exposed
- **[VERIFIED]** 8-universe DMX/RDM wireless transmitter with **Ethernet + WiFi**; **built-in web interface** for configuration, reachable from any browser (PC/tablet/phone).
- **[VERIFIED]** Transmits **sACN and Art-Net**; has a **built-in RDM controller** in the web UI.
- **[VERIFIED]** **RDM is available to third-party controllers via RDM-over-Art-Net** — this is the clean, standards-based integration path.
- **[VERIFIED]** Universe naming from the web UI; Bluetooth config via the CRMX Toolbox app.
- **[NEEDS VERIFICATION]** No documented JSON/OSC/REST API surfaced in research. So programmatic access is either (a) **RDM-over-Art-Net** (standard, clean) or (b) scraping/driving the web UI (fragile — the pattern you just deleted).

### Why it matters for you
It's a lighting device on your lighting app — natural fit. RDM-over-Art-Net also lets you reach **downstream wireless fixtures'** RDM data (addresses, modes, sensor data, even fixture battery on RDM-capable units), which ties directly into your patch/fixture inventory.

### Integration ideas
- **Transmitter status (read-only):** per-universe link/RF status, output config, named universes, RF power. Confirms "is my wireless DMX actually transmitting."
- **RDM discovery → auto-patch:** use RDM-over-Art-Net to discover downstream fixtures and their addresses/modes, and reconcile against your `PatchSheet` — "this fixture is patched at U1/45 but reports U1/50." That's a killer feature for a patch tool.
- **Settings:** universe naming, RF power, protocol/merge config — but via RDM SET or the web UI (fragile). Read/monitor first.

### How it'd fit your stack
The clean path needs an **Art-Net + RDM library** in the backend (e.g., a Python Art-Net/RDM implementation) to send/receive RDM over the network — more plumbing than Starlink's gRPC, but it's a documented standard, unlike scraping. A `rdm_routes.py` blueprint feeding an "RDM / Wireless" panel, and a reconciliation view against patch data.

### Feasibility: **MEDIUM.** Effort: **~3–4 days** for status + RDM discovery (most of it is the Art-Net/RDM plumbing, reusable for other wireless nodes). Risk: medium. **Avoid** the web-UI-scraping route for config — that's the fragile/SSRF-prone pattern you just removed.

---

## Cross-cutting: how these fit together

All three slot into a single pattern you already have the bones for: **device-aware panels layered on the Network Monitor.** Your scanner discovers devices by IP/MAC/OUI; extend it so that when it recognizes:
- `192.168.100.1` → offer the **Starlink** panel,
- a Riedel OUI / Bolero antenna hostname → offer the **Bolero** panel,
- a LumenRadio OUI / Stardust → offer the **Stardust / RDM** panel,

it surfaces a device-specific view instead of a generic host row. One consistent UX ("we found a Starlink / a Bolero / a Stardust — open its dashboard"), three adapters behind it.

Shared building blocks worth building once:
- A **telemetry-history table** (you already have `LocationSnapshot`/`NetworkDevice` patterns) so every device can log "status over time."
- A **backend adapter interface** (`get_status()`, `get_history()`, optional `apply_setting()`), one implementation per device, so the React side is uniform.
- An **alerts** primitive (threshold → flag) reused across battery %, obstruction %, PTP loss, RF link.

---

## Recommendation / build order

1. **Starlink first.** Best value-to-effort: unauthenticated gRPC, rich telemetry, community protos, fixed IP for auto-detect, essentially read-only. It also lets you build the shared "device panel + history + alerts" scaffolding against the *easiest* target, so Bolero and Stardust reuse it.
2. **Bolero second**, once you can put hands (and a browser DevTools session) on a real unit to map its REST/WebSocket surface. The battery board is the headline feature; keep it read-only at first.
3. **Stardust third**, via RDM-over-Art-Net (not web scraping). The RDM-discovery → patch-reconciliation idea is the most novel thing here and leans on your existing patch model.

**Concrete first step (Starlink, read-only):** add `grpcio` + the community Starlink proto to the backend, a `starlink_routes.py` with `GET /api/starlink/status`, and a `StarlinkMonitor` React page cloned from `NetworkMonitor`'s layout. Auto-show it when `192.168.100.1:9200` is reachable. I can scaffold that whenever you want to start.

**A caution to carry into all three:** these are all *unofficial / reverse-engineered or undocumented* control surfaces. Isolate each behind a thin adapter, handle missing/renamed fields gracefully, keep them read-only until proven, and never expose them on anything but the local production network (the same SSRF lesson from the node code we removed).

---

## Sources

- Starlink local gRPC API & tooling: [sparky8512/starlink-grpc-tools](https://github.com/sparky8512/starlink-grpc-tools), [Nelson's log — Dishy deeper status](https://nelsonslog.wordpress.com/2021/06/27/starlink-dishy-getting-some-deeper-status/), [Integrating Starlink monitoring via gRPC](https://techjunction.co/integrating-starlink-monitoring-into-your-open-source-nms-an-isps-comprehensive-guide-to-implementing-grpc-solving-the-dark-site-challenge/)
- Riedel Bolero REST API / WebSocket telemetry: [DECT — the Bolero UI, reimagined](https://dect.app), [Riedel Bolero product page](https://www.riedel.net/en/products-solutions/intercom/bolero-wireless-intercom), [Bolero user manual (PDF)](https://www.cpl.tech/wp-content/uploads/2018/11/Riedel-Bolero-User-Guide.pdf)
- LumenRadio Stardust web UI / RDM-over-Art-Net: [Stardust product page](https://lumenradio.com/products/stardust/), [Stardust manual](https://lumenradio.com/support-materials/stardust-manual/), [Stardust 1.3.1 release notes (PDF)](https://dl.lumenradio.com/firmware/crmx/stardust/1.3.1/stardust_1.3.1_release_notes.pdf)
