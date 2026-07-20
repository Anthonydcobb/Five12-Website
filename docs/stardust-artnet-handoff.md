# Handoff — LumenRadio Stardust in the Network Monitor (Art-Net + sACN)

Branch: `edit_export`. Goal: Stardust shows in the devices panel as "LumenRadio
Stardust" with MAC + firmware, "universes outputting", and a link button.

All facts below were **verified against live hardware 2026-07-20**. Use
`backend/.venv` (Python 3.12, has scapy/puresnmp) for everything.

## Already done (committed to working tree, verified)
- **Luminex GigaCore** → SNMP enrichment in `backend/app/vendors/__init__.py`
  (`_enrich_luminex`), OUI `D0:69:9E` added, `puresnmp` in `requirements.txt`.
- **Swisson** → existing HTTP `/model/device` enrichment already correct; no change.
- Deleted a duplicate `backend/app/vendors/artnet.py` (the real Art-Net code
  lives in `backend/app/integrations/stardust.py` — build on THAT).
- `integrations/stardust.py` `_parse_poll_reply` now also returns `firmware`
  (VersInfo) and `estaMan` (ESTA code). ← only stardust change made so far.

## Verified device facts
| Device | IP | MAC | ESTA | Notes |
|--------|----|-----|------|-------|
| Stardust | 10.0.1.3 | E4:5F:01:AC:23:14 | 0x4C55 "LU" | OUI = Raspberry Pi (ambiguous → identify by ESTA/name, not OUI). firmware 17.70, name "Stardust" |
| Swisson XND-8 | 10.31.2.92 | 28:36:38:C0:97:27 | 0x5377 "Sw" | 8 ports, universes out [1,101,3,4,5,6] |

## The core bug + proven fix (multi-homed host)
The scanner host has several overlapping `10.0.0.0/8` interfaces. Broadcasts/
unicast from the default route do NOT reach these devices. **Only source IP
`10.220.220.220` reaches them.** The existing adapter binds `('', 0)` → finds 0
nodes. **Fix (verified): enumerate local IPv4s and ArtPoll from each interface.**
```python
def _local_ipv4s():
    ips = set()
    try:
        for *_, sa in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(sa[0])
    except socket.gaierror:
        pass
    return sorted(ips) or ['']
# bind each src to ('<src>', 6454) with SO_REUSEADDR+SO_BROADCAST, send ArtPoll
# to 255.255.255.255, collect ArtPollReply. Record which src heard each node
# ('via') so RDM TOD unicast in _real_status binds the same interface.
```

## sACN blocker (network-side, not code) — CAUSE UNCONFIRMED
sACN Universe Discovery (`239.255.250.214:5568`) never reaches the host —
ruled out firewall (python.exe allowed) and code (multicast self-test works).

**CORRECTION 2026-07-20:** an earlier draft asserted the cause was "IGMP
snooping with no querier." That was never verified, and the operator has
since confirmed **a querier is enabled and there is only one switch** — so
snooping is most likely NOT the cause. Do not act on the old claim.

Untested candidates, most likely first:
1. **Wrong NIC for the IGMP join.** The host has 7 IPv4s and only
   `10.220.220.220` reaches the lighting gear. If the listener binds
   `INADDR_ANY`, Windows picks by route metric and the membership report
   leaves the wrong adapter. This is the *same* root cause as the Art-Net
   bug fixed below, which makes it the prime suspect. Check with
   `netsh interface ip show joins`; the listener must
   `IP_ADD_MEMBERSHIP` bound explicitly to `10.220.220.220`.
2. Socket never joins the group at all (no explicit `IP_ADD_MEMBERSHIP`).
3. Firewall profile: inbound UDP 5568 blocked on the profile that VLAN is
   classified as (Public vs Private), even though python.exe is allowed.

## Tasks 1–4 — DONE 2026-07-20 (all verified against live hardware)
1. ✅ **`integrations/stardust.py`** — `_local_ipv4s()` (honours new
   `FIVE12_ARTNET_SRC` env pin), `_open_socket(src)` binding `(src, 6454)`
   with `SO_REUSEADDR`, `_discover_nodes()` polling all 7 interfaces via
   `select()` on a shared deadline, each node tagged `via`. `_real_status`
   discovers directly (not through `detect()`) so `via` survives for the TOD
   unicast. **Result: 0 nodes → 2 nodes; Stardust `via=10.220.220.220`.**
2. ✅ **Verified live — the Stardust does NOT answer ArtTodRequest.** Zero TOD
   replies on all 8 universes. It also does **not** advertise universes in
   ArtPollReply: all 8 replies are identical with `NetSwitch=127,
   SubSwitch=15, SwOut=15` → universe **32767** (`0x7FFF`, the "unassigned"
   sentinel, now filtered). **So Stardust universes really do depend on the
   sACN fix** — the old conclusion was right even though its stated cause
   above was wrong. Consequence: a TOD reply is NOT a usable "up" proxy; it
   reported "8 universes down" on a healthy unit. `universesUp/Down` now come
   only from ArtPollReply port data and are `None` (unknown, no alert) when
   the node publishes none.
3. ✅ **`scanner.py`** — `_scan_artnet()` + `_subnet_id_for_ip()`, called once
   per sweep after the prune. Upserts `device_type='stardust'`, auto-labels,
   `vendor_data` incl. `universesOutputting` + `webUrl`. Verified: Stardust
   row matched subnet `10.0.0.0/8`, labelled "Stardust".
4. ✅ **`NetworkMonitor.jsx`** — webUrl-aware link button (falls back to
   `lastIp`, so generic for Luminex/Swisson) and a UNIVERSES OUTPUTTING chip
   row with an honest empty state for Stardust. `npm run build` passes.

### Bonus fix found while verifying (port merge)
Multi-port nodes send **one ArtPollReply per port group, all sharing one
MAC** — the Swisson sends 8. Dedupe-by-MAC alone silently discarded 7 of its
universes. `_discover_nodes` now dedupes *identity* by MAC while *merging*
ports. `_parse_poll_reply` returns `ports[{universe, transmitting}]` decoded
from `GoodOutput` bit7 and per-reply `NetSwitch/SubSwitch/SwOut`.
**Verified:** Swisson → `[1, 3, 4, 5, 6, 101]`, an exact match for the
independently-confirmed table above. Universe 101 only decodes correctly
because SubSwitch is read *per reply* (port 2 has `SubSwitch=6`).

## What's actually left
- **The sACN listener** (the only path to Stardust universes). Build it
  binding `IP_ADD_MEMBERSHIP` explicitly to each local interface — do not
  trust `INADDR_ANY`; see the corrected blocker section above.
- RDM `DMX_START_ADDRESS` via full RDM GET (OpRdm 0x8300) — still v2.

## Art-Net ArtPollReply offsets (0x2100), for reference
MAC @201; VersInfoH/L @16/17; EstaManLo/Hi @24/25; ShortName @26–44;
LongName @44–108; NumPortsHi/Lo @172/173; GoodOutput @182–186 (bit7 = data
transmitted); SwOut @190–194; NetSwitch @18, SubSwitch @19. Universe =
(Net<<8)|(Sub<<4)|(SwOut&0x0F).
