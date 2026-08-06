# GigaCore port-to-device map — design

- **Date:** 2026-08-06
- **Author:** Claude Code, with Anthony
- **Status:** design approved, not implemented
- **Scope:** Network tab only.
- **Related:** `2026-08-05-dmx-node-port-universes-design.md`. This is the
  switch-side counterpart, and it deliberately reuses that feature's shape —
  but the data is weaker and the honesty rules are therefore stricter.

## Problem

The rig has six Luminex units. The request was to give them the per-port
universe table just built for Swisson and ACPD nodes.

**They cannot have it.** All six are GigaCore12 Ethernet switches, not DMX
nodes:

```
sysDescr -> "GigaCore12 GigaBit Ethernet Switch"   (all six, OUI D0:69:9E)
172.16.1.5   .11   .12   .21   .45   .46
```

Their twelve ports are RJ45 network ports. No DMX leaves them, so there is no
port-to-universe mapping to read. The nearest equivalent — which sACN universes
flow out of which switch port, derivable from IGMP snooping because sACN
multicast addresses map 1:1 onto universe numbers — is also unavailable:

| Probe, 172.16.1.5 | Result |
|---|---|
| `dot1qTpGroupEgressPorts` (multicast group → port) | **0 rows** |
| IGMP snooping table `1.3.6.1.2.1.17.7.1.2.2.1.2` | **0 rows** |
| Web GUI / REST, all six | **401**, auth-locked |

What a GigaCore *can* answer is a different and still useful question: **which
device is on which port.** That is what this builds.

## Goals

1. Selecting a GigaCore in the Network tab shows a per-port table naming the
   device on each port, cross-referenced against the app's own device table.
2. Every other device's detail pane says which switch and port it sits behind.
3. A port that cannot prove direct attachment says so, rather than presenting a
   port number as a patch point.
4. Nothing this feature does can change a switch. The rig is live.

## Non-goals

- Universes per switch port. Not available — see above.
- Writing anything to a switch: no port config, no VLAN, no SNMP SET. See Safety.
- Topology discovery (LLDP/CDP neighbour graph). A different feature.
- The offline unit at `172.16.1.12`. It is handled as unreachable, not special-cased.
- LumiNode DMX nodes. Anthony has none; if any ever appear, the *other* spec's
  reader is what they need, not this one.

## What the hardware actually serves

> **Measured 2026-08-06 — `verified on actual gear`.** All figures below are
> from live SNMP v2c reads against the rig, community `public`, read-only.

Four MIB-II / BRIDGE-MIB columns, all standard:

| OID | Column | Result on 172.16.1.21 |
|---|---|---|
| `1.3.6.1.2.1.17.4.3.1.2` | `dot1dTpFdbPort` — MAC → bridge port | 82–87 rows |
| `1.3.6.1.2.1.17.1.4.1.2` | `dot1dBasePortIfIndex` — bridge port → ifIndex | 12 rows |
| `1.3.6.1.2.1.2.2.1.2` | `ifDescr` — ifIndex → name | 33 rows, `Port  1` … `Port 12` |
| `1.3.6.1.2.1.2.2.1.8` | `ifOperStatus` — link state | 33 rows |

`ifName` (`1.3.6.1.2.1.31.1.1.1.1`) returns **0 rows** on this firmware; the
port label must come from `ifDescr`, which returns bytes and contains two
spaces (`b'Port  1'`).

Joined and cross-referenced against the app's device table, CARL looks like:

```
Port  1   up    1 MAC    00:E0:4C:30:7E:FE      172.16.220.220
Port  2   up    1 MAC    Anthony's Bolero Nic   192.168.1.220
Port  3   up    1 MAC    00:E0:4C:30:7E:FC      10.220.220.220
Port  4   up    1 MAC    00:E0:4C:30:7E:FB      172.31.0.220
Port  5   up    1 MAC    Bollero Antenna #1     192.168.1.11   [bolero]
Port  6   up    1 MAC    Bollero Antenna #2     192.168.1.12   [bolero]
Port 11   up    1 MAC    (not in the device table)
Port 12   up   79 MACs   64 of them known
(no port)  down  1 MAC   Luminex (CARL) — the switch's own management MAC
```

Three things in that output are load-bearing:

- **One FDB entry has a bridge port absent from `dot1dBasePortIfIndex`.** It is
  the switch's own management MAC. It must not render as a mystery port.
- **A MAC not in the device table is normal**, not an error. Port 11 is real.
- **Port 12 is an uplink**, and 79 rows there would bury the six that matter.

### Timing

~2s per switch for all four walks. All six sequentially: **16.6s**, including a
6s timeout for `172.16.1.12`, which answers neither SNMP nor HTTP. That fits
inside the 300s discovery sweep without restructuring it.

## The honesty rule

This is the core of the design, and the reason it is not simply the Swisson
feature with different columns.

A forwarding database records **where a MAC was last seen**, not what is plugged
in where. A device appears in the FDB of *every* switch on its path. Measured:

```
Bollero Antenna #1   172.16.1.21 port  5  (1 MAC behind it)     <- direct
                     172.16.1.45 port 12  (73 MACs)
                     172.16.1.5  port  1  (74 MACs)
Bolero Antenna #3    172.16.1.45 port 12  (73 MACs behind it)   <- best available
                     172.16.1.5  port  1  (74 MACs)
Hog 172.31.0.2       172.16.1.5  port 12  (6 MACs behind it)    <- best available
```

Picking the port with the fewest MACs finds the *closest known* port. But only a
count of exactly **one** proves direct attachment. Antenna #3's best candidate
is an uplink with 73 devices behind it — it is plugged into something else
entirely, most likely the switch that is currently offline. Reporting "Antenna
#3 is on port 12" would be false.

So:

| MACs behind the port | What we may say |
|---|---|
| exactly 1 | **on CARL · Port 5** — direct attachment |
| more than 1 | **behind 172.16.1.45 · Port 12**, with 72 others — a path, not a patch point |
| device absent from every FDB | **not seen by any switch** — say nothing more |

The distinction is carried in the data, not left to prose: the reader returns
the count, and the UI chooses its wording from it. This mirrors the `code N`
convention in the sibling spec — the raw truth beats a confident guess.

**The table also ages.** FDB entries expire when a device goes quiet, so absence
is not proof of unplugging. The UI must not imply otherwise. For the same
reason the counts above are a snapshot, not constants — CARL's port 12 read 79
MACs in one probe and 74 minutes later. Any test fixture must be a captured
payload, never an assertion that a live switch still reports a given number.

## Approach

| | Approach | Verdict |
|---|---|---|
| **A** | Store port maps on the sweep; invert them on demand for the reverse lookup | **Chosen** |
| **B** | Walk SNMP live on every selection, both directions | Rejected |
| **C** | Switch-side table only, no reverse lookup | Rejected — half the value |

B is rejected because the *device-side* lookup needs the maps of **all**
switches to answer "where is this device", so a live read would walk six
switches on every device click — ~16s of latency and constant SNMP load on live
show hardware. A stores each switch's map in its own `vendor_data` on the sweep;
the reverse index is then pure computation over rows already in the database,
costing no SNMP at all. The switch-side table still re-reads live on selection
(~2s), matching the sibling feature.

### Backend — the walk helper first

`_snmp_walk_map` keys rows on the last OID arc:

```python
out[o.rsplit('.', 1)[-1]] = val
```

Correct for interface tables indexed by a single integer. **Wrong for the FDB**,
which is indexed by the six octets of the MAC — the helper discards five of
them, returning keys like `91` and `86`, which are last bytes, not devices.

A new `_snmp_walk_suffix(ip, oid)` returning the full remaining suffix is a
prerequisite. It is added alongside rather than replacing the existing helper:
`_enrich_snmp_switch` serves Netgear and Luminex today and must not change
behaviour.

### Backend — the reader

`read_switch_ports(ip) -> dict`, four read-only walks, returning:

```json
{"switchPorts": [
   {"port": 5, "name": "Port 5", "link": "up",
    "macs": ["00:19:7C:AA:BB:CC"], "deviceCount": 1}],
 "switchPortsAsOf": "2026-08-06T13:15:16.543468Z"}
```

`switchPortsAsOf` stamps the read itself. The sibling feature shipped a bug
where the staleness timestamp was the ICMP ping clock rather than the data's own
clock; that lesson is applied here from the start.

MACs whose bridge port has no `dot1dBasePortIfIndex` entry (the switch's own
management MAC) are excluded from the port list rather than assigned a port.
`{}` on any failure, so the sweep's carry-forward keeps the last good map.

### Backend — the reverse index

`find_switch_port(mac, switches)` — pure function, no I/O, given the stored maps:

1. Collect every `(switch, port, deviceCount)` whose `macs` contains the MAC.
2. Return the entry with the lowest `deviceCount`, plus that count.
3. Return `None` when no switch has seen it.

The caller decides wording from the count. Being pure and I/O-free, it is
directly unit-testable against the real captured maps.

### Backend — the two routes

- `GET /api/network/devices/<mac>/switch-ports` — live re-read of that switch,
  falling back to the stored map, returning `{switchPorts, live, asOf}`. Same
  contract shape and same fallback semantics as the sibling feature's
  `/ports` route, so the frontend pattern carries over unchanged.
- `GET /api/network/devices/<mac>/uplink` — the reverse lookup for any device,
  returning `{switchMac, switchLabel, port, deviceCount}` or `{"found": false}`.
  Pure computation over stored rows; issues no SNMP and never writes.

### Frontend

- `SwitchPortTable.jsx` on a GigaCore's detail pane: cached paint, then live
  re-read. A port with one device names it (label, IP, type) by cross-reference;
  a port with several shows the count and **the first 4 identified names**,
  then `+N more` — 4 because CARL's busiest real port has 6 and its uplink has
  79, so the cap must clearly separate "a few things behind a small switch"
  from "the uplink"; a port with none shows its link state only.
- One line on every other device's pane, worded per the honesty rule.

Both are new components. Neither touches the DMX `PortTable`, the
`UNIVERSES OUTPUTTING` chip row, or the Devices tab.

## Safety — the rig is live

Anthony's constraint, verbatim: *"if you mess with switches do not change any
ports or settings we are in a live environment."*

- **SNMP GET and WALK only. No SET, ever.** Not behind a flag, not in a helper.
- No HTTP writes to a switch. The GUI is 401 and stays untouched.
- The route is read-only toward the database, like its sibling.

This is pinned by a test asserting no SNMP set/write call appears anywhere in
the vendors module, so a future edit that adds one fails the suite rather than
reaching a switch.

**Related finding, out of scope but recorded.** `_gigacore_read` and
`_gigacore_write` (`backend/app/routes.py:1284`) POST credentials and PUT
`universe` / `protocol` / `mergeMode` to `/api/rest/v1/ports/{id}` on a
GigaCore, and `NodesPage.jsx:90` offers a config panel on that basis. The
endpoints answer 401, and a GigaCore has no universes to set. That path is
speculative and cannot work. It is **not** touched here — removing it is its own
change — but it should not be mistaken for prior art supporting a write path.

## Testing

Backend, against the captured real payloads:

- `_snmp_walk_suffix` returns full multi-arc suffixes where `_snmp_walk_map`
  returns only the last, proven on a real FDB fixture.
- The reader joins FDB → bridge port → ifIndex → name, and excludes the
  unmapped management MAC.
- A switch that does not answer yields `{}`; the stored map survives.
- `find_switch_port` picks the single-MAC port over the uplink for Antenna #1;
  returns the 73-MAC uplink *with its count* for Antenna #3; returns `None` for
  an unseen MAC.
- **Read-only:** no SNMP set call exists in the module.

Frontend: a one-MAC port names the device; a many-MAC port shows a count and
does not claim attachment; an unknown MAC renders raw; the device-side line
hedges when the count exceeds one; nothing renders for a device no switch saw.

## Open question, deliberately left open

`172.16.1.12` answers neither SNMP nor HTTP, and Bolero Antenna #3's real
attachment point is most likely one of its ports. Until it is reachable, that
antenna will correctly report only "behind 172.16.1.45 · Port 12, with 72
others". Whether that switch is powered down, on a different VLAN, or has SNMP
disabled is not yet known, and this design does not depend on the answer.
