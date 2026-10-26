# Five12

Show-network discovery, device visibility, and lighting data management for film and
television production.

Five12 runs on the lighting rig alongside the console. It discovers what is actually on
the show network — fixtures, sACN/DMX nodes, switches, wireless devices, uplinks — and
presents it next to the show's own patch and fixture data, so the network and the
paperwork can be read in one place.

## Why it exists

Show networks are rebuilt from nothing on every set, often on unmanaged switching, and
they give you almost no visibility. When something goes down mid-shoot there are no port
counters to read, no logs to pull, and no topology to consult — only cables and guesses.
Five12 started as an answer to that: a way to see the network while it is still working,
so that when it stops, isolation takes a minute instead of an hour.

## What it does

**Network and device discovery**

| Source | What it surfaces |
|---|---|
| ARP / subnet scanning | Live hosts per configured subnet, MAC-keyed device records |
| SNMP switch queries | Per-device switch ports, port state, uplink resolution |
| sACN (E1.31) listener | Active universes and sources seen on the wire |
| NETGEAR AV-line snapshots | Parsed port configuration, profiles, and neighbor tables |
| BLE scanning | Wireless lighting devices (Cintenna / CRMX), advertisement decoding |
| LumenRadio Stardust | Wireless DMX output stream state |
| Riedel Bolero | Comms appliance status |
| Starlink (gRPC) | Link telemetry for remote and backlot units |
| Local interfaces | Host adapter enumeration, addressing, route inspection |

**Show data**

Patch sheets with DMX universe and address conflict detection, a fixture library with
mode and channel-count records, Excel import/export, and a drag-and-drop label designer
with Dymo printing.

## Safety model

Every feature that can touch hardware is behind an environment gate that **defaults to
off**, so a hosted or unattended deployment never drives a radio, a console, or a tablet
unasked. On the show rig, launching Five12 is itself the request, and the launcher turns
on what that rig needs.

| Gate | Default | Enables |
|---|---|---|
| `FIVE12_NETWORK_TOOLS` | on | Interface enumeration and route inspection (read-only) |
| `FIVE12_BLE_TOOLS` | off | Passive BLE discovery and connected-status reads |
| `FIVE12_BLE_WRITE` | off | BLE writes: mode switch, Link, Unlink |
| `FIVE12_MIRROR_TOOLS` | off | Astera tablet mirror (spawns `adb`) |
| `FIVE12_DEVICE_SIM` | off | Simulated adapters for development without hardware |

Two properties worth stating plainly:

- **Five12 never writes switch, router, or AP configuration.** There is no SNMP SET and no
  config push. Infrastructure is read-only, always.
- **Device writes are narrow and gated.** The only outbound device control is BLE commands
  to wireless lighting fixtures, behind `FIVE12_BLE_WRITE`. Host adapter addressing can be
  changed from the IP Config page, which acts on the machine Five12 runs on — not on
  anything else on the network.

A disabled gate is never silent. The feature reports itself disabled and names the
variable that would enable it, because an undocumented gate reads as a broken feature.

## Architecture

```
app/        React + Vite frontend (Tailwind)
backend/    Flask + SQLAlchemy API
  app/
    scanner.py            subnet / ARP discovery
    network_routes.py     subnets, devices, ports, uplinks, scan triggers
    sacn_listener.py      E1.31 universe listener
    five12_ble/           BLE stack: scanner, GATT client, decoders, commands
    integrations/         starlink, stardust, cintenna, bolero, android_mirror
    vendors/              netgear_snapshot parsing
    models.py             ORM models
  migrations/             live Alembic history
electron/   desktop shell
scripts/    rig tooling, including Five12Doctor (host network diagnostics)
docs/       architecture notes and feature plans
```

The frontend talks to the backend over `/api/*`, which Vite proxies in development.
Backend JSON uses camelCase keys over snake_case columns.

**Storage:** MySQL in development, SQLite in desktop mode.

## Running it

Backend, from `backend/`:

```
flask run
```

Frontend, from `app/`:

```
npm run dev
```

Both run concurrently; Vite serves on `:5173` and proxies `/api/*` to `:5000`.

Database schema is managed with Flask-Migrate. Run `flask db upgrade` from `backend/` —
the live Alembic history is `backend/migrations/`, and Flask-Migrate resolves that path
relative to the working directory.

## Configuration

Copy `.env.example` to `backend/.env` and fill in local values. The example file documents
every variable, including which feature each gate controls and what happens when it is
left at its default. No real credentials belong in the repository.

## Tests

```
pytest                 # from backend/  — 62 test modules
npm run test           # from app/      — 16 test modules (Vitest)
```

Coverage includes the BLE command path, patch import, the NETGEAR snapshot parsers against
captured fixture pages, and the host network probe.

## Status

Built and used on a working film production. Developed with AI-assisted tooling
(Claude Code, Codex) under a documented review and verification workflow; see `docs/`.
