# Network Monitoring Dashboard — Design Spec

**Date:** 2026-05-21  
**Status:** Approved  
**Subsystem:** #1 of 6 (Film Set Toolkit)

---

## Overview

A live network monitoring dashboard for use on film sets. Discovers devices across multiple VLANs (management, sACN, Bolero, internet), shows vendor-enriched status for each device, allows notes keyed to MAC address, and saves named location snapshots for historical reference.

Designed for daily use by a single operator managing Luminex switches, Swisson DMX nodes, Ubiquiti access points, Starlink, and Bolero intercom infrastructure on a film set.

---

## Context: Network Setup

The operator will have one of two setups:

1. **Multiple USB NICs** — one NIC per VLAN (management, sACN, Bolero, internet)
2. **VMware VLAN-router VM** — trunk line into laptop, VM handles VLAN tagging

Both setups result in the same thing from the Flask backend's perspective: multiple subnets reachable via different interfaces. The app needs no special per-setup logic — it sweeps whichever subnets are configured and Python's socket stack routes via the correct interface automatically.

---

## Architecture

### Scan Layer (Flask backend)

- A background thread runs ARP sweeps on each configured subnet every 30 seconds
- Python library: `scapy` for ARP requests (requires elevated privileges on Windows; document this)
- After ARP resolves a MAC, a **vendor-detect step** fires:
  1. Checks MAC OUI prefix against a known vendor table (Luminex, Ubiquiti, Swisson, etc.)
  2. Probes the vendor's management API on that IP for enriched data
  3. Falls back to "unknown" with online/offline ping only if no vendor match

- Results are written to MySQL; frontend polls `GET /api/network/devices`
- A `POST /api/network/scan/trigger` endpoint fires an immediate scan outside the 30s cycle

### Vendor API Integrations

| Vendor | Device | Protocol | Data Retrieved |
|--------|--------|----------|----------------|
| Luminex | GigaCore switches | REST (`/api/v1/system`) | Model, firmware, uptime, port count, active ports |
| Ubiquiti | UniFi APs, Dream Machine | UniFi local API | AP status, client count, uplink health |
| Ubiquiti | GigaBeam | SNMP or airOS scrape | Link state, signal strength |
| Starlink | Dish | gRPC at `192.168.100.1` | Obstruction %, latency, download/upload |
| Swisson | XND nodes | sACN broadcast discovery | Node presence, universe assignments |
| Unknown | Any | ICMP ping | Online/offline only |

All vendor data is stored as a JSON blob in `vendor_data` — adding a new vendor requires no schema change.

### Subnet Configuration

Users define subnets to scan in a settings screen. Each subnet has:
- A human label ("Management", "sACN", "Bolero", "Internet")
- A CIDR string (e.g. `192.168.10.0/24`)
- An optional interface hint (e.g. `eth1`) for multi-NIC setups
- A color (used for sidebar badge and device list accent)

---

## Data Model

### `network_subnet`
```
id              INT PK AUTO_INCREMENT
label           VARCHAR(100)          -- "Management", "sACN", etc.
cidr            VARCHAR(50)           -- "192.168.10.0/24"
interface_hint  VARCHAR(50) NULL      -- "eth1", optional
color           VARCHAR(20)           -- hex color for UI accent
active          BOOLEAN DEFAULT TRUE
created_at      DATETIME
```

### `network_device`
```
mac_address     VARCHAR(17) PK        -- "AA:BB:CC:DD:EE:FF"
label           VARCHAR(100) NULL     -- user-assigned name
device_type     VARCHAR(50)           -- luminex|ubiquiti_ap|ubiquiti_gigabeam|starlink|swisson|unknown
subnet_id       INT FK NULL           -- which subnet it was last found on
notes           TEXT NULL             -- freeform, persists across locations
last_ip         VARCHAR(15)
last_seen       DATETIME
vendor_data     JSON NULL             -- model, firmware, ports, signal, etc.
created_at      DATETIME
```

### `location_snapshot`
```
id              INT PK AUTO_INCREMENT
name            VARCHAR(200)          -- "Warner Bros Lot 3 - Stage A"
created_at      DATETIME
```

### `location_device`
```
id                    INT PK AUTO_INCREMENT
location_id           INT FK → location_snapshot.id
mac_address           VARCHAR(17)
ip_at_time            VARCHAR(15)
online_at_time        BOOLEAN
vendor_data_at_time   JSON NULL       -- frozen copy of vendor_data at save time
```

**Key invariant:** Notes and labels live on `network_device` keyed to MAC address — they follow the physical device forever regardless of IP changes or location. Location snapshots freeze IP and vendor state at a point in time but never overwrite the live notes.

---

## API Endpoints

```
GET    /api/network/subnets              List configured subnets
POST   /api/network/subnets              Add a subnet
DELETE /api/network/subnets/:id          Remove a subnet

GET    /api/network/devices              All known devices (with last_ip, status, vendor_data)
PATCH  /api/network/devices/:mac         Update label or notes
DELETE /api/network/devices/:mac         Remove a device from history

POST   /api/network/scan/trigger         Trigger immediate scan (returns 202, scan runs async)

GET    /api/network/locations            List saved location snapshots
POST   /api/network/locations            Save snapshot of current device state
GET    /api/network/locations/:id        Devices present in a saved location
DELETE /api/network/locations/:id        Delete a saved location
```

All responses use camelCase JSON per existing API conventions.

---

## UI — Layout B (Sidebar + Detail Panel)

### Shell

```
┌─────────────────────────────────────────────────────────────────┐
│ Network Monitor  ● scanning...  [Scan Now]  [⊞ Save Location]  │
├──────────────┬──────────────────────┬───────────────────────────┤
│ NETWORKS     │ Management · 3/4 ●  │  GigaCore 12              │
│ ● Management │ ─────────────────── │  http://192.168.10.5 ↗    │
│ ● sACN       │ 🟢 GigaCore 12  ↗  │                           │
│ ● Bolero     │ 🟢 GigaCore 26  ↗  │  MAC  AA:BB:CC:DD:EE:FF   │
│ ● Internet   │ 🔴 Switch #3        │  Type Luminex GigaCore 12 │
│              │ ⚠ Unknown .22   ↗  │  FW   3.2.1               │
│ LOCATIONS    │                     │  Ports 12 · 10 up · 2 dn  │
│ Warner Bros  │                     │  Uptime 6h 14m            │
│ Sony Lot 4   │                     │                           │
│ + Save...    │                     │  NOTES                    │
│              │                     │  [House left truss · ...] │
│              │                     │                           │
│              │                     │  SEEN AT LOCATIONS        │
│              │                     │  📍 Warner Bros · May 10  │
│              │                     │  📍 Sony Stage A · Apr 28 │
└──────────────┴──────────────────────┴───────────────────────────┘
```

### Sidebar
- Networks section: each subnet as a colored badge showing label and online/total count
- Locations section: saved snapshots listed chronologically, most recent first
- "+ Save current…" shortcut at bottom opens the save modal

### Device List (middle panel)
- Devices sorted: online first, then offline, then unlabeled/unknown
- Each row: status dot, label (or IP if unlabeled), IP with ↗ link, truncated notes preview
- Offline devices show red background + "last seen X ago" — never auto-removed
- Unlabeled devices show amber ⚠ badge as a prompt to label them
- When viewing a saved location, list shows snapshot state (greyed, read-only, with "Snapshot from [date]" header)

### Detail Panel (right)
- Header: device label (editable inline), IP link to device GUI, online/offline badge
- Metadata grid: MAC, device type, firmware, uptime, port counts, last seen
- Notes: click-to-edit textarea, autosaves on blur, persists to MAC address
- Seen At Locations: list of every snapshot where this MAC appeared, with IP at the time

### Save Location Modal
- Single text field: "Location name"
- On confirm: snapshots all currently-known devices (online + offline) with their current IPs and vendor data
- Appears immediately in the sidebar Locations list

### Scan Controls
- Auto-scan every 30s; spinner in header while active
- [Scan Now] button triggers immediate sweep; disabled while scan is in progress
- Scan status line shows "Last scan: X seconds ago"

---

## Error Handling

- **Device goes offline:** Badge turns red, "last seen X ago" — stays in list until manually cleared. No data loss.
- **Vendor API unreachable:** Device still appears (from ARP), `vendor_data` shows last known value with a "stale" indicator. Never blocks the scan.
- **ARP requires elevated privileges:** App startup checks for required permissions; shows a clear error in the UI if missing, with instructions to run as administrator or configure `cap_net_raw`.
- **Subnet unreachable (NIC not connected):** Subnet shows "unreachable" badge in sidebar; other subnets continue scanning normally.

---

## Out of Scope (v1)

- Configuring device settings from within the app (use the ↗ link to the device's own GUI)
- Push alerts / notifications for offline devices (v2)
- SNMP trap receiver (v2)
- Multi-user / shared state (single operator tool)

---

## Dependencies

- **Python:** `scapy` (ARP scanning), `requests` (vendor HTTP APIs), `grpcio` + `spacex.api` protobuf (Starlink)
- **Existing:** Flask, SQLAlchemy, Flask-Migrate, PyMySQL
- **New DB migrations:** 4 new tables — `network_subnet`, `network_device`, `location_snapshot`, `location_device`
