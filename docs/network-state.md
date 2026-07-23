# Lighting Network — State & Handoff

Last updated: 2026-07-23

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

**Hog 4 family** [NAMED 2026-07-23] — each unit is dual-homed (HogNet 172.31.0.x +
sACN/FixtureNet 10.0.0.x, consecutive MACs per chassis):

| Name | HogNet | sACN | HogNet MAC |
|---|---|---|---|
| Princess Donut (console) | `172.31.0.139` | `10.0.0.139` | `00:90:A1:30:12:96` |
| Hobbs | `172.31.0.22` | `10.0.0.22` | `00:90:A1:26:12:71` |
| Calvin | `172.31.0.11` | `10.0.0.11` | `00:90:A1:26:09:75` |
| Hog FL HPU #4 | `172.31.0.4` | `10.0.0.4` | `00:90:A1:24:00:97` |

Shows run on port **6612** on this rig (not the 6600 default).

**Stardust units** [LABELED 2026-07-23] — 4 known, MAC-persistent labels in the app:
MAIN Unit Backup `E4:5F:01:AB:9F:65` (10.0.5.2), MAIN UNIT PRIMARY `…89:B3:00`
(10.0.5.1), FMB #6 `…AC:24:D4` (10.31.1.201), FMB #5 `…AC:23:14` (10.0.1.3).
The Devices panel lists live ArtPoll responders only; units powered off don't
appear (verified 3 of 4 genuinely absent overnight 7/22→7/23, not an app fault).

**Luminex GigaCore12 (6)** — `172.16.1.4`, `.11`, `.12`, `.21`, `.31`, `.36`

**Netgear M4250-10G2F-PoE+ (7)** — `172.16.3.78`, `.79`, `.90`, `.93`, `.96`,
`.97`, `.98`. All seven share OUI `28:94:01` and are typed automatically.
Firmware 13.0.5.26 / boot 1.0.0.11, 12 ports each. Serials read over SNMP where
configured: `.97` = `70VG5C5GA0121`, `.98` = `70VG5C5NA0143`.

**Unidentified** — `172.16.2.2`, `10.0.7.2`, `10.31.0.11`, `10.31.7.102`

**Bolero antennas** — `192.168.1.11` = MBS LM 2 (local), `192.168.1.12` = MBS LM 1.
See "Bolero comms" below.

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

## Bolero comms (`192.168.1.0/24`) [VERIFIED 2026-07-22]

Read-only beltpack/antenna telemetry, shown in the Devices page `Bolero` panel.
Backend `backend/app/integrations/bolero.py` polls; it never writes to a live
comms system. Two antennas (Riedel calls them nodes / "MBS LM"): `192.168.1.11`
= MBS LM 2 (local, the address the GUI and API are reached on), `192.168.1.12`
= MBS LM 1.

### REST API (mapped from the real unit, HAR capture)

Base `http://192.168.1.11/rest/…`, plain HTTP. Auth is HTTP Basic with the
factory READ-ONLY account the GUI itself uses (`user`/`userPass`); override via
`FIVE12_BOLERO_USER`/`FIVE12_BOLERO_PASS`. No login flow.

- `GET /rest/nodeStatus` — antennas + **live per-pack battery**. Each node's
  `bp[]` are the packs currently attached to that antenna; each carries
  `battery{status(=charge %), currentCharge(mAh), usbPower, batteryTemperature,
  batteryHealth, maxCharge}`, `signalLevel` (see below), `timeslots{free,usable,
  interfered,warning}`, and the node has `ptpStatus{lockState}` (synced when
  `==2`).
- `GET /rest/nodeConfig` — `nodeId → name` (MBS LM 2 = .11, MBS LM 1 = .12).
- `GET /rest/bp` — DECT `id → bpConfig.bpName` (crew names). ~98 KB, so cached
  300 s; the small live status polls every cycle.
- `ws://192.168.1.11/wsapp` exists for live push — out of scope (we poll).

**Config (not committed** — `backend/.env` is gitignored): `FIVE12_BOLERO_HOST=
192.168.1.11`. Without it the panel says "FIVE12_BOLERO_HOST not configured"
rather than guessing, so any fresh checkout / other machine needs this line
re-added.

### Panel columns

Pack · Battery (live charge) · **Signal** (0–4 bars + word) · Health % (battery
state-of-health, NOT signal) · Antenna · Temp · State (⚡ when charging). Sorted
lowest-battery first. `?sim=1` is the simulator fallback.

### Signal quality [VERIFIED 2026-07-22 against the GUI bundle]

`signalLevel` in `/rest/nodeStatus` is **not** a 0/1 scale (an earlier note
guessed that) — it is Riedel's `BP_SIGNAL_LEVELS` enum, read straight from their
app bundle `http://192.168.1.11/scripts/app-028c6fe2a3.js`
(`getSignalIconClass` / `getSignalTooltip`). The GUI maps it directly to bars +
a word and does **not** consult `timeslots`:

| `signalLevel` | Bars | Word |
|---|---|---|
| 0 | 4 | Excellent |
| 1 | 3 | Good |
| 2 | 2 | Medium |
| 3 | 1 | Bad |
| 0xFF / missing | 0 | Not Connected |

`bolero.py` reproduces this exactly (`_signal_quality`), emitting `signalQuality`
(0–4) + `signalLabel` per pack. On the live rig all packs sit at level 0 →
"Excellent". Verified end-to-end 2026-07-22 (commit `9ae789e`, 8 packs on MBS LM 2).

## Fixed

**HogPC couldn't join shows — flash-and-return on Connect** (fixed 2026-07-23).
Four stacked faults, unpicked in order: (1) the KM-TEST Loopback still held
`172.31.210.220/16` (open item 1) — REMOVED via `Remove-NetIPAddress`; (2)
Princess Donut's HogNet mask was `255.255.255.0` — corrected to `/16` at the
console (same fault class as the 7/22 Stardust); (3) HogPC's FixtureNet was
bound to the *Bluetooth* adapter GUID (blank FN IP on the start screen) —
repointed to the sACN NIC in Hog Control Panel; (4) **the killer**: Hog's data
dir `Documents\ETC\HogPC` is OneDrive-redirected (Known Folder Move), and the
pulled show cache (`Shows\<show>\blackbox`) got poisoned under sync — Hog's
desktop component crashed reopening it on every Connect (an earlier 786 MB
`desktop-Win32-golden.exe.dmp` shows prior history). Fix: clear the cached
show so Connect pulls a fresh copy. Verified: two successful joins.
**DO NOT junction `Documents\ETC\HogPC` on this machine** — tried 2026-07-23;
this OneDrive build FOLLOWS junctions and entered a recursive sync loop
(nested `_stale\…-onedrive-tree` copies until path-too-long), renamed the
junction aside and won. Final state: `Documents\ETC\HogPC` is a plain real
folder (cache lives in OneDrive; accepted), archives/stashes live in
`C:\Hog4PC\_stale\`. **Standing remedy when a Connect flashes again:** quit
Hog, delete `Documents\ETC\HogPC\Shows\<show>`, reconnect fresh (5 seconds).
Durable alternative if it keeps biting: turn off OneDrive's Documents backup
(KFM) — operator's call. NOTE: HogPC's own
process names don't contain "Hog" — the launcher is `launcher-win32-golden`,
desktop is `desktop-Win32-golden`, install lives under
`C:\Program Files (x86)\ETC\HogPC`, settings in `%APPDATA%\ETC\Persistent`.

**backend/.env was never actually loading — python-dotenv missing** (fixed
2026-07-23, commit `5468b6e`). Flask's CLI only auto-loads `.env` when
python-dotenv is installed; it never was, so `FIVE12_BOLERO_HOST` (and DB_*)
only reached the app when the launching shell happened to export them. A
backend restart in a clean shell silently broke the Bolero panel. Now declared
in requirements.txt; `.env` loads on every `flask run`.

**Second occurrence of the wrong-interpreter trap** (2026-07-23): a backend
started with PATH `python` lacked `websocket-client`, so the Stardust outputs
`/ws` fetch failed silently (`outputs: null`, panel said "outputs config
unavailable"). Same class as the 7/21 puresnmp false alarm — always launch with
`backend/.venv/Scripts/python.exe`; verify by behaviour, not process paths.

**Devices flapped offline/online — revisit interval exceeded the offline threshold**
(fixed 2026-07-22). "Online" is `last_seen` within `OFFLINE_THRESHOLD` (90s), but the
wide discovery sweep refreshed a device's `last_seen` only once per full pass — measured
**~165s** on the rig (HogNet 13s + sACN 40s + Bolero 4s + Management 78s of SNMP retries
+ 30s sleep). So every device sawtoothed across the 90s line and flipped offline/online,
worst on HogNet (scanned first, then waited the whole cycle). Two duplicate `flask
run --port=5000` backends were also running, both scanning the same DB, aggravating it.
Fix: split the scan into two daemon threads — a cheap **keep-alive** (`quick_reprobe`,
every 20s: ping known device IPs + read the ARP cache, bump `last_seen`, no sweep/SNMP)
and the slow **discovery** sweep (`run_scan_now`, every 300s). Known gear now refreshes
every ~20s, well under the threshold. [VERIFIED 2026-07-22] over-90s count 8+/40
(median 128s) → 1/41 (median 10s); the lone holdout was a genuinely-absent unit. Covered
by `backend/tests/test_scanner_keepalive.py`. As a bonus this also cut scanner CPU
sharply — the old loop scanned ~85% of the time; discovery now runs 165s out of every
300s at most, and only one thread does the heavy work.

**Every device read permanently ONLINE — timezone bug** (fixed 2026-07-22, commit
`464b9b6`). `to_dict()` emitted a bare `.isoformat()` on naive-UTC datetimes with
no `Z`/offset; per the ECMAScript spec an offset-less string parses as LOCAL
time, so the browser placed every timestamp 4h in the future (UTC-4), made
elapsed time negative, and `negative < 90_000` is always true — nothing could
ever go offline. Fixed at the source with `_utc_iso()` in `models.py` (trailing
`Z`) plus a `parseUtc()` guard in `NetworkMonitor.jsx`. This had also silently
disabled the "remove offline" button, whose count uses the same predicate.

HogNet `172.31.0.0/16` had been bound to a Microsoft KM-TEST Loopback adapter — a
virtual adapter with no physical port — so every ARP for `172.31.x` went nowhere
and returned `Incomplete`. The physical HOG NIC was meanwhile on
`192.168.220.220/16`, squatting on the Bolero range. NIC corrected;
`172.31.0.4` now reachable.

**Scan loop never completed** (fixed 0700a3d). `_scapy_scan` enumerated whatever
CIDR it was handed, and the configured ranges are deliberately loose. Measured
on this host: a /24 sweep is ~2.6s, so HogNet `/16` was ~11min and the sACN
`10.0.0.0/8` was **~47h**. `run_scan_now` walks subnets sequentially, so the /8
stalled every later subnet indefinitely and Management was never reached. Wide
prefixes are now reduced by `_sweep_targets` to the /24s holding a local NIC or
a previously-seen device; `arp -a` still covers the full CIDR, so only the
ACTIVE probe is narrowed. Full four-subnet loop: never finished -> **65s**.

**Switch firmware/serial were on the wire but discarded** (fixed 0700a3d).
`_enrich_snmp_switch` hardcoded `firmware: None` and set `model` to the entire
raw sysDescr string. Firmware now comes from `entPhysicalSoftwareRev`, boot
version from the sysDescr tail, serial from `entPhysicalSerialNum`. Netgear
reports **no** `entPhysicalHardwareRev` — it returns an empty string — so
HW VERSION is left blank rather than faked from the boot version.

**Venue Wi-Fi is now filtered by subnet, not by OUI** (fixed 2026-07-21).
`NetworkSubnet.ignore_cidrs` holds comma-separated ranges inside a subnet whose
addresses are never persisted as devices — the same treatment randomized MACs
get, applied before the row is written rather than cleaned up after. Seeded to
`172.16.10.0/23` on Management by migration `b3f21c9d47ae`, which also purges
the rows already there. [VERIFIED 2026-07-21] Management went from 148 unknown
devices to 17 total, and repeated sweeps do not bring them back.

One row inside the ignored range survived the purge and should: the FortiGate at
`172.16.10.1`, which had been auto-labelled `Fortinet`. The purge deliberately
spares any row with a label or notes. Note the consequence — that row is now
inside an ignored range, so **it will never be refreshed again** and will sit
permanently offline. Either accept it as a static record, or narrow the ignore
list to exclude `.1`.

**"Remove offline devices", per subnet** (added 2026-07-21).
`POST /api/network/subnets/<id>/clear-offline` sets `hidden=True` on every
offline device in that subnet and returns the count. It is a **soft hide keyed
on MAC, never a delete** — label, notes and vendor data stay on the row, and
`_process_discovered_device` clears `hidden` on any sighting, so a device that
plugs back in returns with everything the operator typed on it. `GET
/api/network/devices` omits hidden rows unless `?includeHidden=1`.

Offline is `scanner.OFFLINE_THRESHOLD` = 90s, which **must** stay equal to
`OFFLINE_THRESHOLD_MS` in `app/src/pages/NetworkMonitor.jsx`. The button clears
exactly what the UI paints red; if the two drift, it silently acts on a
different set than the operator can see. Both constants carry a comment
pointing at the other.

[VERIFIED 2026-07-21] Against MySQL on the live rig: the endpoint hid the one
offline Bolero row and returned `{"hidden":1}`, the two online antennas were
untouched, and a device forced to `hidden=1` came back with `hidden=False` and
its label `Bollero Antenna #1` intact on the next sweep.

## Open

1. ~~Two Hog consoles still not visible on `172.31.x` / Loopback squatting~~
   **RESOLVED 2026-07-23** — loopback's `172.31.210.220` removed; contributing
   cause was also Princess Donut's `/24` mask (now `/16`). Residue: a
   `172.31.0.220` alias remains on the HOG NIC (added while diagnosing; now
   redundant — remove at leisure with
   `Remove-NetIPAddress -InterfaceAlias 'HOG' -IPAddress '172.31.0.220'`).
   Follow-up worth doing at a dark moment: Princess Donut's session crashed
   when a client disconnected — make a fresh show backup and run a show-file
   health check on the console.
2. **Wi-Fi `172.16.11.11/23` overlaps Management `/16`.** Venue Wi-Fi (~50 phones
   with randomized MACs) shares the range; the more specific /23 wins, routing
   `172.16.10-11.x` out the Wi-Fi via a FortiGate. Renumber Management to a /24.
   Mitigated in-app: the scanner now drops locally-administered MACs, so the
   phones no longer land in the device list.
   [MEASURED 2026-07-21] Only partly mitigated — 148 unknown devices sat on
   Management and **145 of them were in `172.16.10.x`/`172.16.11.x`**, i.e.
   inside the Wi-Fi /23. Their OUIs are scattered consumer singletons, so OUI
   matching cannot catch them; the subnet boundary can.
   **Mitigated in-app 2026-07-21** by `ignore_cidrs` — see "Fixed" above. The
   underlying overlap is still there, so renumbering Management to a /24
   remains the real fix; the app just no longer cares.
3. **Rogue second default route** `0.0.0.0/0 -> 10.0.0.1` on the disabled
   "Local Area Connection". NordVPN also holds `10.100.0.2/22` inside the sACN `/8`.
4. **Tailscale ifMetric 5** is below the lighting NICs at 25, so it wins multicast
   egress. Has not stopped the sACN listener, which joins on every interface.
5. **All four lighting NICs are firewall profile "Public".**
6. **SNMP** v2c community `public` / `172.16.0.0` / `255.255.0.0` / ReadOnly is
   configured on `172.16.3.97` and `.98` (the latter added 2026-07-21 and
   verified reading its own serial). The remaining **five** Netgears still need
   it and return `{}` from enrichment until they get it. Luminex answers by
   default. Each unconfigured switch costs ~6s of SNMP retries, so those five
   add ~30s to every Management sweep — configuring them speeds up scanning as
   well as filling in the data.
   The `puresnmp` client itself is fine — pinned in `backend/requirements.txt`
   and present in `backend/.venv`, which is the interpreter `electron/main.js`
   prefers. A "puresnmp not installed" warning means the backend was started
   with the wrong interpreter (e.g. a bare `python` off PATH), not that a
   dependency is missing.
7. **`10.31.2.201` unreachable** — real fault, unresolved. NOTE: the original
   notes give this address as both `10.31.2.201` and `10.31.1.201`; the correct
   octet has not been confirmed.
8. **scapy contributes nothing on this host.** `_scapy_scan` returns 0 answers
   without raising (no Npcap/admin) on every subnet — all real discovery comes
   from `arp -a` plus the ping warm-up. The active sweep should become opt-in
   rather than being paid for on every pass.
9. **Replace sweeping with SNMP, don't just speed it up.** Ask the switches:
   `ipNetToMediaTable` (`1.3.6.1.2.1.4.22.1.2`) is a device's own ARP table, so
   one walk returns the whole VLAN's IP↔MAC map — including quiet devices that
   never answer a ping. `dot1qTpFdbPort` gives MAC→port for everything the
   switch has seen. This scales to a /8 trivially because you query ~7
   switches, not 16.7M addresses. Blocked on item 6 (five switches still need
   SNMP configured).
10. **Enrichment failure is invisible.** `_process_discovered_device` only
   writes `vendor_data` when truthy, so a switch that stops answering SNMP
   silently keeps its last-known blob rather than clearing or flagging it.
11. **Unverified oddity:** two devices with the Luminex OUI `D0:69:9E` on
   `172.16.1.x` were typed `unknown` while six others typed `luminex`
   correctly. Not investigated. May just be stale rows from a pre-fix process.
12. **`ignore_cidrs` has no UI.** It can be set when creating a subnet
   (`POST /api/network/subnets` accepts `ignoreCidrs`) but not edited
   afterwards — changing it on an existing subnet needs SQL or a new PATCH
   route. Fine while the only value is the seeded Wi-Fi /23.

## Environment — read before touching the backend

1. **Python is `backend/.venv/Scripts/python.exe`.** It has scapy, puresnmp and
   pytest. A bare `python` off PATH does not, and produces a misleading
   "puresnmp not installed" warning.

   **Do NOT diagnose this from the process list.** [CORRECTED 2026-07-21 — one
   session already lost time to this] `backend/.venv` was built with a
   redirector, not a copied binary: `pyvenv.cfg` has
   `executable = ...\Programs\Python\Python312\python.exe`, so launching the
   venv python execs the BASE binary while keeping the venv's `sys.prefix` and
   site-packages. Windows therefore reports the base path in
   `Win32_Process.CommandLine` and `Get-NetTCPConnection` for a process that is
   correctly inside the venv. A command line reading
   `AppData\...\Python312\python.exe -m flask run` is **not** evidence of the
   wrong interpreter and proves nothing either way.

   The real test is behaviour, not paths: if `172.16.3.97`/`.98` come back with
   a `serial` in `vendorData`, puresnmp imported and the venv is live. A
   "puresnmp not installed" line in the log is the only reliable negative.

   What IS worth checking is **how many** flask processes exist — see 6.
2. **Dev is MySQL (`five12_website`), the desktop Electron app is SQLite**
   (`~/Five12Data/five12.db`). Different databases, different data — always
   confirm which one you are looking at.
3. **The migration directory is `backend/migrations/`, not the `migrations/`
   at the repo root.** The root one is a dead earlier history and is NOT what
   Alembic reads (CLAUDE.md still points at it and is wrong). Head as of
   2026-07-21 is `b3f21c9d47ae`.
4. **The desktop SQLite database is built by `create_all()`**, which creates
   tables but never adds columns to existing ones. It had no `alembic_version`
   at all until 2026-07-21, when it was stamped `2114aba7e69a` and brought onto
   the migration chain. Any future column must be applied to BOTH databases —
   `flask db upgrade` for MySQL, and again with `FLASK_CONFIG=desktop` for
   SQLite.
5. **The app launches its own backend.** A model change without a matching
   migration breaks the app the moment it restarts, even if your own backend is
   fine. That is how the subnets vanished at the end of 2026-07-21: an
   `ignore_cidrs` column existed on the model for ~30 minutes with no
   migration, the app spawned a backend that loaded it, and every subnet query
   500'd. **Write the migration in the same change as the model edit.**
6. **After ANY backend code change, kill survivors** — `Get-Process python |
   Stop-Process -Force`. A stale process reverts data silently rather than
   failing loudly (see the corrections below). [SEEN 2026-07-21] Four flask
   processes accumulated across one session; each `flask db ...` invocation
   also builds the app, which starts the scanner and the sACN listener, so
   those commands leave a live process behind rather than exiting cleanly.
   Nothing respawns them — killed, they stay dead — so a plain kill-all before
   starting is safe and is the fastest way back to a known state.

```powershell
cd backend
$env:FLASK_APP='app.py'
& .venv\Scripts\python.exe -m flask run --host=127.0.0.1 --port=5000 --no-reload
```

Tests: `& .venv\Scripts\python.exe -m pytest tests/ -q`

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
- **A stale Flask backend silently reverts data — always confirm the old
  process died.** [PROVEN 2026-07-21] After the ARP fix was committed, the
  seven Netgear switches still showed `unknown`. The code was correct; three
  backends from earlier the same day were still running with pre-fix code in
  memory, sweeping on the 30s loop and overwriting `device_type` every cycle.
  Demonstrated by writing `netgear` to `172.16.3.96` and watching it revert 29s
  later while no current-code process was running. The tell was a HALF-updated
  row: new code wrote the `Netgear` label, old code (which only labels on first
  sighting) left the label alone but stomped the type. Two hours went into
  chasing the code before the environment was suspected. `Get-Process python`
  after any backend change; a survivor fails silently rather than loudly.
- **"The wrong interpreter owns port 5000" was a FALSE alarm.** [2026-07-21]
  The venv is a redirector, so every venv-launched process reports the base
  Python path on Windows. Time went into "fixing" a correctly-configured
  process. Verify an environment claim by testing behaviour (does SNMP
  enrichment return a serial?) before acting on a path string. Same failure
  shape as the stale-backend hunt below: the environment was blamed from
  circumstantial evidence instead of a direct test.

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
