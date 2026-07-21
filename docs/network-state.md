# Lighting Network — State & Handoff

Last updated: 2026-07-21

Field survey of the show network, and the source of the "confirmed on rig" OUI
entries in `backend/app/vendors/__init__.py`. Originally captured as loose
PowerShell scripts in `~/lighting-network`; the findings that belong in the app
have been folded into the scanner, the vendor table and the sACN listener.

## Addressing scheme

| Network | Range | Local NIC |
|---|---|---|
| HogNet (consoles) | `172.31.0.0/16` | `HOG` @ 172.31.220.220 |
| sACN (nodes) | `10.0.0.0/8` | `sACN` @ 10.220.220.220 |
| Bolero coms | `192.168.1.0/24` | `COMS` @ 192.168.1.220 |
| Management (switches) | `172.16.0.0/16` | `Management` @ 172.16.220.220 |

All four are seeded as `NetworkSubnet` rows and scanned automatically.

## Confirmed OUIs

| OUI | Device |
|---|---|
| `E4-5F-01` | Stardust (a Raspberry Pi OUI — Stardusts are Pi-based) |
| `28-36-38` | Swisson Node |
| `28-94-01` | Netgear AV Switch |
| `D0-69-9E` | Luminex |
| `00-90-A1` | Hog 4 family (mDNS `hog4.local`) |

## Inventory

**Swisson nodes (9)** — `10.31.2.93`, `10.31.8.31`, `.36`, `.78`, `.79`, `.90`, `.96`, `.97`, `.98`

**Stardust** — `10.0.5.1`.

**Hog 4** — `172.31.0.4` (server, dual-homed with `10.0.0.4`), plus `10.0.0.11`, `10.0.0.22`.

**Luminex GigaCore12 (6)** — `172.16.1.4`, `.11`, `.12`, `.21`, `.31`, `.36`

**Netgear M4250-10G2F-PoE+** — `172.16.3.97` (firmware 13.0.5.26, boot 1.0.0.11)

**Unidentified** — `172.16.2.2`, `10.0.7.2`, `10.31.0.11`, `10.31.7.102`, `192.168.1.11`

**Known non-gear** — `172.16.0.94` = Eltons Mac Pro (`E4-50-EB-BB-A9-F1`), expected on the network

A scan on 2026-07-21 classified 39 devices: 7 swisson, 6 luminex, 6 hog,
2 stardust, 1 netgear, 1 fortinet, 16 unknown. The Swisson count is short of
the 9 above — sweep coverage, not a fault (see the corrections below).

## sACN sources [VERIFIED 2026-07-21]

Read live off the wire by `backend/app/sacn_listener.py`. Source names are
self-declared, so this is positive ID, not inference.

| Universe | Sources |
|---|---|
| 1–5 | `10.0.0.4` "Processor, Netnumber 4" **and** `10.0.0.22` "Processor, Netnumber 22" |
| 6 | `10.0.0.4` only |

Netnumber matches the final IP octet. All sources run priority 100 at ~26 fps.

> **Open question — two processors contend on universes 1–5.** Both source at
> the *same* priority (100), so which one a receiver follows is arbitrary. This
> is either an intentional tracking-backup rig that should be re-prioritised so
> the intent is explicit, or a genuine misconfiguration. Not yet resolved with
> the operator. The Network Monitor flags it with ⚠.

Note the Hog processors send **no** E1.31 universe discovery packets, so
discovery-driven multicast joins alone find nothing. The listener joins
universes 1–16 unconditionally for this reason (`FIVE12_SACN_UNIVERSES`).

## Fixed

HogNet `172.31.0.0/16` had been bound to a Microsoft KM-TEST Loopback adapter — a
virtual adapter with no physical port — so every ARP for `172.31.x` went nowhere
and returned `Incomplete`. The physical HOG NIC was meanwhile on
`192.168.220.220/16`, squatting on the Bolero range. NIC corrected;
`172.31.0.4` now reachable.

## Open

1. **Two Hog consoles still not visible on `172.31.x`.** The Loopback adapter
   still holds `172.31.210.220/16` and continues to win source selection for
   HogNet. Still present as of 2026-07-21 — both `172.31.210.220` and
   `172.31.220.220` appear in the interface list. Fix (needs admin):
   `Remove-NetIPAddress -InterfaceAlias 'Loopback' -IPAddress '172.31.210.220'`
   or set `-SkipAsSource $true` plus `-InterfaceMetric 9999`.
2. **Wi-Fi `172.16.11.11/23` overlaps Management `/16`.** Venue Wi-Fi (~50 phones
   with randomized MACs) shares the range; the more specific /23 wins, routing
   `172.16.10-11.x` out the Wi-Fi via a FortiGate. Renumber Management to a /24.
   Mitigated in-app: the scanner now drops locally-administered MACs, so the
   phones no longer land in the device list.
3. **Rogue second default route** `0.0.0.0/0 -> 10.0.0.1` on the disabled
   "Local Area Connection". NordVPN also holds `10.100.0.2/22` inside the sACN `/8`.
4. **Tailscale ifMetric 5** is below the lighting NICs at 25, so it wins multicast
   egress. Has not stopped the sACN listener, which joins on every interface.
5. **All four lighting NICs are firewall profile "Public".**
6. **SNMP** v2c community `public` / `172.16.0.0` / `255.255.0.0` / ReadOnly is
   configured on the one M4250 only. Remaining Netgears still need it, and
   return `{}` from enrichment until they get it. Luminex answers by default.
   The `puresnmp` client itself is fine — pinned in `backend/requirements.txt`
   and present in `backend/.venv`, which is the interpreter `electron/main.js`
   prefers. A "puresnmp not installed" warning means the backend was started
   with the wrong interpreter (e.g. a bare `python` off PATH), not that a
   dependency is missing.
7. **`10.31.2.201` unreachable** — real fault, unresolved. NOTE: the original
   notes give this address as both `10.31.2.201` and `10.31.1.201`; the correct
   octet has not been confirmed.

## Corrections made during diagnosis — do not repeat these errors

- "Zero Swisson nodes" and "zero Netgear switches" were **sweep-coverage
  artifacts**, not faults. Absence of evidence was wrongly reported as evidence
  of absence.
- The IGMP querier theory was **wrong**. Multicast works fine; universes 1–6
  flow normally. The missing joins simply meant no listening software was
  running at the time.
- `10.31.x.201` is a **Stardust**, not a Raspberry Pi — `E4-5F-01` is the Pi
  OUI, and Stardusts are Pi-based.
- Wide sweeps (>50k addresses) time out. Sweep targeted /24s only.
- A hand-rolled SNMP packet with a miscalculated varbind length produced false
  "no SNMP reply" results across every switch. Length is `oidCount + 4`, not
  `oidCount + 6`. (The app uses `puresnmp` and never had this bug.)

## Origin scripts

Superseded by the app, kept in `~/lighting-network` for reference:

| Script | Folded into |
|---|---|
| `scan-lighting-devices.ps1` | `scanner.py` + `vendors/__init__.py` |
| `scan-sacn.ps1` | `sacn_listener.py` |
| `fix-lighting-net.ps1` | **not yet ported** — see the IPConfig health-panel work |
| `rollback-lighting-net.ps1` | **not yet ported** |
