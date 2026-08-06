# DMX node port/universe table — design

- **Date:** 2026-08-05
- **Author:** Claude Code, with Anthony
- **Status:** implemented 2026-08-05, verified on the rig — see Verification below
- **Scope:** Network tab only. The Devices tab and the Stardust output cards are
  explicitly out of scope and unchanged.

## Problem

Selecting a DMX node in the Network tab tells you its model, firmware and port
*count*, but not what any port is doing. The one universe-related panel —
`UNIVERSES OUTPUTTING` in `DeviceDetail` — is a flat chip row fed by
`vendorData.universesOutputting`, populated only by Stardust via Art-Net
discovery. For a Swisson or ACPD node it renders nothing at all.

So the question an operator actually asks at a node — *which universe is on
port 3?* — can only be answered by leaving the app, opening the node's own web
GUI, and reading its Status page.

The information is one HTTP GET away, and the app is already talking to these
devices for `/model/device` enrichment.

## Goals

1. Selecting a DMX node in the Network tab shows a per-port table: port number,
   universe, protocol, direction, status.
2. The table is correct *while someone is repatching the node*, not up to five
   minutes behind it.
3. When a node stops answering, the last known patch is shown and clearly
   labelled as stale rather than blanked or silently presented as current.
4. An enum value we have never observed is never given a guessed label.

## Non-goals

- Writing to nodes. Everything here is read-only. Changing a universe stays a
  job for the node's own GUI.
- Touching the Devices tab, the Stardust output cards, or the existing
  `UNIVERSES OUTPUTTING` chip row. Stardust reports a flat universe list with no
  port mapping; that panel stays exactly as it is and keeps serving it.
- Vendors that do not serve `/model/status`. Hog, Luminex and Netgear are out.
- Deriving port mapping from sACN traffic. The sACN listener sees universes and
  source names, never which physical XLR they leave by.

## What the hardware actually serves

> **Measured 2026-08-05 — `verified on actual gear`.** All findings below come
> from live GETs against the rig, not from documentation.

`http://<ip>/model/status` returns the Status page's contents as JSON. From the
XND-8 at `10.31.8.51`:

```json
{"modelName":"XND-8","locate":false,"longArtNetName":"SWISSON XND-8",
 "artNetMode":1,"addressDisplayMode":0,
 "ports":[{"status":3,"direction":1,"protocol":2,"universe":21},
          {"status":3,"direction":1,"protocol":2,"universe":42},
          {"status":3,"direction":1,"protocol":2,"universe":91},
          {"status":3,"direction":1,"protocol":2,"universe":104},
          {"status":3,"direction":1,"protocol":2,"universe":44},
          {"status":3,"direction":1,"protocol":2,"universe":41},
          {"status":3,"direction":1,"protocol":2,"universe":41},
          {"status":3,"direction":1,"protocol":2,"universe":1}]}
```

Array index is the port number, zero-based. Ports 1–4 read 21 / 42 / 91 / 104,
matching the GUI screenshot taken at the same moment.

**The ACPD PDXND-4-1 serves the identical contract**, four entries instead of
eight — confirmed against all 15 units (`10.9.15.101`–`.114` and `.121`). This
mirrors `/model/device`, which `_enrich_model_device_api` already shares between
the two vendors for exactly this reason.

> **Corrected 2026-08-05 after implementation.** This section originally said
> "one reader covers 16 devices", from a survey that had seen only one Swisson
> plus the ACPD rack. The first full sweep on the shipped code found **29
> nodes, 168 ports**: 13 × XND-8, 1 × **XND-4** (`10.31.2.46`, same contract,
> four ports — a model the survey never saw), and 15 × PDXND-4-1. The reader's
> coverage is nearly twice what was designed for, at no extra cost, because
> the contract is shared rather than per-model.

### Endpoints checked

| Path | Result |
|---|---|
| `/model/status` | 200 — the per-port array above. **The only source of port data.** |
| `/model/device` | 200 — already consumed by `_enrich_model_device_api` |
| `/model/network` | 200 — IP/link state, not needed here |
| `/model/port` | 200 but **useless**: ignores `?index=`, `?port=` and `?portIndex=`, returning the same single record every time (`protocol:1, universe:0`). Not a per-port endpoint. |
| `/model/dmx`, `/model/ports`, `/model/config` | 404 |

Note that `/model/port` reports `protocol:1` on a node whose every port is sACN,
so its fields are **not** interchangeable with those in `/model/status`. Do not
cross-reference the two.

### Enum decoding, and its limits

Every one of the **168 ports across all 29 reachable nodes reads
`status:3, direction:1, protocol:2`.** The rig offers no second sample of any of
the three fields. (The original survey said 68 ports across 16 nodes; the full
sweep after implementation raised the count without turning up a single new
code, so the conclusion below rests on more evidence than it did, not less.)
Confirmed meanings:

| Field | Code | Meaning | Evidence |
|---|---|---|---|
| `protocol` | 1 | Art-Net | operator-confirmed 2026-08-05; not observed on rig |
| `protocol` | 2 | sACN | observed on all 68 ports; GUI renders "sACN" |
| `direction` | 1 | Output | observed on all 68 ports; GUI renders "Output" |
| `status` | 3 | OK | observed on all 68 ports; GUI renders "OK" |

Everything else — input ports, disabled ports, no-signal ports — is **unknown**,
and the design treats it as unknown. An unrecognised code renders as the literal
string `code 5`, never an invented word.

This is deliberate. On a troubleshooting screen a confidently wrong status is
worse than a raw number, because the operator stops looking. The repo already
takes this line explicitly in the Starlink OUI comment in `vendors/__init__.py`.
When a real input or dead port is next seen on a rig, decoding it is a one-line
addition to the table below — and until then the raw code is itself the bug
report.

## Approach

Three options were weighed for freshness:

| | Approach | Verdict |
|---|---|---|
| **A** | Persist on the sweep, re-read live on selection | **Chosen** |
| **B** | Persist on the sweep only | Rejected — up to 5 min wrong |
| **C** | Live read only, no cache | Rejected — blank panel on an offline node |

`enrich_device` runs only in `_process_discovered_device`, i.e. on the full
discovery sweep every `DISCOVERY_INTERVAL = 300` seconds. The 20-second
keep-alive does not re-enrich. B therefore shows a stale universe for up to five
minutes after someone repatches a node — precisely the moment the panel is being
looked at, and the failure that would teach an operator to distrust it. C is
always true but shows nothing when a node is unreachable, discarding a last
known patch that is still useful. A gets both.

### Backend — the reader

`_read_model_status(ip) -> dict` in `backend/app/vendors/__init__.py`, merged
into the `_enrich_model_device_api` result so `swisson` and `acpd` both receive
it through the path they already share. It adds one key to `vendor_data`:

```json
"ports": [
  {"port": 1, "universe": 21, "protocol": "sACN", "direction": "Output", "status": "OK"},
  {"port": 2, "universe": 42, "protocol": "sACN", "direction": "Output", "status": "OK"}
]
```

`port` is the 1-based array index. Decoding happens here rather than in the
frontend: the vendors module is where vendor knowledge lives, and there must be
exactly one enum table to extend when a new code appears.

Failure behaviour matches the rest of `enrich_device`: on timeout, non-200 or
malformed JSON the key is **absent**, and `_process_discovered_device`'s existing
`if vendor_data:` guard leaves the previously stored value untouched. A single
missed poll must not erase a known patch.

### Backend — the live read

`GET /api/network/devices/<mac>/ports` in `network_routes.py`:

- Node answers → `{"ports": [...], "live": true}`
- Node does not answer → `{"ports": <stored vendor_data.ports>, "live": false,
  "asOf": <device.lastSeen>}`
- No stored ports and no answer → `{"ports": [], "live": false}`

Short timeout (3s, matching `_enrich_model_device_api`). The endpoint never
writes to the database — it is a read path, and a live value that disagrees with
the sweep is not evidence the sweep was wrong.

### Frontend

New `app/src/components/PortTable.jsx`. `NetworkMonitor.jsx` is already 716
lines carrying the sidebar, device list, detail pane and three modals; another
inline panel makes it worse, and this one has its own fetch lifecycle.

- Renders only when `device.vendorData?.ports?.length` — no empty box on a
  switch or a Hog.
- Placed above the `NOTES` panel in `DeviceDetail`, below the meta grid.
- On mount and on `device.macAddress` change: paint the cached rows immediately,
  fire the live fetch, replace on success.
- `live: false` shows a stale marker with the `asOf` time, using the existing
  `timeAgo` helper.
- Status cell is green only for exactly `OK`. Anything else, including a
  `code N`, renders neutral — we cannot claim a state is bad any more than we
  can claim it is good.
- Columns: Port | Universe | Protocol | Direction | Status. Universe is
  `tabular-nums`, consistent with the existing chip row.

### Free side effect

`NetworkLocation` snapshots already persist `vendor_data_at_time`
(`network_routes.py:257`). Once `ports` is in `vendor_data`, every saved location
captures the full port-to-universe patch of all 16 nodes with no extra work — a
record of what the rig was patched to at that venue.

## Testing

**Backend** (`backend/tests/test_vendors.py`, existing `requests` mocking
pattern):

- XND-8 payload above → 8 ports, `port` 1–8, universes in order.
- PDXND-4-1 payload → 4 ports.
- Unknown code (`status: 9`) → `"code 9"`, and the row is still emitted.
- Timeout / non-200 / malformed JSON → no `ports` key, no exception.
- `enrich_device` for both `swisson` and `acpd` reaches the reader.

**Route** (`backend/tests/`):

- Node answers → `live: true`.
- Node unreachable with stored ports → `live: false` plus `asOf`.
- Node unreachable with nothing stored → empty list, no 500.
- Unknown MAC → 404.

**Frontend** (`PortTable.test.jsx`):

- 8 cached rows render before the fetch resolves, then are replaced by live values.
- Renders nothing when the device has no `ports`.
- Stale marker appears on `live: false`.
- A `code N` status renders the raw string, not a blank cell.

## Verification

> **Run 2026-08-05 — `verified on actual gear`.**

- The reader was exercised against 8 real nodes directly, including the XND-4
  and one unreachable address (`10.0.0.95`), which correctly yielded `{}`.
- `GET /api/network/devices/28:36:38:C0:39:C0/ports` returned `live: true` with
  all 8 ports; the ACPD at `10.9.15.101` returned `live: true` with 4.
- A full discovery sweep populated `vendor_data.ports` on **29 nodes**.
- In the running app, the Swisson XND-8 detail pane rendered 8 rows —
  universes 21 / 42 / 91 / 104 / 44 / 41 / 41 / 1, matching the node's own web
  GUI — and the ACPD rendered 4. Status cells green, no stale banner, no
  console errors.
- Regression check: a Stardust unit still shows `UNIVERSES OUTPUTTING` with
  "None reported" and its Art-Net note, and renders **no** port table.

**One consequence worth knowing.** The panel renders only for a device that
already has `vendor_data.ports`, so immediately after deploying this, no node
shows a table until the next discovery sweep — up to 300 seconds, or one press
of **Scan Now**. This follows from painting the cached patch before the live
one, and is the intended trade: an operator never sees an empty box flash
before data arrives.

**The stale-backend trap this caught.** Before the restart, the running backend
predated these commits, so the new route 404'd into the SPA fallback while the
device itself answered fine on the same machine. The test suite was fully green
throughout. That gap between "the tests pass" and "the app can do it" is why
this verification step exists as a task rather than an afterthought.

## Open question, deliberately left open

The `status`, `direction` and non-sACN `protocol` codes are undecoded because
the rig has no example of them. This is recorded rather than resolved. The
`code N` rendering is what surfaces the answer the first time a port on any rig
is set to input, disabled, or loses signal — at which point one table entry
closes it.
