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

## sACN blocker — SOLVED 2026-07-20. It was the bind, not the network.
**sACN multicast reaches this host fine.** Verified live: joined
`239.255.250.214` + `239.255.0.1–8` on interface `10.220.220.220` and
received within seconds:
```
RX from 10.0.0.2  len=638  acn='ASC-E1.17'  universe=1
source='Processor, Netnumber 2, Output 1'
```

**Root cause: the Windows multicast bind.** You must `bind(('', 5568))`
(INADDR_ANY) and choose the interface via the `IP_ADD_MEMBERSHIP` mreq:
```python
s.bind(('', 5568))                                  # NOT (IFACE, 5568)
mreq = socket.inet_aton(group) + socket.inet_aton('10.220.220.220')
s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
```
Binding the interface's *unicast* IP — the intuitive thing, and what the
Art-Net unicast path correctly does — silently receives **zero** multicast
on Windows. That is why every earlier attempt saw nothing.

**Two earlier diagnoses in this doc were both WRONG. Do not act on either:**
- ~~"IGMP snooping with no querier"~~ — a querier is enabled on the single
  switch. **No switch change is needed. Nothing to do on the network.**
- ~~"wrong NIC for the IGMP join"~~ — disproved: `netsh interface ip show
  joins` shows `239.255.250.214` joined on `Ethernet 2` (ifIndex 5), which
  *is* `10.220.220.220`. The join was always on the correct adapter.

Host topology notes (verified): `Ethernet 4` is `10.220.220.221`, a second
NIC on the same subnet as `Ethernet 2`; the default route is `Local Area
Connection` (`10.0.0.1`), neither of them. NordVPN/NordLynx is active. None
of this blocked sACN, but it is why interface selection must always be
explicit rather than left to the routing table.

## OPEN SCOPE QUESTION — read before building the listener
The Stardust is a **receiver**: it consumes sACN/Art-Net and re-transmits
DMX wirelessly over CRMX. In sACN, **sources announce themselves; receivers
do not.** So a listener yields "which universes are live on the wire, and
who sources them" (above: universe 1 from a processor at `10.0.0.2`) — it
does **not** reveal which universes the Stardust is patched to consume.

That is the number the devices panel was specced to show, so the original
goal may not be reachable from sACN either. Decide the scope before
designing: either redefine the panel section as *network* universes (a
genuinely useful "what's on the wire" view), or find another surface for
Stardust's patch config. Do not assume the listener answers the original
question.

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
