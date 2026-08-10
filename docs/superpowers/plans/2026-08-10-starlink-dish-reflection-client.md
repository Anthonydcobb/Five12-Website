# Starlink Dish Reflection Client Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Devices tab's Starlink panel show live dish telemetry, replacing a dependency that cannot be installed with a self-contained gRPC reflection client.

**Architecture:** A new module fetches the dish's own protobuf descriptors over gRPC server reflection, builds them into a descriptor pool at runtime, and calls `Device.Handle` with a request name drawn from a read-only allowlist. `StarlinkAdapter._real_status` keeps its contract and swaps its internals to use it.

**Tech Stack:** Python 3.12 (app interpreter), `grpcio` 1.83.0, `protobuf` 7.35.1, pytest. React 18 frontend, vitest.

**Spec:** `docs/superpowers/specs/2026-08-10-starlink-dish-reflection-client-design.md`

## Global Constraints

- **READ-ONLY. The client may only ever send `get_status` and `get_history`.** The dish's gRPC endpoint is **unauthenticated** and its `Request` oneof includes `reboot`, `dish_stow`, `factory_reset`, `dish_factory_reset`, `dish_inhibit_rf`, `software_update`, `set_sku` and `wifi_set_config`. On this rig the dish is the internet; an accidental `reboot` is a show-stopper. Task 1 pins this against the module's own source.
- The allowlist is checked **before a channel is opened**, so a bad name cannot reach the network.
- `StarlinkAdapter._real_status` keeps its signature, its `{'available': False, 'reason': ...}` failure shape, and **every key it already returns**. The panel must keep working untouched.
- Failure returns `{'available': False, 'reason': ...}` and never raises — the adapter is polled on a timer.
- Dish address is `192.168.100.1:9200` (`DISH_HOST`/`DISH_PORT`, already in the module).
- Do NOT install or vendor `starlink-grpc-tools`. It is not on PyPI.
- **Wi-Fi and router data are out of scope** — `wifi_get_clients` returns `UNIMPLEMENTED` on the dish.
- Do not change the simulator path, `ALERT_RULES`, `detect()`, or the adapter registry.
- Backend tests run from `C:\dev\Five12-TheApp\backend`. **Two interpreters:** plain `python` is 3.14 and does NOT have grpcio/protobuf; `C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe` does. Tests must pass on **both** — that means no test may require grpcio at import time.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/integrations/starlink_grpc_client.py` (create) | Reflection, descriptor pool, allowlist, `call()` |
| `backend/tests/test_starlink_grpc_client.py` (create) | Allowlist + safety pins + pool building |
| `backend/app/integrations/starlink.py` (modify) | `_real_status` uses the client; new mapped keys |
| `backend/tests/test_starlink_adapter.py` (create) | Payload mapping against a captured fixture |
| `backend/tests/fixtures/starlink_get_status.json` (create) | Verbatim captured dish payload |
| `backend/tests/fixtures/starlink_get_history.json` (create) | Verbatim captured dish payload |
| `app/src/pages/Devices.jsx` (modify) | Device-info line + software-update chip |

---

### Task 1: The reflection client

**Files:**
- Create: `backend/app/integrations/starlink_grpc_client.py`
- Test: `backend/tests/test_starlink_grpc_client.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `call(request_name, host='192.168.100.1', port=9200, timeout=10.0) -> dict` and `ALLOWED_REQUESTS: frozenset`. Task 2 imports both.

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_starlink_grpc_client.py`:

```python
"""Read-only gRPC client for the Starlink dish.

The dish serves an UNAUTHENTICATED gRPC endpoint on 192.168.100.1:9200 whose
Request oneof includes reboot, dish_stow, factory_reset, dish_inhibit_rf and
software_update. Anything that can reach the dish can issue them. On this rig
the dish carries the show's internet, so the client is restricted to an
explicit read allowlist and that restriction is pinned here.

These tests must pass on BOTH interpreters. Plain `python` is 3.14 and has
neither grpcio nor protobuf, so nothing here may import them at module scope.
"""

import importlib.util

import pytest

MODULE = 'app.integrations.starlink_grpc_client'

# Every mutating request name observed in the dish's own Request oneof on
# 2026-08-10. None may appear in the client's source.
MUTATING = (
    'reboot', 'dish_stow', 'factory_reset', 'dish_factory_reset',
    'dish_inhibit_rf', 'dish_inhibit_gps', 'software_update', 'set_sku',
    'wifi_set_config', 'dish_set_config', 'dish_set_emc', 'set_test_mode',
    'dish_clear_obstruction_map', 'set_trusted_keys',
)


def _client():
    import importlib
    return importlib.import_module(MODULE)


def test_the_allowlist_holds_only_reads():
    c = _client()
    assert c.ALLOWED_REQUESTS == frozenset({'get_status', 'get_history'})


def test_no_mutating_request_name_appears_in_the_source():
    """Asserted against the module's own text so that ADDING one fails the
    suite, rather than relying on nobody having called it during a test run.
    A reboot issued at the dish takes the show's internet with it."""
    import inspect
    src = inspect.getsource(_client())
    for name in MUTATING:
        assert name not in src, f'mutating request {name!r} present in client'


def test_a_disallowed_name_is_refused_before_any_channel_opens(monkeypatch):
    """The check must come first. If it happened after connecting, a typo
    would already have reached a device that accepts factory_reset."""
    c = _client()
    opened = []
    monkeypatch.setattr(c, '_channel', lambda host, port: opened.append((host, port)))

    with pytest.raises(ValueError) as exc:
        c.call('reboot')

    assert 'not allowed' in str(exc.value).lower()
    assert opened == [], 'a channel was opened for a disallowed request'


def test_a_disallowed_name_is_refused_even_when_it_looks_like_a_read(monkeypatch):
    c = _client()
    monkeypatch.setattr(c, '_channel', lambda host, port: pytest.fail('channel opened'))
    with pytest.raises(ValueError):
        c.call('get_device_info')      # a real RPC, deliberately not allowlisted


def test_varint_round_trips_without_protobuf_internals():
    """The reflection request is hand-encoded. Earlier drafts reached into
    google.protobuf.internal.encoder/decoder, which are private and move
    between releases; these two helpers are ours and are six lines each."""
    c = _client()
    for n in (0, 1, 127, 128, 300, 5307, 1 << 21):
        buf = c._varint(n)
        value, offset = c._read_varint(buf, 0)
        assert value == n and offset == len(buf)


def test_the_reflection_request_uses_field_four_for_a_symbol():
    """ServerReflectionRequest: file_by_filename is 3, file_containing_symbol
    is 4, list_services is 7. Getting this wrong makes the dish answer
    `INTERNAL: failed to unmarshal the received message`, which reads like a
    transport fault rather than a malformed request — it cost a round trip."""
    c = _client()
    req = c._symbol_request('SpaceX.API.Device.Device')
    assert req[0] == (4 << 3) | 2          # tag: field 4, length-delimited
    assert req.endswith(b'SpaceX.API.Device.Device')
```

- [x] **Step 2: Run the tests to verify they fail**

From `C:\dev\Five12-TheApp\backend`:

```bash
python -m pytest tests/test_starlink_grpc_client.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.integrations.starlink_grpc_client'`.

- [x] **Step 3: Write the client**

Create `backend/app/integrations/starlink_grpc_client.py`:

```python
"""Read-only gRPC client for the Starlink dish, via server reflection.

[VERIFIED 2026-08-10 on the rig] The dish at 192.168.100.1:9200 enables gRPC
server reflection. One `file_containing_symbol` lookup for
`SpaceX.API.Device.Device` returns the full transitive descriptor set — 19
files — so the schema is built at runtime and no generated stubs are shipped
or go stale against dish firmware.

This exists instead of `starlink-grpc-tools`, which the adapter used to import
and tell operators to `pip install`. That package is not on PyPI (pip: "from
versions: none"); it is a GitHub repository of scripts.

SAFETY. The endpoint is UNAUTHENTICATED and its Request oneof carries
destructive commands alongside the reads. Only names in ALLOWED_REQUESTS are
ever sent, and the check happens before a channel is opened. On this rig the
dish is the show's internet.
"""

import logging
import threading

DISH_HOST = '192.168.100.1'
DISH_PORT = 9200

#: The only requests this application will ever send. Both verified to return
#: real data on 2026-08-10. Widening this set is a safety decision, not a
#: convenience one — see the module docstring.
ALLOWED_REQUESTS = frozenset({'get_status', 'get_history'})

_SERVICE_SYMBOL = 'SpaceX.API.Device.Device'
_REFLECTION_METHOD = '/grpc.reflection.v1alpha.ServerReflection/ServerReflectionInfo'
_HANDLE_METHOD = '/SpaceX.API.Device.Device/Handle'

log = logging.getLogger(__name__)

# Descriptors are cached per process: the dish's schema does not change between
# polls, and re-fetching 19 files every cycle would load a device that is also
# carrying the show's internet.
_cache_lock = threading.Lock()
_cached = {}          # (host, port) -> (RequestClass, ResponseClass)


def _varint(n):
    """Minimal protobuf varint encoder.

    Ours on purpose. Earlier drafts used google.protobuf.internal.encoder,
    which is private API and has moved between releases; this is six lines and
    cannot break under a protobuf upgrade.
    """
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _read_varint(buf, i):
    """Returns (value, next_offset)."""
    result = shift = 0
    while True:
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, i
        shift += 7


def _symbol_request(symbol):
    """ServerReflectionRequest{ file_containing_symbol: symbol }.

    Field numbers: file_by_filename = 3, file_containing_symbol = 4,
    list_services = 7. A wrong number produces `INTERNAL: failed to unmarshal
    the received message` from the dish, which reads like a transport problem.
    """
    body = symbol.encode()
    return bytes(bytearray(_varint((4 << 3) | 2)) + _varint(len(body)) + body)


def _file_descriptors(payload):
    """Pull FileDescriptorProto bytes out of a ServerReflectionResponse.

    field 4 = FileDescriptorResponse, whose field 1 repeats the protos.
    """
    out, i = [], 0
    while i < len(payload):
        tag, i = _read_varint(payload, i)
        field, wire = tag >> 3, tag & 7
        if wire == 2:
            length, i = _read_varint(payload, i)
            chunk, i = payload[i:i + length], i + length
            if field == 4:
                j = 0
                while j < len(chunk):
                    inner, j = _read_varint(chunk, j)
                    if inner & 7 == 2:
                        ln, j = _read_varint(chunk, j)
                        out.append(chunk[j:j + ln])
                        j += ln
                    else:
                        _, j = _read_varint(chunk, j)
        elif wire == 0:
            _, i = _read_varint(payload, i)
        else:
            break
    return out


def _channel(host, port):
    import grpc
    return grpc.insecure_channel(f'{host}:{port}')


def _message_classes(channel):
    """Fetch the dish's descriptors and return (RequestClass, ResponseClass)."""
    from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

    raw = lambda b: b          # noqa: E731 — reflection frames are opaque here
    reflect = channel.stream_stream(
        _REFLECTION_METHOD, request_serializer=raw, response_deserializer=raw)

    blobs = []
    for response in reflect(iter([_symbol_request(_SERVICE_SYMBOL)]), timeout=15):
        blobs = _file_descriptors(response)
        break

    protos = {}
    for blob in blobs:
        fdp = descriptor_pb2.FileDescriptorProto()
        fdp.ParseFromString(blob)
        protos[fdp.name] = fdp

    # Dependency order matters: DescriptorPool.Add raises on a missing import.
    pool, added = descriptor_pool.DescriptorPool(), set()

    def add(name):
        if name in added or name not in protos:
            return
        for dep in protos[name].dependency:
            add(dep)
        pool.Add(protos[name])
        added.add(name)

    for name in list(protos):
        add(name)

    return (
        message_factory.GetMessageClass(
            pool.FindMessageTypeByName('SpaceX.API.Device.Request')),
        message_factory.GetMessageClass(
            pool.FindMessageTypeByName('SpaceX.API.Device.Response')),
    )


def call(request_name, host=DISH_HOST, port=DISH_PORT, timeout=10.0):
    """Send one allowlisted read to the dish and return the response as a dict.

    Raises ValueError for a name outside ALLOWED_REQUESTS, before any network
    activity. Any other failure propagates to the caller, which is expected to
    convert it into an unavailable status rather than let it escape.
    """
    if request_name not in ALLOWED_REQUESTS:
        raise ValueError(
            f'{request_name!r} is not allowed; this client sends only '
            f'{sorted(ALLOWED_REQUESTS)}')

    from google.protobuf import json_format

    channel = _channel(host, port)
    key = (host, port)
    with _cache_lock:
        classes = _cached.get(key)
    if classes is None:
        classes = _message_classes(channel)
        with _cache_lock:
            _cached[key] = classes
    request_cls, response_cls = classes

    handle = channel.unary_unary(
        _HANDLE_METHOD,
        request_serializer=lambda m: m.SerializeToString(),
        response_deserializer=response_cls.FromString)

    message = request_cls()
    getattr(message, request_name).SetInParent()
    return json_format.MessageToDict(
        handle(message, timeout=timeout), preserving_proto_field_name=True)
```

- [x] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/test_starlink_grpc_client.py -v
"C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe" -m pytest tests/test_starlink_grpc_client.py -v
```

Expected: 6 PASS on **both**. The 3.14 interpreter has no grpcio; nothing in the tests or at the module's import scope may need it — `grpc` and `google.protobuf` are imported inside functions for exactly this reason.

- [x] **Step 5: Commit**

```bash
git add backend/app/integrations/starlink_grpc_client.py backend/tests/test_starlink_grpc_client.py
git commit -m "feat(starlink): read-only gRPC client via server reflection"
```

---

### Task 2: Capture real payloads and rewrite the adapter

**Files:**
- Create: `backend/tests/fixtures/starlink_get_status.json`, `backend/tests/fixtures/starlink_get_history.json`
- Modify: `backend/app/integrations/starlink.py` (module docstring, `_real_status`)
- Test: `backend/tests/test_starlink_adapter.py` (create)

**Interfaces:**
- Consumes: `starlink_grpc_client.call(name) -> dict`, `ALLOWED_REQUESTS`.
- Produces: `_real_status()` returning every key the panel already reads, plus `hardwareVersion`, `softwareVersion`, `bootcount`, `softwareUpdateState`, `gpsValid`, `gpsSats`, `ethSpeedMbps`, `mobilityClass`, `disablementCode`, `obstructionValidS`. Task 3 renders the new ones.

- [x] **Step 1: Capture the real payloads — and settle one open question**

Run this from `C:\dev\Five12-TheApp\backend` with the **app interpreter**:

```bash
"C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe" -c "import sys,json; sys.path.insert(0,'.'); from app.integrations import starlink_grpc_client as c; json.dump(c.call('get_status'), open('tests/fixtures/starlink_get_status.json','w'), indent=1); json.dump(c.call('get_history'), open('tests/fixtures/starlink_get_history.json','w'), indent=1); print('captured')"
```

Create `backend/tests/fixtures/` first if it does not exist.

**Then read `starlink_get_status.json` and answer this before writing any mapping code:** the old implementation did `state = g_status.get('state')` and set `online = (state == 'CONNECTED')`. **No `state` field was seen in the sampled payload** — the sample was truncated at 1400 characters during design and this was never resolved. Determine from the captured file which field actually carries connection state. Candidates observed: `ready_states` (all booleans), `disablement_code` (`OKAY`), `is_snr_above_noise_floor`, `outage` if present.

If no single field carries it, derive `online` from `disablement_code == 'OKAY'` and all `ready_states` values being true, and **set `state` to a short string you can justify from the payload** — do not invent `'CONNECTED'` if the dish never says it. Record what you found in your report. The panel prints `status.state` verbatim next to the online dot, so this is operator-facing.

- [x] **Step 2: Write the failing tests**

Create `backend/tests/test_starlink_adapter.py`:

```python
"""Adapter mapping, against payloads captured verbatim from the dish.

The fixtures are real responses, not composed ones. A Starlink firmware update
can move fields, which is why every read is a .get() with a default and why
these tests exist: they say what the panel will show for a payload we have
actually seen.
"""

import json
import pathlib
from unittest.mock import patch

import pytest

FIXTURES = pathlib.Path(__file__).parent / 'fixtures'
STATUS = json.loads((FIXTURES / 'starlink_get_status.json').read_text())
HISTORY = json.loads((FIXTURES / 'starlink_get_history.json').read_text())


def _adapter():
    from app.integrations.starlink import StarlinkAdapter
    return StarlinkAdapter()


def _fake_call(name, **kw):
    return {'get_status': STATUS, 'get_history': HISTORY}[name]


def test_the_captured_status_maps_to_every_key_the_panel_reads():
    with patch('app.integrations.starlink_grpc_client.call', side_effect=_fake_call):
        s = _adapter()._real_status()

    assert s['available'] is True
    for key in ('state', 'online', 'uptimeS', 'downMbps', 'upMbps', 'latencyMs',
                'obstructionPct', 'snrAboveNoiseFloor', 'hardwareAlerts',
                'outagesLastHour', 'outageLog'):
        assert key in s, f'panel reads {key} and the adapter did not supply it'


def test_throughput_is_reported_in_megabits_not_bits():
    """The dish reports bps; the panel's tiles say Mbps. A missing conversion
    would render 1239517.5 under a label reading Mbps."""
    with patch('app.integrations.starlink_grpc_client.call', side_effect=_fake_call):
        s = _adapter()._real_status()

    raw = STATUS['dish_get_status']['downlink_throughput_bps']
    assert s['downMbps'] == pytest.approx(raw / 1e6, rel=1e-3)
    assert s['downMbps'] < 10_000        # a sanity bound no real link exceeds


def test_obstruction_is_a_percentage_not_a_fraction():
    """The dish reports fraction_obstructed 0..1; the tile's unit is '%'. On
    the captured payload the true value is around 52%, and reporting 0.52
    under a % label would read as a healthy dish."""
    with patch('app.integrations.starlink_grpc_client.call', side_effect=_fake_call):
        s = _adapter()._real_status()

    frac = STATUS['dish_get_status']['obstruction_stats']['fraction_obstructed']
    assert s['obstructionPct'] == pytest.approx(frac * 100, rel=1e-3)


def test_the_outage_tiles_are_no_longer_hardcoded_empty():
    """These two were `None` and `[]` behind a `needs history_data(); v2`
    comment, so the panel's outage tile and log have always been blank — and
    ALERT_RULES has an outagesLastHour rule that could never fire."""
    with patch('app.integrations.starlink_grpc_client.call', side_effect=_fake_call):
        s = _adapter()._real_status()

    assert s['outagesLastHour'] is not None
    assert isinstance(s['outageLog'], list)
    if s['outageLog']:
        entry = s['outageLog'][0]
        assert set(entry) >= {'ts', 'durationS', 'cause'}
        assert isinstance(entry['durationS'], (int, float))


def test_device_info_reaches_the_panel():
    with patch('app.integrations.starlink_grpc_client.call', side_effect=_fake_call):
        s = _adapter()._real_status()

    info = STATUS['dish_get_status']['device_info']
    assert s['hardwareVersion'] == info['hardware_version']
    assert s['softwareVersion'] == info['software_version']


def test_an_unreachable_dish_is_unavailable_not_an_exception():
    """The adapter is polled on a timer; a raise here would surface as a 500
    on every cycle rather than a panel that says the dish is not answering."""
    with patch('app.integrations.starlink_grpc_client.call',
               side_effect=OSError('dish unreachable')):
        s = _adapter()._real_status()

    assert s['available'] is False
    assert 'reason' in s


def test_a_history_failure_does_not_lose_the_status():
    """Two independent calls. If get_history fails, the dish's live state is
    still worth showing — half a read must not cost the other half."""
    def only_status(name, **kw):
        if name == 'get_history':
            raise OSError('timeout')
        return STATUS

    with patch('app.integrations.starlink_grpc_client.call', side_effect=only_status):
        s = _adapter()._real_status()

    assert s['available'] is True
    assert s['latencyMs'] is not None
    assert s['outagesLastHour'] is None      # honest about what is missing


def test_the_dependency_message_names_installable_packages():
    """The old text told operators to `pip install starlink-grpc-tools`, which
    does not exist on PyPI. Whatever replaces it must be runnable."""
    import inspect
    from app.integrations import starlink
    src = inspect.getsource(starlink)
    assert 'starlink-grpc-tools' not in src
    assert 'starlink_grpc' not in src.replace('starlink_grpc_client', '')
```

- [x] **Step 3: Run the tests to verify they fail**

```bash
python -m pytest tests/test_starlink_adapter.py -v
```

Expected: FAIL — the adapter still imports `starlink_grpc` and returns the not-installed reason, so the mapping assertions fail and `test_the_dependency_message_names_installable_packages` fails on the source scan.

- [x] **Step 4: Rewrite `_real_status` and the module docstring**

In `backend/app/integrations/starlink.py`, replace the `_real_status` method. Map from the **captured fixture's actual field names**, using the `state`/`online` decision made in Step 1:

```python
    def _real_status(self):
        """Live dish telemetry over gRPC reflection.

        Two independent allowlisted reads. get_history failing must not cost
        us get_status: the dish's current state is worth showing even when the
        ring buffer read times out.
        """
        from . import starlink_grpc_client as client

        try:
            payload = client.call('get_status')
        except Exception as exc:  # noqa: BLE001 — offline, grpc errors, proto drift
            return {'available': False, 'reason': f'dish unreachable: {exc}'}

        dish = payload.get('dish_get_status') or {}
        info = dish.get('device_info') or {}
        state_info = dish.get('device_state') or {}
        obstruction = dish.get('obstruction_stats') or {}
        gps = dish.get('gps_stats') or {}
        alerts = dish.get('alerts') or {}

        def num(value, scale=1.0):
            return round(value * scale, 2) if isinstance(value, (int, float)) else None

        def as_int(value):
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        status = {
            'available': True,
            'source': 'grpc-reflection',
            # CONNECTION STATE — verify this against the captured fixture
            # before accepting it. The old code read a `state` field and
            # compared it to 'CONNECTED'; no such field appeared in the
            # sampled payload. The derivation below uses fields that WERE
            # observed. If the fixture turns out to carry a real state field,
            # use it instead and say so in your report. Do not reintroduce
            # 'CONNECTED' unless the dish actually emits it.
            'state': (dish.get('disablement_code') or 'UNKNOWN'),
            'online': (dish.get('disablement_code') == 'OKAY'
                       and bool(dish.get('ready_states'))
                       and all((dish.get('ready_states') or {}).values())),
            'uptimeS': as_int(state_info.get('uptime_s')),
            'downMbps': num(dish.get('downlink_throughput_bps'), 1 / 1e6),
            'upMbps': num(dish.get('uplink_throughput_bps'), 1 / 1e6),
            'latencyMs': num(dish.get('pop_ping_latency_ms')),
            'snrAboveNoiseFloor': dish.get('is_snr_above_noise_floor'),
            'obstructionPct': num(obstruction.get('fraction_obstructed'), 100),
            'obstructionValidS': num(obstruction.get('valid_s')),
            'stowed': bool(dish.get('stowed')),
            'hardwareAlerts': [k for k, v in alerts.items() if v],
            'hardwareVersion': info.get('hardware_version'),
            'softwareVersion': info.get('software_version'),
            'bootcount': as_int(info.get('bootcount')),
            'softwareUpdateState': dish.get('software_update_state'),
            'gpsValid': gps.get('gps_valid'),
            'gpsSats': as_int(gps.get('gps_sats')),
            'ethSpeedMbps': as_int(dish.get('eth_speed_mbps')),
            'mobilityClass': dish.get('mobility_class'),
            'disablementCode': dish.get('disablement_code'),
            'outagesLastHour': None,
            'outageLog': [],
        }

        # Independent: the panel is more useful with live state and no history
        # than with neither.
        try:
            history = (client.call('get_history') or {}).get('dish_get_history') or {}
        except Exception as exc:  # noqa: BLE001
            log.warning('starlink get_history failed: %s', exc)
            return status

        events = ((history.get('event_log') or {}).get('events')) or []
        outages = []
        for event in events:
            start_ns = as_int(event.get('start_timestamp_ns'))
            duration_ns = as_int(event.get('duration_ns'))
            if start_ns is None:
                continue
            outages.append({
                'ts': start_ns / 1e9,
                'durationS': round(duration_ns / 1e9, 1) if duration_ns else 0,
                'cause': (event.get('reason') or '')
                         .replace('EVENT_REASON_OUTAGE_', '').replace('_', ' ').title()
                         or 'Unknown',
                'severity': event.get('severity'),
            })
        outages.sort(key=lambda o: o['ts'], reverse=True)

        cutoff = time.time() - 3600
        status['outageLog'] = outages
        status['outagesLastHour'] = sum(1 for o in outages if o['ts'] >= cutoff)
        return status
```

Add `import logging` and `log = logging.getLogger(__name__)` near the top if absent.

Then rewrite the module docstring's dependency claim. The current text says
`starlink-grpc-tools ("pip install starlink-grpc-tools" -> module starlink_grpc)`.
Replace it with an accurate statement: telemetry comes from
`starlink_grpc_client`, which needs `grpcio` and `protobuf` — both on PyPI and
both installed on this rig (1.83.0 / 7.35.1).

- [x] **Step 5: Run the tests to verify they pass**

```bash
python -m pytest tests/test_starlink_adapter.py -v
"C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe" -m pytest tests/test_starlink_adapter.py -v
```

Expected: 8 PASS on both.

- [x] **Step 6: Run the whole backend suite**

```bash
python -m pytest tests/ -q
```

Expected: no new failures.

- [x] **Step 7: Commit**

```bash
git add backend/app/integrations/starlink.py backend/tests/test_starlink_adapter.py backend/tests/fixtures/
git commit -m "feat(starlink): map live dish telemetry, fill the outage tiles"
```

---

### Task 3: Panel additions

**Files:**
- Modify: `app/src/pages/Devices.jsx` (`StarlinkPanel`)

**Interfaces:**
- Consumes: the adapter keys added in Task 2.
- Produces: no new exports.

- [x] **Step 1: Note why this task has no unit test**

`StarlinkPanel` is not exported from `Devices.jsx`, and `Devices.jsx` has no test file. Exporting a component solely so a test can reach it changes the module's surface to serve the test rather than the app, and standing up a harness for one presentational panel buys little: the additions here are guarded field renders with no logic.

This task is therefore verified by the build plus Task 4's on-screen check. Record that reasoning in your report so it reads as a decision rather than an omission — and if you disagree, say so rather than quietly adding an export.

- [x] **Step 2: Add the device-info line and update chip**

In `app/src/pages/Devices.jsx`, inside `StarlinkPanel`, immediately after the
existing `<AlertChips alerts={status.alerts} />` line, add:

```jsx
      {status.softwareUpdateState === 'REBOOT_REQUIRED' && (
        <div className="text-[10px] font-mono text-warn">
          ⚠ software update installed — dish reboot required
        </div>
      )}
```

And immediately before the closing `</div>` of the panel's outer
`<div className="space-y-3">`, add:

```jsx
      <div className="text-[9px] font-mono text-text-muted flex gap-3 flex-wrap">
        {status.hardwareVersion && <span>hw {status.hardwareVersion}</span>}
        {status.softwareVersion && <span>sw {status.softwareVersion}</span>}
        {status.bootcount != null && <span>boots {status.bootcount}</span>}
        {status.gpsValid != null && (
          <span>gps {status.gpsValid ? `${status.gpsSats ?? '?'} sats` : 'invalid'}</span>
        )}
        {status.ethSpeedMbps != null && <span>eth {status.ethSpeedMbps} Mbps</span>}
        {status.mobilityClass && <span>{status.mobilityClass.toLowerCase()}</span>}
      </div>
```

Every field is guarded, so a dish on older firmware that omits any of them
renders a shorter line rather than blanks or `undefined`.

- [x] **Step 3: Build**

From `C:\dev\Five12-TheApp\app`:

```bash
npm run build
```

Expected: `✓ built`.

- [x] **Step 4: Run the frontend suite for regressions**

```bash
npm test
```

Expected: no new failures.

- [x] **Step 5: Commit**

```bash
git add app/src/pages/Devices.jsx
git commit -m "feat(starlink): show device info and update state on the panel"
```

---

### Task 4: Verify on the actual dish

Tests prove the mapping. They cannot prove the running backend can reach the dish, and on this branch's sibling features that gap has caught a stale backend twice.

**Files:**
- Modify: `docs/superpowers/specs/2026-08-10-starlink-dish-reflection-client-design.md` (status + Verification section)

- [ ] **Step 1: Confirm the client works from this machine**

```bash
cd C:\dev\Five12-TheApp\backend && "C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe" -c "import sys; sys.path.insert(0,'.'); from app.integrations.starlink import StarlinkAdapter; s=StarlinkAdapter()._real_status(); print({k: s[k] for k in ('available','state','online','latencyMs','obstructionPct','outagesLastHour','softwareUpdateState')})"
```

Expected: `available: True` and a plausible obstruction percentage. At design time the dish read ~52% obstructed with `REBOOT_REQUIRED`.

- [ ] **Step 2: Restart the backend**

It will predate these commits. **Ask Anthony first — it is a live rig.** The command `start.ps1` uses:

```
$env:FIVE12_BLE_TOOLS='1'; $env:FIVE12_BLE_WRITE='1'; cd backend;
& "C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe" -m flask run --port 5000 --no-reload
```

- [ ] **Step 3: Confirm the API serves it**

```bash
curl -s http://localhost:5000/api/devices/starlink/status
```

Expected: `"available": true` with the mapped keys. If it says the package is not installed, the backend is stale.

- [ ] **Step 4: Confirm on screen**

Open the Devices tab, Starlink panel. Expect: state and uptime, the tiles populated, **the obstruction tile in warn colour** (it is over the 5% rule), an outage count and log with readable causes, the device-info line, and the reboot-required chip if the dish still reports it.

- [ ] **Step 5: Confirm nothing else moved**

The other Devices tabs (Bolero, Stardust, Cintenna, Astera) still render. The Network tab's DMX and switch tables are unaffected.

- [ ] **Step 6: Update the spec and commit**

Set the status line to `implemented 2026-08-10`, add a Verification section recording what steps 1 and 4 actually showed, and commit.

---

## Notes for the implementer

- **Never widen the allowlist casually.** `ALLOWED_REQUESTS` is a safety boundary, not a convenience. The dish accepts `reboot` and `factory_reset` from anyone who can reach it, and on this rig it carries the show's internet.
- **The `state`/`online` question in Task 2 Step 1 is genuinely open.** It was not resolved at design time because the sampled payload was truncated. Resolve it from the captured fixture and say what you found — do not carry `'CONNECTED'` over from the old code on faith.
- **Two interpreters.** Plain `python` is 3.14 without grpcio; the app runs 3.12 with it. Import `grpc` and `google.protobuf` inside functions, never at module scope, or the 3.14 suite breaks on collection.
- **Fixtures are captured, not composed.** A test asserting a live dish still reports a given obstruction percentage will fail on a clear day.
