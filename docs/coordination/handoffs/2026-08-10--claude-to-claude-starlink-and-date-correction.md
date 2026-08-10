# Handoff — Starlink dish client (mid-flight) + a date correction to make

- **Date:** 2026-08-10
- **From:** Claude Code session of 2026-08-10
- **To:** the next session
- **Branch:** `spec/starlink-dish-reflection`, rebased onto `main` at `1e41f9c`
- **State:** 3 commits, working tree clean, suites green

## Read this first

Two things are outstanding that are *not* the Starlink feature, and one of
them is an error in already-merged code. Do those before adding features.

### 1. Dates are wrong in merged, pushed work — correct them

The session that produced the DMX and GigaCore features believed the date was
**2026-08-05 / 2026-08-06**. It was **2026-08-10** throughout. The
measurements in those documents are real and were taken on the rig; only the
dates on them are wrong.

Affected, and now on `main`:

- `docs/superpowers/specs/2026-08-05-dmx-node-port-universes-design.md`
- `docs/superpowers/plans/2026-08-05-dmx-node-port-universes.md`
- `docs/superpowers/specs/2026-08-06-gigacore-port-device-map-design.md`
- `docs/superpowers/plans/2026-08-06-gigacore-port-device-map.md`
- `docs/superpowers/specs/2026-08-06-starlink-dish-reflection-client-design.md`
- `docs/superpowers/plans/2026-08-06-starlink-dish-reflection-client.md`
- **In code**, which matters most, because this repo treats a dated
  verification claim as evidence:
  - `backend/app/vendors/__init__.py` — `[VERIFIED 2026-08-06] against five
    GigaCore12s, ~2s each`, and the `/model/status` enum comment's
    `[VERIFIED 2026-08-05] all 68 ports…`
  - `backend/tests/test_switch_ports.py`, `test_switch_lookup.py`,
    `test_node_config_routes.py` — docstrings citing 2026-08-06
  - `backend/app/integrations/starlink_grpc_client.py` — `[VERIFIED 2026-08-06
    on the rig]`

Renaming the spec/plan files changes paths other documents reference; grep for
the old names before renaming, or leave filenames and correct only the
in-document dates. **Correcting the in-code `[VERIFIED]` dates is the part
that is not optional.**

### 2. Task 1 of the Starlink plan has unfixed review findings

`backend/app/integrations/starlink_grpc_client.py` is committed and its six
tests pass on both interpreters, but a review raised four Importants that were
never fixed. The safety boundary was **approved** — allowlist checked first,
`_channel()` the single choke point, no bypass path, and the source-scan and
ordering tests were confirmed meaningful, not vacuous. These are reliability
gaps around it:

1. **Every `call()` opens a gRPC channel it never closes**, cache hit or not —
   `channel = _channel(host, port)` runs unconditionally *before* the cache
   lookup, and nothing closes it. Once the panel polls this, every poll builds
   and tears down a channel against the dish that carries the show's internet.
   Fix: open once, close deterministically (`with` or try/finally), and not
   before it is needed.
2. **Cold-cache race** — `_cache_lock` guards only the dict get/set; the
   19-file reflection fetch runs outside it, so two concurrent callers both
   hit the dish at startup. Fix: make the fetch atomic. Preserve the existing
   good property that a *failed* fetch leaves the cache empty rather than
   poisoning it.
3. **Unknown wire type silently truncates** — `_file_descriptors` hits
   `else: break` for wire types 1/3/4/5, abandoning the rest of the payload.
   The failure then surfaces later as an opaque "message type not found".
   Fix: raise a specific malformed-reflection error naming the wire type and
   offset; give it a module-level exception class.
4. **A stub would pass all six tests.** Nothing feeds a synthetic
   `ServerReflectionResponse` through `_file_descriptors`, and nothing
   exercises `call()`'s happy path with a fake channel. This is the most
   important gap: the hand-rolled binary parser is entirely unverified in CI.

Minor, same review: `_read_varint` raises a bare `IndexError` on a truncated
buffer; `_file_descriptors` slices without checking `length` against the
remaining buffer; `test_starlink_grpc_client.py` imports `importlib.util`
unused. `_message_classes` breaking after the first stream response is
**correct** (one request, one response) but reads as an unexamined assumption
— add a comment rather than changing it.

## Starlink: what is done and what remains

Plan: `docs/superpowers/plans/2026-08-06-starlink-dish-reflection-client.md`
Spec: `docs/superpowers/specs/2026-08-06-starlink-dish-reflection-client-design.md`

- **Task 1 — DONE** (`e7c1799`), findings above unfixed.
- **Task 2 — not started.** Capture real payloads to
  `backend/tests/fixtures/`, rewrite `StarlinkAdapter._real_status` onto the
  client, fill the outage tiles from `get_history`.
- **Task 3 — not started.** Two guarded additions to `StarlinkPanel` in
  `app/src/pages/Devices.jsx`.
- **Task 4 — not started.** Verify against the dish; needs a backend restart,
  which is Anthony's call because the rig is live.

### The open question Task 2 must settle

The old adapter did `state = g_status.get('state')` and
`online = (state == 'CONNECTED')`. **No `state` field appeared in the sampled
payload** — the sample was truncated at 1400 characters during design and this
was never resolved. Task 2 Step 1 captures the full payload and resolves it
from the fixture. The plan supplies a derivation from fields that *were*
observed (`disablement_code == 'OKAY'` plus all `ready_states` true) and
**forbids reintroducing `'CONNECTED'` on faith**. The panel prints
`status.state` verbatim next to the online dot, so this is operator-facing.

## Verified facts — do not re-derive these

Measured on the rig 2026-08-10:

- The old adapter's advice was impossible: **`starlink-grpc-tools` is not on
  PyPI** (`pip`: "from versions: none"). It is a GitHub repo of scripts.
- **Dish gRPC reflection works.** One `file_containing_symbol` lookup for
  `SpaceX.API.Device.Device` returns the full transitive descriptor set — 19
  files. `ServerReflectionRequest` field numbers: `file_by_filename` **3**,
  `file_containing_symbol` **4**, `list_services` **7**. A wrong number makes
  the dish answer `INTERNAL: failed to unmarshal the received message`, which
  reads like a transport fault.
- Descriptors must enter the pool in **dependency order** or `Add` raises.
- `get_status` and `get_history` both return real data. `get_device_info` is
  redundant — `get_status` already carries the same `device_info` block.
- `get_history` gives `outages` (32 entries at capture), 900-sample rings, and
  an `event_log.events` list whose `severity` / `reason` /
  `start_timestamp_ns` / `duration_ns` map directly onto the panel's existing
  `cause` / `ts` / `durationS` shape.
- Live sample: **51.9% obstructed**, `software_update_state: REBOOT_REQUIRED`,
  `alerts: {install_pending: true}`, latency 19.4 ms, 12 GPS sats,
  `eth_speed_mbps` 1000, `mobility_class` MOBILE.
- **Wi-Fi is not available from the dish.** `wifi_get_clients` →
  `UNIMPLEMENTED`. The router at `192.168.1.1` answers **every** HTTP path —
  including `/definitely/not/a/real/endpoint` — with the identical 5307-byte
  `index.html`, and its gRPC port 9200 is closed. Anthony asked for Wi-Fi
  info; it is out of scope until that endpoint is found, and this is recorded
  as the spec's open question. **Do not design against `UNIMPLEMENTED`.**
- The router's LAN is `192.168.1.0/24` — the same range as the app's
  configured "Bolero" subnet. Not this feature's problem, but it means the
  Bolero antennas and a Starlink-connected laptop look like one network.

## Environment

- **Dependencies installed this session, app interpreter only:** `grpcio`
  1.83.0 and `protobuf` 7.35.1, both from PyPI. They are **not** in
  `backend/requirements.txt` — decide whether they should be.
- **Two interpreters, and this has bitten twice.** Plain `python` is 3.14 and
  has *neither* package; the app runs
  `C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe`, which
  has both. `grpc` and `google.protobuf` are therefore imported **inside
  functions**, never at module scope. Any new test must pass on **both**.
- Suites at handoff: **783 passed, 7 skipped on both interpreters.**

## Working practices worth carrying forward

- **This checkout is shared.** On 2026-08-10 Anthony was building the NETGEAR
  M4250 snapshot feature in a second window on the same working directory. It
  moved the checkout to `main` mid-flight, which made a subagent's target
  files vanish and correctly halted it. Check `git rev-parse --abbrev-ref
  HEAD` before dispatching agents, and prefer a worktree if parallel work is
  expected. The Starlink branch was rebased onto the resulting `main`; git
  skipped the duplicated Preflight commit by patch-id on its own.
- **Probe before designing.** Every expensive defect this session came from
  code written against an unverified contract: the GigaCore read and write,
  the Swisson read and write, and the `starlink-grpc-tools` install advice —
  four separate paths, none of which could ever have worked. A single control
  request (a path that certainly does not exist) exposed two of them.
- **The dish endpoint is unauthenticated** and accepts `reboot`, `dish_stow`,
  `factory_reset`, `dish_inhibit_rf`, `software_update`, `wifi_set_config`.
  The allowlist is a safety boundary, not a convenience. On this rig the dish
  is the internet.

## Cost

This session ran to roughly **$740**, most of it in the full
spec → plan → subagent → review pipeline across three features. The Starlink
discovery is done and written down here, so the remaining work is the cheap
half. Anthony was given the running figure at each decision point and chose
the full pipeline each time; ask before assuming that still holds.
