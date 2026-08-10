# Starlink dish telemetry via gRPC reflection — design

- **Date:** 2026-08-06
- **Author:** Claude Code, with Anthony
- **Status:** design approved, not implemented
- **Scope:** `StarlinkAdapter`'s real-status path and the tiles the existing
  panel already declares. The panel's layout, the adapter's public contract,
  the history/sparkline plumbing and the simulator path are all unchanged.

## Problem

The Devices tab has a Starlink panel, and it has never worked on this machine.

`StarlinkAdapter._real_status` opens with `import starlink_grpc` and, on
failure, returns:

```python
'reason': "Python package 'starlink-grpc-tools' not installed "
          "(pip install starlink-grpc-tools grpcio)"
```

**That command cannot succeed.** `starlink-grpc-tools` is not on PyPI — pip
reports `from versions: none`. It is a GitHub repository of scripts
(`sparky8512/starlink-grpc-tools`), not a published package. So the panel has
only ever rendered its "unavailable" state, and the remedy it offers is a
dead end.

Meanwhile `detect()` works and reports `gRPC port open`, so the app has been
correctly telling the operator the dish is there while being unable to say
anything about it.

## Goals

1. The Starlink panel shows live dish telemetry, with no borrowed third-party
   code on a machine that runs shows.
2. Nothing this feature does can change the dish's configuration or state.
3. The two tiles the panel already declares but hardcodes empty —
   `outagesLastHour` and `outageLog` — start carrying real values.
4. The adapter's public contract, the panel layout, and the simulator path are
   unchanged, so nothing else in the Devices tab has to move.

## Non-goals

- **Wi-Fi and router data.** See "The Wi-Fi wall" — the dish declines those
  RPCs and the router exposes no reachable API. Designing against
  `UNIMPLEMENTED` is guessing, which is the failure this repo has paid for
  four separate times today.
- Vendoring or installing `starlink-grpc-tools` from git. Rejected below.
- Any dish command that is not a read. See Safety.
- Obstruction map imagery (`dish_get_obstruction_map`). A different feature.

## What the hardware actually serves

> **Measured 2026-08-06 — `verified on actual gear`.** Every figure below is
> from live calls against the dish on this rig.

**Reflection is enabled.** `192.168.100.1:9200` answers
`grpc.reflection.v1alpha.ServerReflection` and advertises:

```
SpaceX.API.Device.Device
grpc.reflection.v1.ServerReflection
grpc.reflection.v1alpha.ServerReflection
```

One `file_containing_symbol` lookup for `SpaceX.API.Device.Device` returns the
**full transitive descriptor set — 19 files**, including `device.proto`
(the service), `dish.proto` (51 messages), `common.proto` (32) and the
`wifi*.proto` family (79 + 20 + 7). No stubs need to be generated or shipped.

The service is `Device.Handle(Request) -> Response`, where `Request` is a
**oneof of 92 options**.

A real `get_status` call returns, among other fields:

```
device_info      rev4_panda_prod2 · sw 2026.05.05.mr79639.1 · bootcount 144
device_state     uptime_s 1493
obstruction_stats fraction_obstructed 0.5190484, valid_s 1237,
                 time_obstructed 0.0116, patches_valid 6011
alerts           {install_pending: true}
throughput       downlink 1_239_517 bps / uplink 36_808_920 bps
pop_ping_latency_ms 19.365892      eth_speed_mbps 1000
gps_stats        gps_valid true, gps_sats 12
boresight        azimuth 143.63°, elevation 75.94°
mobility_class   MOBILE            class_of_service CONSUMER
software_update_state REBOOT_REQUIRED
disablement_code OKAY              is_snr_above_noise_floor true
ready_states     scp/l1l2/xphy/aap/rf all true
```

A real `get_history` call returns:

```
current                 1714            (ring-buffer write index)
outages                 list of 32
pop_ping_drop_rate      900 samples     pop_ping_latency_ms      900 samples
downlink_throughput_bps 900 samples     uplink_throughput_bps    900 samples
power_in                900 samples
event_log.events        severity · reason · start_timestamp_ns · duration_ns
                        EVENT_REASON_OUTAGE_BOOTING / _NO_DOWNLINK / _SKY_SEARCH
```

Those three event fields map directly onto the shape the panel's existing
outage log already renders — `ts`, `durationS`, `cause` — so filling it is a
translation, not a redesign.

### Two reflection details worth writing down

- `ServerReflectionRequest` field numbers are `file_by_filename = 3`,
  `file_containing_symbol = 4`, `list_services = 7`. Getting this wrong
  produces a confusing `INTERNAL: failed to unmarshal the received message`
  from the server rather than a helpful error — it cost a round trip here.
- Descriptors must be added to the pool **in dependency order**, or
  `DescriptorPool.Add` raises on a missing import.

### The Wi-Fi wall

Anthony asked for Wi-Fi information alongside the dish. It is not available:

| Probe | Result |
|---|---|
| `wifi_get_clients` on the dish | **`UNIMPLEMENTED: *device.Request_WifiGetClients`** |
| Router `192.168.1.1` HTTP, any path | 200, `text/html`, **identical 5307-byte `index.html`** — including `/definitely/not/a/real/endpoint` |
| Router `192.168.1.1:9200` | closed |
| Dish HTTP `192.168.100.1` `/status`, `/api/status`, `/statistics`, `/support/statistics` | 404 |

The dish carries the Wi-Fi *message definitions* because both devices share a
proto set, but it does not serve those RPCs. The router presumably does, on a
port not yet found. **Until that endpoint is located and a real response seen,
Wi-Fi stays out.**

Note also that the router's LAN is `192.168.1.0/24`, the same range as the
app's configured "Bolero" subnet — worth knowing before both are live on one
rig, though it is not this feature's problem.

## Approach

| | Approach | Verdict |
|---|---|---|
| **A** | Self-contained reflection client, `grpcio` + `protobuf` only | **Chosen** |
| **B** | `pip install git+https://github.com/sparky8512/starlink-grpc-tools` | Rejected |
| **C** | Vendor `starlink_grpc.py` and generated protobufs into the repo | Rejected |

B puts whatever is on a third party's default branch onto a show machine,
unpinned, and can change under us between deploys. C freezes that risk but
means maintaining someone else's generated code, and the generated stubs go
stale against dish firmware while reflection never does — the dish tells us its
own current schema on every connection.

A costs more code than either, and that code is the price of the dish being the
only thing on the rig we depend on. Both dependencies are mainstream and
already installed: `grpcio` 1.83.0 (no transitive dependencies) and `protobuf`
7.35.1.

### The client

A new `backend/app/integrations/starlink_grpc_client.py`, deliberately separate
from the adapter so the reflection mechanics can be understood and tested on
their own:

```python
def call(request_name: str, host: str = '192.168.100.1', port: int = 9200,
         timeout: float = 10.0) -> dict
```

It connects, fetches the descriptor set by reflection, builds the pool in
dependency order, constructs `Request` with the named oneof field set, calls
`Handle`, and returns the response as a plain dict via
`json_format.MessageToDict(preserving_proto_field_name=True)`.

Descriptors are cached per process — the dish's schema does not change between
calls, and re-fetching 19 files on every poll would be wasteful on a device
that is also carrying the show's internet.

### Safety — a read-only allowlist

The `Request` oneof includes `reboot`, `dish_stow`, `factory_reset`,
`dish_factory_reset`, `dish_inhibit_rf`, `dish_set_config`, `software_update`,
`set_sku` and `wifi_set_config`. **The endpoint is unauthenticated**: anything
that can reach `192.168.100.1:9200` can issue them.

So `call()` accepts only names in an explicit allowlist:

```python
_ALLOWED = frozenset({'get_status', 'get_history'})
```

`get_device_info` was in this list until it was actually called: it returns the
same `device_info` block that `get_status` already carries, so it earns no
place. Two allowlisted reads, both verified to return real data.

A name outside it raises `ValueError` before a channel is opened. A test
asserts no mutating request name appears anywhere in the module's source, the
same discipline the GigaCore work established for SNMP — and for the same
reason: on this rig the dish is the internet, and an accidental `reboot` is a
show-stopper.

### The adapter

`_real_status` keeps its signature, its `{'available': False, 'reason': ...}`
failure shape and every key it already returns, so the panel needs no change to
keep working. Its internals become two allowlisted calls:

- `get_status` — the fields it already maps, read from the real payload's
  actual names (`dish_get_status.device_state.uptime_s`,
  `obstruction_stats.fraction_obstructed`, and so on).
- `get_history` — fills `outagesLastHour` and `outageLog`, which are currently
  hardcoded `None` and `[]` behind a `needs history_data(); v2` comment.

New keys, each one a field observed in the live payload rather than hoped for:
`hardwareVersion`, `softwareVersion`, `bootcount`, `softwareUpdateState`,
`gpsValid`, `gpsSats`, `ethSpeedMbps`, `mobilityClass`, `disablementCode`,
`obstructionValidS`.

The `reason` string for a missing dependency is rewritten to name `grpcio` and
`protobuf`, which can actually be installed.

### The panel

Additive only. The existing tiles and sparklines are untouched; `outagesLastHour`
and `outageLog` simply start having values. A device-info line
(hardware/software/bootcount) and a software-update-state chip are added, the
latter surfacing when the dish says `REBOOT_REQUIRED` — as it does right now.

## Testing

Against a captured real `get_status` payload, not a composed one:

- The client builds a pool from the 19-file descriptor set and constructs a
  valid `Request` for each allowlisted name.
- A name outside the allowlist raises `ValueError` **before** any channel is
  opened — asserted by patching `grpc.insecure_channel` and asserting it was
  never called.
- **No mutating request name appears in the module source** (`reboot`,
  `factory_reset`, `dish_stow`, `dish_inhibit_rf`, `software_update`,
  `set_sku`, `wifi_set_config`).
- An unreachable dish yields `{'available': False, 'reason': ...}` and never
  raises — the adapter is polled on a timer.
- The adapter maps the captured payload to every key the panel reads, including
  the previously-empty outage fields.
- Frontend: the new device-info line and update-state chip render, and are
  absent when those keys are missing, so a dish on older firmware degrades
  rather than showing blanks.

## Open question, deliberately left open

Where the router serves its gRPC endpoint. `9200` is closed on `192.168.1.1`
and its HTTP is a single-page app with no API behind it. Until that is found
and a real `wifi_get_clients` response is seen, the Wi-Fi half of the original
request cannot be designed honestly, and this spec does not attempt it.
