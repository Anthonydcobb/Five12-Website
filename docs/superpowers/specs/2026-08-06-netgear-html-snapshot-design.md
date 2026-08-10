# NETGEAR M4250 settings from a saved AV UI page — design

- **Date:** 2026-08-06
- **Author:** Claude Code, with Anthony
- **Status:** implemented and merged 2026-08-07, verified on the rig — see
  Verification below
- **Scope:** Network tab only. Read-only. No change to the Devices tab, the DMX
  node port table, or any existing enrichment path.

## Problem

The Network tab knows a NETGEAR switch exists — the OUI map resolves `28:94:01`
and 25 other NETGEAR prefixes to `device_type = 'netgear'` — but it shows almost
nothing about one. `_enrich_netgear` is SNMP-only, and its own comment records
why that mostly yields nothing:

> M4250 answers MIB-II once v2c is enabled — it is NOT on by default, unlike
> Luminex. Configure per switch [...] Returns {} until then.

Seven switches are on the rig. One has v2c configured. The other six enrich to
`{}` on every sweep, so their panels show a model and nothing else.

Meanwhile the switch's own AV UI has all of it on one page: serial, firmware,
boot version, uptime, management IP, STP role, fan mode, temperature, CPU and
memory, the full profile table (FixtureNet / Comms / VidNet / HogNet with their
VLANs and colors), and per-port VLAN, profile, PoE, link state and connected
host.

None of that is reachable without leaving the app, opening each switch's GUI,
and reading it — which is exactly the friction the DMX node port table was built
to remove for Swisson and ACPD nodes.

## Goals

1. Selecting a NETGEAR switch in the Network tab shows its device details,
   its configured profiles, and a per-port table — the same facts the switch's
   own Overview page shows.
2. Getting that data in requires no switch reconfiguration: no SNMP, no
   credentials stored, no new listening port.
3. The data is always presented with the time it was captured, because it is a
   manual snapshot and stale by definition.
4. A snapshot is never silently attributed to the wrong switch.
5. A layout change in NETGEAR's UI degrades to less data, never to wrong data.

## Non-goals

- **Writing to switches.** Read-only throughout. Changing a profile or a port
  stays a job for the switch's own GUI.
- **Live polling.** A live REST client against the AV UI's API is the intended
  successor to this and is deliberately out of scope here; see Future work. The
  field mapping this spec defines is what that client would populate too, so
  none of the parsing or UI work is throwaway.
- **Replacing SNMP.** The one switch with v2c configured keeps enriching by
  SNMP, and SNMP keeps winning for the fields it returns.
- Any change to Luminex, Ubiquiti, Swisson, ACPD, Stardust or Starlink
  enrichment.

## Approach

A saved copy of the switch's Overview page is pasted into the Network tab. A
pure parser turns it into the same `vendorData` shape the tab already renders,
matched to the right switch by the management IP printed in the page itself.

### Components

**`backend/app/vendors/netgear_snapshot.py`** — one public function:

```python
def parse_snapshot(html: str) -> dict
```

No network, no database, no Flask. Given a string, returns a dict. That is the
whole contract, and it is what makes this testable against a real captured page
without a switch in the room.

Three groups come out of it.

*Device details*, from the stable `#device_*` element ids the AV UI assigns:
`device_serial`, `device_mac`, `device_firmware`, `device_bootver`,
`device_avuiversion`, `device_uptime`, `device_manageip`, `device_stp`,
`fan_temp`, `max_temp`, `fan_mode`, `cpu_monitor`, `memory_monitor`,
`product_name`, `device_model`, `device_name`.

CPU and memory carry their value twice — as `aria-valuenow` on the progress
element and as text inside it. Read the attribute; it is the unformatted number
and needs no stripping of a `%` sign.

*Profiles*, from the Configured Profiles table: name, template, VLAN id, IP,
assigned port count, and the swatch color — so the Network tab can render a
profile in the same color the switch does, rather than inventing a second
palette for the same four networks.

The profile table cannot be read by id. The AV UI emits `id="profile_name"` and
`id="profile_color"` on *every* row — duplicate ids, invalid HTML that browsers
and parsers both tolerate. An id lookup returns only the first row, which would
silently import one profile out of five. Parse by walking `tbody` rows and
taking cells positionally.

*Ports*, from the port graphic: port number, media (copper / fiber), link state,
PoE presence, and trunk type — the `M` (manual) and `A` (auto) badges. Enriched,
where available, with the popover fields: VLAN, profile name, profile template,
connected host, MAC, IP, link speed, and power draw.

**`NetgearPortTable`** — a new component, not an extension of `PortTable`. A DMX
port and a switch port share only the word "port": one has universe, protocol
and direction, the other has VLAN, profile and PoE. Forcing them into one
component would mean a table where most columns are blank for whichever kind it
is rendering.

**Import panel** — a paste box in the Network tab, with a confirm step that
shows what was parsed (which switch, how many profiles, how many ports, and any
degradations) before anything is written.

### The popover alignment problem

This is the one genuinely fragile part of the page, and it drives a specific
guard.

Port popovers do not live inside the port elements they describe. The AV UI
renders them into a detached `#el-popper-container-*` at the end of the body,
and the only thing tying a popover to a port is document order.

On the captured page that order is exact: twelve ports, twelve popover pairs,
correctly aligned — ports 1 and 2 carry all five VLANs as manual trunks, port 3
is HogNet on 600, ports 4–7 and 9 are FixtureNet on 300, port 8 is Comms on 400,
port 10 is the auto-trunk uplink to FMB Switch 76, and ports 11–12 are the fiber
pair on Default. Every one of those cross-checks against the port's own color
swatch and badge.

But that is an observation about NETGEAR's renderer, not a contract it owes
anyone. So:

- Port number, media, link state, PoE and trunk type are read from the port
  elements directly. These carry their own port number in the markup and are
  never at risk from ordering.
- Popover-sourced fields are accepted **only** when the popover count exactly
  matches the port count. On any mismatch they are dropped wholesale, the rest
  of the import proceeds, and the panel says per-port host data was unavailable
  for this snapshot.

Dropping a column is recoverable. Attributing port 7's connected fixture to port
6 is not — it is the kind of wrong that gets trusted and acted on.

The same principle governs the profile-color and VLAN reads: a field that cannot
be located is absent, never defaulted. This follows the `'code N'` convention
already established for unmapped port enums in `vendors/__init__.py` — never
blank, never guessed.

### Storage and precedence

Parsed output merges into the existing `vendorData` blob on `NetworkDevice`,
stamped `snapshotAsOf` (naive-UTC ISO via `_utc_iso`, matching every other
timestamp in this module) and `source: 'html-snapshot'`.

Switch ports are stored under **`netgearPorts`** — not `ports`, and not
`switchPorts`. Both are already taken, by different features, with
incompatible shapes.

`ports` belongs to the DMX node patch: `PortTable` renders whenever
`vendorData.ports` is non-empty, and `/api/network/devices/<mac>/ports`
re-reads that key live via `read_port_status`. Using it would render a DMX
universe/protocol table for every switch and point a DMX node endpoint at a
switch's IP.

`switchPorts` belongs to the GigaCore port-to-device map (branch
`spec/gigacore-port-device-map`), which writes
`{port, name, link, macs, deviceCount}` read from BRIDGE-MIB. That reader is
generic to any managed switch, so wiring it into `_enrich_netgear` would put
GigaCore-shaped ports over this feature's on every sweep.

The two port datasets are complementary rather than competing: the SNMP map
answers *what is behind port 6*, this snapshot answers *what VLAN and profile
is port 6 in*. On an M4250 with SNMP v2c enabled both are worth having. They
are kept in separate keys so neither feature blocks the other, and so a future
merged view — if one is ever wanted — can be built from two stable shapes
rather than negotiated between two moving ones.

Profiles are stored under `profiles`, which nothing else claims.

Precedence between the snapshot and SNMP:

- SNMP wins for any field it actually returns — `model`, `firmware`,
  `bootVersion`, `portCount`, `activePorts`, `serial`. It is live; the snapshot
  is not.
- The snapshot supplies everything SNMP has no OID for: profiles, per-port VLAN
  and profile assignment, PoE, uptime, fan mode, temperature, CPU, memory, AV UI
  version, STP role.
- **An empty or partial SNMP result never clears snapshot fields.** This is the
  load-bearing rule. `_enrich_snmp_switch` returns `{}` for six of seven
  switches on every sweep; a naive `vendor_data = enrich_device(...)` assignment
  would erase an imported snapshot within seconds of it being saved.

Both sources keep their own timestamps, so the UI can show a live firmware
reading next to a two-day-old profile table and be honest about both.

### Matching a snapshot to a switch

Matching is on the **management IP** (`device_manageip`), against
`NetworkDevice.last_ip`.

This design originally matched on the serial plus the base MAC the page prints,
and that was wrong in a way only the rig could reveal. The page's "Base MAC
Address" is the CHASSIS MAC; the management interface ARPs with a different one,
so the scanner's row never carries the value the page reports. Matching on base
MAC refused all fifteen switches on the rig — including switches sitting in the
device table at the very IP the page named. The unit tests passed throughout
because they fabricated the device row from the page's own base MAC, the one
value guaranteed to agree with itself.

Observed pairs, page → scanner row: switch 60 `3A:02`→`3A:05`, switch 73
`3C:DE`→`3C:E1`, switch 52 `47:02`→`47:05`, switch 76 `3C:1A`→`3C:1D`, switch 69
`46:52`→`46:55`. The offset is a consistent +3 and is deliberately NOT used:
five samples of one firmware is not a rule, and deriving an identity from a
guessed arithmetic relationship is precisely the silent misattribution this
route exists to prevent.

- Exactly one device at that IP → import.
- No device at that IP → refuse, and say so. No row is created. A switch the
  scanner has never seen is a discovery problem, not something to invent a
  record for from a pasted document.
- More than one device at that IP → refuse as ambiguous. Picking one would be a
  coin toss.
- The device already holds a different serial → refuse and report the conflict.

The page's base MAC is still stored in `vendorData` for reference — it is the
chassis identity and worth having — it is simply not the matcher.

The refusal path is what makes it safe to paste fifteen pages in a row without
tracking which is which.

### UI

Device details extend the existing meta cells in `DeviceDetail` — the same
`MetaCell` row that renders `FIRMWARE` and `PORTS` today.

Profiles and ports each get a table below it, `NetgearPortTable` for the latter.

Every panel fed by a snapshot shows its capture time. Not in a tooltip — on the
face of the panel, next to the data. An operator reading a port table during a
show needs to know at a glance whether they are looking at something from ten
minutes ago or from load-in.

## Error handling

Every failure mode resolves to *less data, clearly labelled*, never to wrong
data or a crash:

| Condition | Result |
|---|---|
| Not a NETGEAR AV UI page | Refused before parsing, with what was expected |
| Serial or management IP absent | Refused before matching |
| No device at that management IP | Refused, no row created |
| More than one device at that IP | Refused as ambiguous |
| Stored serial disagrees with the page | Refused, conflict reported |
| Popover count ≠ port count | Ports imported without host data, noted in UI |
| A `#device_*` id missing | That field absent; rest of the import proceeds |
| Profile table missing or empty | Profiles absent; device details and ports proceed |
| Malformed HTML | Parser returns what it could locate; never raises past its own boundary |

The parser never raises to its caller. It is fed operator-pasted text from a
device whose firmware can change under us — the same defensive posture
`read_port_status` takes for exactly the same reason.

## Testing

TDD, against a real captured page as the primary fixture.

**Fixture capture:** in the switch's AV UI, on Configure → Overview, save the
rendered page (browser Save Page As, or copy `document.documentElement.outerHTML`
from the console) to `backend/tests/fixtures/netgear_m4250_overview.html`. The
console form is preferred — it captures the Vue-rendered DOM, which is what the
parser reads. A raw `view-source` of the SPA shell contains none of the data.

Cases:

1. Full parse of the fixture — every device detail field, all five profiles with
   VLANs and colors, all twelve ports with VLAN/profile/link/PoE/trunk.
2. Popover alignment on the good fixture — port 3 is HogNet/600, port 8 is
   Comms/400, port 10 is the trunk to FMB Switch 76.
3. Count mismatch — fixture with a popover removed; ports still import, host
   data absent, degradation flagged.
4. Missing device fields — fixture with `#device_serial` stripped; import
   refused for lack of identity.
5. Unmatched serial — parses clean, matches no device, refused, no row created.
6. Conflicting serial — target device holds a different serial, refused.
7. SNMP does not clobber — device with a stored snapshot, `enrich_device`
   returns `{}`, snapshot fields survive.
8. SNMP precedence — SNMP returns a firmware, snapshot has an older one, SNMP's
   is shown and the snapshot's other fields are untouched.
9. Non-NETGEAR input — arbitrary HTML refused cleanly.
10. `NetgearPortTable` renders VLAN, profile, PoE, link speed and connected host,
    and renders a port with no popover data without blank-looking holes.

## Future work

A live REST client against the AV UI's own API. The UI is a Vue SPA driving a
token-authenticated backend, so the same facts are available as JSON without any
HTML parsing — and without the popover-ordering fragility this design has to
guard against.

That work needs endpoint discovery and stored per-switch credentials, which is
why it is separate. When it lands it populates the same `vendorData` fields
defined here, with `source: 'av-ui-api'` instead of `'html-snapshot'`, and the
precedence rule extends by one rank: live API > SNMP > snapshot. The parser,
the tables, and the profile colors all carry over unchanged.


## Verification

Unit and route tests cover the parser, the identity rules and the precedence
rule, but the defect that mattered most was invisible to all of them — see
Matching above. What was checked against live hardware:

- **Import succeeds** — the Overview page of FMB Switch 69 (`172.16.3.69`) was
  captured from the live switch and imported through the panel. Profiles and
  per-port data populated. [VERIFIED 2026-08-07]
- **Import refuses correctly** — the page for a switch absent from the device
  table was posted to the route; it returned `unknown_device` naming the address,
  and a read-only query confirmed no row had been created. [VERIFIED 2026-08-07]

Not verified on hardware: the ambiguous-IP refusal, and the serial-conflict
refusal. Both are covered by route tests only.

Known gap: once a serial is stored for an IP, a page reporting a different
serial is refused permanently, with no override short of editing the database.
Narrow in practice — a replaced switch normally arrives at a new address — but
undocumented elsewhere, so it is recorded here.
