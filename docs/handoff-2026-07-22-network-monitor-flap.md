# Handoff — Network Monitor: devices flap offline/online (FIXED 2026-07-22)

**Status:** FIXED. Root cause was confirmed with live evidence (below), then fixed
with a per-cycle keep-alive re-probe. Branch `edit_export`. This was a **pre-existing**
issue; nothing in the earlier 2026-07-22 sessions touched the scanner.

## Resolution (2026-07-22)

Two things were found and fixed:

1. **Duplicate backend.** Two `flask run --port=5000` processes were alive at once —
   one held the port, the other lost the bind race but its scanner thread kept running
   and stomping the same DB every 30s (the exact "stale backend" trap this repo's notes
   warn about). Killed both, ran one. This alone was *aggravating* the flap (two
   scanners + CPU contention stretched the cycle); it was not the whole cause.

2. **The real fix — per-cycle keep-alive (`quick_reprobe` in `scanner.py`).** The scan
   loop is now split across two daemon threads:
   - **keep-alive** (`quick_reprobe`, every `KEEPALIVE_INTERVAL = 20s`): pings just the
     already-known device IPs and re-reads the ARP cache, bumping `last_seen` for every
     known MAC still answering. No scapy sweep, no `/24` warming, no SNMP enrichment, no
     prune — so it finishes in a couple of seconds.
   - **discovery** (`run_scan_now`, every `DISCOVERY_INTERVAL = 300s`): the original slow
     wide sweep + enrichment + prune + Art-Net, now on its own thread so its ~165s
     duration never stalls the keep-alive.

   Known gear is now refreshed every ~20s — far under the 90s `OFFLINE_THRESHOLD` — so it
   stops flapping. New-device discovery and SNMP enrichment still happen, every 5 min.
   Tests: `backend/tests/test_scanner_keepalive.py` (5 tests). Full suite 119 pass.

**Verified live (single clean backend, MySQL dev):** over-90s count went from 8+/40
(median 128s) to **1/41 (median 10s)**. The one remaining is `172.31.0.139`
"Princess Donut", genuinely absent (not answering ARP) — a correct offline reading, not
a flap. "I don't see anything on HogNet" was this same bug: the real Hog consoles
(`172.31.0.4/.11/.22`) were sitting at 93s = red/offline because HogNet is scanned first
and then waited the whole ~165s cycle before its next revisit. They now hold at ~10s.

### If the flap ever returns
- First check for **duplicate flask processes** (`Get-Process python`) — that trap recurs.
- `KEEPALIVE_INTERVAL` must stay well under `OFFLINE_THRESHOLD` (90s). If the offline
  threshold is ever lowered below ~40s, lower the keep-alive interval too.
- Genuinely-absent gear (unplugged) *should* read offline — that is not the flap.

---

## Original diagnosis (kept for reference)

## Symptom

In the app's Network Monitor, devices on sACN, HogNet, and Bolero all keep dropping
to offline and coming back. **The actual gear is fine** — operator confirmed it's only
the app's view. So this is a monitor artifact, not a real network/multicast problem.

## Root cause (confirmed, not a hypothesis)

"Online" is computed purely as `last_seen` within **90s** (frontend
`OFFLINE_THRESHOLD_MS` in `app/src/pages/NetworkMonitor.jsx`, mirroring backend
`OFFLINE_THRESHOLD = timedelta(seconds=90)` in `backend/app/scanner.py`). `last_seen`
only updates when the ARP scan re-sees a device.

The scanner (`scanner.py` `run_scan_now` → `start_scanner._loop`) sweeps **every subnet
sequentially, then `time.sleep(30)`**. So a device's **revisit interval = the whole
cycle time**. The configured subnets are huge:

```
172.31.0.0/16  Hognet
10.0.0.0/8     sACN        <-- 16 million addresses
192.168.1.0/24 Bolero
172.16.0.0/16  Management
```

A full sweep of a /8 + two /16s takes far longer than 90s, so devices routinely age past
the threshold before the scan returns → flip offline → flip back online next pass.

**Live measurement (40 devices, backend on :5000):**
- median `last_seen` age = **128s**, max 4156s
- **28 of 40 devices were >90s old at one instant** (i.e. showing offline, about to flip)
- ages sawtooth 15→57→81→93→99… — the signature of revisit interval > threshold

Reproduce/verify (before & after any fix):
```bash
curl -s http://127.0.0.1:5000/api/network/devices | python -c "
import sys,json,datetime
d=json.load(sys.stdin); now=datetime.datetime.utcnow(); ages=[]
for x in d:
    ls=x.get('lastSeen')
    if ls: ages.append((now-datetime.datetime.fromisoformat(ls.replace('Z',''))).total_seconds())
ages.sort()
print('over90:',sum(a>90 for a in ages),'of',len(ages),'median',ages[len(ages)//2])
"
```
A good fix drives "over90" for genuinely-present devices toward ~0.

## Fix options

1. **(RECOMMENDED, proper fix) Fast re-probe of known devices every cycle.**
   The scanner already aims at previously-seen IPs (`known_ips` / `_sweep_targets` in
   scanner.py ~L334-348). Split that into a **quick targeted ARP of just the known device
   IPs that runs every cycle** (fast — a few hundred exact IPs), keeping real gear's
   `last_seen` fresh, while the **slow wide discovery sweep for new devices runs less
   often** (e.g. every Nth cycle). Keeps the 90s threshold meaningful. Add a test like the
   existing `tests/test_clear_offline.py` style.

2. **(STOPGAP) Raise the offline threshold** to safely exceed the real cycle
   (~180-240s). Change BOTH `OFFLINE_THRESHOLD` (scanner.py) AND `OFFLINE_THRESHOLD_MS`
   (NetworkMonitor.jsx L31) — they must match. One small change, immediate relief, but a
   band-aid: re-breaks as the network/subnets grow.

3. **Tighten CIDRs / parallelize.** A /8 for sACN is enormous; a narrower CIDR (operator
   config) or concurrent subnet scanning (code) shrinks the cycle at the source.

Reasonable plan: ship #2 as an immediate calm-down, then do #1 as the real fix.

## Key files / constants

- `backend/app/scanner.py` — `OFFLINE_THRESHOLD` (90s), `run_scan_now` (sequential subnet
  sweep), `start_scanner._loop` (`sleep(30)`), `_arp_scan`, `known_ips` aiming (~L334-352).
- `backend/app/network_routes.py` — `GET /api/network/devices` (serializes `lastSeen`),
  `clear-offline`.
- `app/src/pages/NetworkMonitor.jsx` — `parseUtc` (naive-UTC → append 'Z', already correct),
  `isOnline` (L34), `OFFLINE_THRESHOLD_MS = 90_000` (L31), polls every 15s (L501).

## Don't

- Don't chase a timezone bug — `parseUtc` already appends 'Z' to naive UTC (prior fix,
  covered by `tests/test_timestamp_serialization.py`). That's not it.
- Don't treat it as a real network problem — operator confirmed the gear is fine.

## Environment (as every session)

Backend dies with the session that started it. Restart before measuring:
```
cd backend && ./.venv/Scripts/python.exe -m flask run --host=127.0.0.1 --port=5000 --no-reload
```
