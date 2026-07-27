# Cintenna BLE — Read-Only Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Cintennas tab to the Devices page that passively discovers nearby LumenRadio TimoTwo radios over Bluetooth and shows their connected read-only status, with no capability to write to a radio.

**Architecture:** A daemon thread owns a `bleak` event loop and an in-memory device registry, following the existing `scanner.py` pattern. A thin synchronous `CintennaAdapter` reads that registry so the existing Devices tab strip works unchanged. A separate `/api/ble/*` blueprint serves roster and snapshot reads, registering only when `ENABLE_BLE_TOOLS` is set.

**Tech Stack:** Python 3 / Flask 3 / `bleak` / pytest on the backend; React 19 / Vite 5 / Tailwind 4 / axios / Vitest + React Testing Library on the frontend.

**Design:** [`docs/superpowers/specs/2026-07-26-cintenna-ble-design.md`](../specs/2026-07-26-cintenna-ble-design.md)
**Repo map:** [`docs/architecture/ble-integration-map.md`](../../architecture/ble-integration-map.md)

## Global Constraints

- **This plan ships no write path.** `command_service.py` is not created here. No task may call `bleak`'s `write_gatt_char`. If a task seems to need it, stop and re-read the design.
- Branch: `feat/cintenna-ble`, based on `main`. Never `edit_export` — it is 51 commits stale.
- Backend root is `backend/app/`. Backend tests are **flat** in `backend/tests/` named `test_ble_<subject>.py`. No test subpackages.
- Frontend root is `app/` — `app/package.json`, `app/vite.config.mjs`. The `package.json` and `vite.config.js` at the repository root are stale duplicates; never edit them.
- Frontend components are `.jsx`. New BLE components live in `app/src/components/devices/`.
- `FIVE12_BLE_TOOLS` **defaults off**. Absent env var means no BLE thread starts and `/api/ble/*` routes do not exist.
- Characteristics are resolved **by UUID on every connection**. Never address by ATT handle.
- JSON response keys are **camelCase**, matching the existing API convention.
- Never log or store: linking keys, the `10351003` opaque blob, or full OS device identifiers.
- Language rules, enforced in code and copy: "nearby" ≠ "connected"; "TimoTwo-compatible" ≠ "Cintenna 2"; RSSI is not distance. There must be no field named `linked` anywhere in this plan's output.
- Run backend tests from `backend/`: `pytest`. Run frontend tests from `app/`: `npm run test`.

## File Structure

**Created — backend**

| File | Responsibility |
|---|---|
| `backend/app/five12_ble/__init__.py` | Package marker; no logic |
| `backend/app/five12_ble/constants.py` | Verified UUIDs, enums, read allowlist. Pure |
| `backend/app/five12_ble/advertisement.py` | Manufacturer-data decoding. Pure |
| `backend/app/five12_ble/decoders.py` | Raw GATT bytes → display values. Pure |
| `backend/app/five12_ble/models.py` | `DiscoveredDevice` dataclass |
| `backend/app/five12_ble/registry.py` | Thread-safe device registry: upsert, RSSI smoothing, expiry |
| `backend/app/five12_ble/errors.py` | Typed BLE failures with operator copy |
| `backend/app/five12_ble/sim.py` | Fake advertisements and GATT values |
| `backend/app/five12_ble/scanner.py` | Owns the bleak loop + scan thread |
| `backend/app/five12_ble/connection_manager.py` | Single-owner connections, bounded timeouts |
| `backend/app/five12_ble/gatt_client.py` | Read-only snapshot builder |
| `backend/app/integrations/cintenna.py` | `CintennaAdapter` — sync facade over the registry |
| `backend/app/ble_routes.py` | `/api/ble/*` blueprint |

**Created — frontend**

| File | Responsibility |
|---|---|
| `app/src/lib/bleApi.js` | axios wrapper for `/api/ble/*` |
| `app/src/components/devices/CintennaPanel.jsx` | Roster + detail panel |
| `app/src/components/devices/BleEvidenceBadge.jsx` | Renders a field's evidence source |
| `app/src/test/setup.js` | Vitest + jest-dom setup |

**Modified**

| File | Change |
|---|---|
| `backend/config.py` | Add `ENABLE_BLE_TOOLS` to both config classes |
| `backend/app/__init__.py` | Register `ble_routes` and start the BLE thread under the gate |
| `backend/app/integrations/__init__.py` | Add `cintenna` to `get_adapter` and `ALL_DEVICE_IDS` |
| `backend/requirements.txt` | Add pinned `bleak` |
| `app/package.json` | Add Vitest/RTL devDeps and `test` scripts |
| `app/vite.config.mjs` | Add the `test` block |
| `app/src/pages/Devices.jsx` | Import `CintennaPanel`, add to `PANELS` |

---

### Task 1: Feature gate, dependency, and capabilities endpoint

**Files:**
- Modify: `backend/config.py:25` (DevelopmentConfig), `backend/config.py:43` (DesktopConfig)
- Modify: `backend/requirements.txt`
- Create: `backend/app/ble_routes.py`
- Modify: `backend/app/__init__.py:53-55`
- Test: `backend/tests/test_ble_gate.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `app.config['ENABLE_BLE_TOOLS']` (bool); blueprint `ble` at `/api/ble`; `GET /api/ble/capabilities` → `{"bleToolsEnabled": bool, "adapterAvailable": bool, "platformSupported": bool}`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_ble_gate.py`:

```python
"""The BLE gate defaults OFF. Unlike FIVE12_NETWORK_TOOLS (which defaults on
because probing your own LAN is expected), starting a radio scan without being
asked is not. When off, the routes must not exist at all."""

from app import create_app


def test_ble_disabled_by_default():
    app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
    assert app.config.get('ENABLE_BLE_TOOLS') is False


def test_capabilities_route_absent_when_disabled():
    app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
    resp = app.test_client().get('/api/ble/capabilities')
    assert resp.status_code == 404


def test_capabilities_route_present_when_enabled():
    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'ENABLE_BLE_TOOLS': True,
    })
    resp = app.test_client().get('/api/ble/capabilities')
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['bleToolsEnabled'] is True
    assert 'adapterAvailable' in body
    assert 'platformSupported' in body
```

- [ ] **Step 2: Run test to verify it fails**

Run from `backend/`: `pytest tests/test_ble_gate.py -v`
Expected: FAIL — `test_ble_disabled_by_default` fails because `ENABLE_BLE_TOOLS` is `None`, and the "present when enabled" test 404s.

- [ ] **Step 3: Add the config flag**

In `backend/config.py`, inside `DevelopmentConfig`, directly after the `ENABLE_NETWORK_TOOLS` line:

```python
    # Gates the Bluetooth stack in app/__init__.py — the bleak scan thread and
    # the /api/ble/* blueprint. OFF by default, deliberately unlike
    # ENABLE_NETWORK_TOOLS: probing the operator's own LAN is expected, but
    # starting a radio scan without being asked is not. Set FIVE12_BLE_TOOLS=1.
    ENABLE_BLE_TOOLS = os.getenv("FIVE12_BLE_TOOLS", "0") == "1"
```

In `backend/config.py`, inside `DesktopConfig`, directly after `ENABLE_NETWORK_TOOLS = True`:

```python
    # BLE stays opt-in even on desktop — the operator turns it on per show.
    ENABLE_BLE_TOOLS = os.getenv("FIVE12_BLE_TOOLS", "0") == "1"
```

- [ ] **Step 4: Create the blueprint**

Create `backend/app/ble_routes.py`:

```python
"""Bluetooth device routes — read-only CRMX/TimoTwo discovery.

Registered ONLY when ENABLE_BLE_TOOLS is set, so with the gate off these
routes do not exist rather than returning 403.

This module contains no write path. Configuration writes, TX Link, and RX
Unlink are a later, separately gated piece of work.
"""

import sys

from flask import Blueprint, jsonify

ble = Blueprint('ble', __name__, url_prefix='/api/ble')


def _platform_supported():
    """bleak supports Windows 10+ / macOS / Linux with BlueZ. Five12's target
    is Windows 11, so anything else is 'works, unverified' rather than a hard
    no — report the platform honestly and let the UI phrase it."""
    return sys.platform in ('win32', 'darwin', 'linux')


def _adapter_available():
    """True when a usable Bluetooth adapter is present. Task 6 replaces this
    with a real bleak probe; until the scanner exists there is nothing to ask."""
    return False


@ble.get('/capabilities')
def capabilities():
    return jsonify({
        'bleToolsEnabled': True,   # this route only exists when the gate is on
        'adapterAvailable': _adapter_available(),
        'platformSupported': _platform_supported(),
    })
```

- [ ] **Step 5: Register it in the app factory**

In `backend/app/__init__.py`, directly after the existing `ENABLE_NETWORK_TOOLS` blueprint block (currently lines 53–55):

```python
    # Bluetooth (CRMX/TimoTwo discovery) registers only when explicitly enabled.
    # Default is OFF — see config.ENABLE_BLE_TOOLS. With the gate off no scan
    # thread starts and /api/ble/* does not exist.
    if app.config.get('ENABLE_BLE_TOOLS'):
        from .ble_routes import ble as ble_bp
        app.register_blueprint(ble_bp)
```

- [ ] **Step 6: Run tests to verify they pass**

Run from `backend/`: `pytest tests/test_ble_gate.py -v`
Expected: 3 passed.

- [ ] **Step 7: Confirm nothing else broke**

Run from `backend/`: `pytest`
Expected: all pre-existing tests still pass.

- [ ] **Step 8: Add the dependency**

Install and pin. Run from `backend/`:

```bash
pip install bleak
```

Then read the resolved version and append it to `backend/requirements.txt` with that exact number, e.g.:

```
# Bluetooth LE — CRMX/TimoTwo discovery (only imported when FIVE12_BLE_TOOLS=1)
bleak==0.22.3
```

Do not import `bleak` anywhere yet. Tasks 2–5 are pure modules that must remain importable without it.

- [ ] **Step 9: Commit**

```bash
git add backend/config.py backend/requirements.txt backend/app/ble_routes.py backend/app/__init__.py backend/tests/test_ble_gate.py
git commit -m "feat: add guarded BLE capability gate"
```

---

### Task 2: Verified BLE contract constants

**Files:**
- Create: `backend/app/five12_ble/__init__.py`, `backend/app/five12_ble/constants.py`
- Test: `backend/tests/test_ble_constants.py`

**Interfaces:**
- Consumes: nothing.
- Produces: UUID string constants `CONFIG_SERVICE`, `DEVICE_NAME`, `MODE`, `OUTPUT_POWER`, `UNIVERSE_COLOR`, `DMX_HOLD`, `TX_PROTOCOL`, `FIRMWARE_VERSION`, `BATTERY_LEVEL`, `MODE_MIRROR`, `COLOR_MIRROR`, `LINK_ACTION`; `IntEnum`s `Mode`, `TxProtocol`, `OutputPower`; `frozenset` `READABLE_UUIDS`; `TIMOTWO_SERVICE_UUID`; `ACCEPTED_COMPANY_IDS`.

**This task's test is the release gate for "no arbitrary write path."** It asserts no write allowlist exists in this phase.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_ble_constants.py`:

```python
"""Guards the verified protocol contract. Every UUID here was confirmed by
GATT capture against a RatPac Cintenna on firmware 1.0.7.2 — see the KB
reference timotwo-ble-discovery-and-gatt.md. A typo in a UUID fails silently
at runtime (characteristic simply not found), so it is asserted literally."""

from app.five12_ble import constants as c


def test_config_service_uuids_exact():
    assert c.TIMOTWO_SERVICE_UUID == '33b5376d-0942-1f91-379b-ac5af36b9efa'
    assert c.CONFIG_SERVICE == '33b5376d-0942-1f91-379b-ac5af36b9efa'
    assert c.DEVICE_NAME == '33b5376e-0942-1f91-379b-ac5af36b9efa'
    assert c.MODE == '33b5376f-0942-1f91-379b-ac5af36b9efa'
    assert c.OUTPUT_POWER == '33b53770-0942-1f91-379b-ac5af36b9efa'
    assert c.UNIVERSE_COLOR == '33b53773-0942-1f91-379b-ac5af36b9efa'
    assert c.DMX_HOLD == '33b53774-0942-1f91-379b-ac5af36b9efa'
    assert c.TX_PROTOCOL == '33b53776-0942-1f91-379b-ac5af36b9efa'


def test_other_service_uuids_exact():
    assert c.FIRMWARE_VERSION == '10351004-3555-4907-0431-2b27430c2642'
    assert c.BATTERY_LEVEL == '00002a19-0000-1000-8000-00805f9b34fb'
    assert c.MODE_MIRROR == '45a41001-2ccd-80a5-b844-095c73b6c7e3'
    assert c.COLOR_MIRROR == '45a41002-2ccd-80a5-b844-095c73b6c7e3'
    assert c.LINK_ACTION == '45a41003-2ccd-80a5-b844-095c73b6c7e3'


def test_all_uuids_lowercase_and_well_formed():
    """bleak normalises to lowercase; a mixed-case constant silently fails
    string comparison against a discovered characteristic."""
    for name, value in vars(c).items():
        if name.isupper() and isinstance(value, str) and value.count('-') == 4:
            assert value == value.lower(), f'{name} must be lowercase'
            assert len(value) == 36, f'{name} is not a 36-char UUID'


def test_enums_match_captured_values():
    assert c.Mode.RX == 0x00
    assert c.Mode.TX == 0x01
    assert c.TxProtocol.CRMX == 0x00
    assert c.TxProtocol.W_DMX_G3 == 0x01
    assert c.TxProtocol.W_DMX_G4S == 0x03
    assert c.OutputPower.MAX == 0x02
    assert c.OutputPower.MIN == 0x05


def test_accepted_company_ids():
    """0x09E9 is LumenRadio's production key; 0xFFFF is the development key the
    official example app also accepts. Both are evidence of the radio platform,
    neither proves the enclosure model."""
    assert c.ACCEPTED_COMPANY_IDS == frozenset({0x09E9, 0xFFFF})


def test_readable_allowlist_contains_only_verified_uuids():
    verified = {
        c.DEVICE_NAME, c.MODE, c.OUTPUT_POWER, c.UNIVERSE_COLOR, c.DMX_HOLD,
        c.TX_PROTOCOL, c.FIRMWARE_VERSION, c.BATTERY_LEVEL, c.MODE_MIRROR,
        c.COLOR_MIRROR, c.LINK_ACTION,
    }
    assert c.READABLE_UUIDS == frozenset(verified)


def test_no_write_allowlist_exists_in_this_phase():
    """RELEASE GATE. The read-only phase must ship no write capability at all.
    If a later phase adds writes, it adds them deliberately and this test is
    updated in the same commit that introduces the command policy."""
    assert not hasattr(c, 'WRITE_ALLOWLIST')
    assert not hasattr(c, 'LINK_COMMAND')
    assert not hasattr(c, 'UNLINK_COMMAND')


def test_opaque_blob_is_not_readable():
    """10351003 is a large opaque blob that changes between connections. It is
    not an identifier, not a version, and must never be read or stored."""
    assert '10351003-3555-4907-0431-2b27430c2642' not in c.READABLE_UUIDS
```

- [ ] **Step 2: Run test to verify it fails**

Run from `backend/`: `pytest tests/test_ble_constants.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.five12_ble'`

- [ ] **Step 3: Create the package and constants**

Create `backend/app/five12_ble/__init__.py`:

```python
"""Five12 BLE — LumenRadio TimoTwo (RatPac Cintenna) discovery and status.

Read-only. This package contains no GATT write path.

constants.py, advertisement.py, and decoders.py are pure — no I/O and no bleak
import — so their tests run without a radio or the dependency installed.
"""
```

Create `backend/app/five12_ble/constants.py`:

```python
"""Verified TimoTwo BLE contract.

Every value here was confirmed by controlled GATT capture against a RatPac
Cintenna (advertised name "F12L - 1946") on firmware 1.0.7.2, cross-checked
against LumenRadio's official example app. Source of truth:
hermes-lighting-networking-kb 10-Lighting/References/LumenRadio/
timotwo-ble-discovery-and-gatt.md

Do NOT add a UUID here without a capture or official documentation behind it.
"""

from enum import IntEnum

# ── Advertisement identity ───────────────────────────────────────────────────
# The official scanner filters advertisements on this service.
TIMOTWO_SERVICE_UUID = '33b5376d-0942-1f91-379b-ac5af36b9efa'

# 0x09E9 is LumenRadio's production company key; 0xFFFF is the development key
# the official example app also accepts. Evidence of platform, not enclosure.
ACCEPTED_COMPANY_IDS = frozenset({0x09E9, 0xFFFF})

ESTA_LUMENRADIO = '4C55'
MODEL_TIMOTWO = 'F140'

# ── Configuration service ────────────────────────────────────────────────────
CONFIG_SERVICE = '33b5376d-0942-1f91-379b-ac5af36b9efa'
DEVICE_NAME = '33b5376e-0942-1f91-379b-ac5af36b9efa'
MODE = '33b5376f-0942-1f91-379b-ac5af36b9efa'
OUTPUT_POWER = '33b53770-0942-1f91-379b-ac5af36b9efa'
UNIVERSE_COLOR = '33b53773-0942-1f91-379b-ac5af36b9efa'
DMX_HOLD = '33b53774-0942-1f91-379b-ac5af36b9efa'
TX_PROTOCOL = '33b53776-0942-1f91-379b-ac5af36b9efa'

# ── Other verified characteristics ───────────────────────────────────────────
# Firmware lives in an otherwise update/security-related service. Only ...004
# is understood; the sibling blob ...003 is deliberately absent from this file.
FIRMWARE_VERSION = '10351004-3555-4907-0431-2b27430c2642'
BATTERY_LEVEL = '00002a19-0000-1000-8000-00805f9b34fb'   # standard 0x2A19

# Read-only mirrors of config values, confirmed to track their counterparts.
MODE_MIRROR = '45a41001-2ccd-80a5-b844-095c73b6c7e3'
COLOR_MIRROR = '45a41002-2ccd-80a5-b844-095c73b6c7e3'
# Reads 01 in RX / 03 in TX. Writing it performs Link/Unlink — NOT in this
# phase. Present as a readable status field only.
LINK_ACTION = '45a41003-2ccd-80a5-b844-095c73b6c7e3'

READABLE_UUIDS = frozenset({
    DEVICE_NAME, MODE, OUTPUT_POWER, UNIVERSE_COLOR, DMX_HOLD, TX_PROTOCOL,
    FIRMWARE_VERSION, BATTERY_LEVEL, MODE_MIRROR, COLOR_MIRROR, LINK_ACTION,
})


class Mode(IntEnum):
    RX = 0x00
    TX = 0x01


class TxProtocol(IntEnum):
    CRMX = 0x00
    W_DMX_G3 = 0x01
    W_DMX_G4S = 0x03


class OutputPower(IntEnum):
    MAX = 0x02       # official module table: 20 dBm / ~100 mW at 2 dBi
    LEVEL_3 = 0x03   # 16 dBm / ~40 mW
    LEVEL_4 = 0x04   # 11 dBm / ~13 mW
    MIN = 0x05       # 5 dBm / ~3 mW; Toolbox labels this "5 mW"


# Observed RX baselines for TX-only fields. Not errors — "not applicable".
RX_POWER_NOT_APPLICABLE = 0x80
RX_PROTOCOL_NOT_APPLICABLE = 0xFF
```

- [ ] **Step 4: Run tests to verify they pass**

Run from `backend/`: `pytest tests/test_ble_constants.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/five12_ble/__init__.py backend/app/five12_ble/constants.py backend/tests/test_ble_constants.py
git commit -m "feat: define verified TimoTwo BLE contract"
```

---

### Task 3: Advertisement decoding

**Files:**
- Create: `backend/app/five12_ble/advertisement.py`
- Test: `backend/tests/test_ble_advertisement.py`

**Interfaces:**
- Consumes: `constants` from Task 2.
- Produces: `decode_manufacturer_data(company_id: int, payload: bytes) -> dict` returning keys `platform`, `product`, `hardwareId`, `estaManufacturerId`, `modelId`, `unknownByte0`, `rawManufacturerData`, `evidence` (list[str]). Also `is_timotwo_service(uuid: str) -> bool`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_ble_advertisement.py`:

```python
"""Advertisement decoding is pure and must never raise — a malformed payload
from unrelated BLE gear in the room cannot be allowed to kill the scan loop."""

from app.five12_ble.advertisement import decode_manufacturer_data, is_timotwo_service

OBSERVED = bytes.fromhex('03F14000004C55F140')   # captured from F12L - 1946


def test_decodes_observed_cintenna_payload():
    out = decode_manufacturer_data(0xFFFF, OBSERVED)
    assert out['hardwareId'] == 'F1400000'
    assert out['estaManufacturerId'] == '4C55'
    assert out['modelId'] == 'F140'
    assert out['platform'] == 'lumenradio-timotwo-compatible'
    assert out['rawManufacturerData'] == '03F14000004C55F140'


def test_product_is_never_inferred():
    """A TimoTwo radio is inside many enclosures. Claiming "Cintenna 2" from
    the radio platform alone is exactly the overclaim the reference warns of."""
    out = decode_manufacturer_data(0xFFFF, OBSERVED)
    assert out['product'] is None


def test_unknown_byte_zero_preserved_raw():
    out = decode_manufacturer_data(0xFFFF, OBSERVED)
    assert out['unknownByte0'] == '03'


def test_production_company_id_accepted():
    out = decode_manufacturer_data(0x09E9, OBSERVED)
    assert 'manufacturer-data' in out['evidence']
    assert out['platform'] == 'lumenradio-timotwo-compatible'


def test_unrecognised_company_id_yields_no_platform_claim():
    out = decode_manufacturer_data(0x004C, OBSERVED)   # Apple
    assert out['platform'] is None
    assert out['evidence'] == []


def test_short_payload_does_not_raise():
    out = decode_manufacturer_data(0xFFFF, b'\x03\xf1')
    assert out['hardwareId'] is None
    assert out['modelId'] is None
    assert out['rawManufacturerData'] == '03F1'


def test_empty_payload_does_not_raise():
    out = decode_manufacturer_data(0xFFFF, b'')
    assert out['hardwareId'] is None
    assert out['rawManufacturerData'] == ''


def test_wrong_esta_id_still_decodes_but_makes_no_platform_claim():
    payload = bytes.fromhex('03F1400000FFFFF140')
    out = decode_manufacturer_data(0xFFFF, payload)
    assert out['estaManufacturerId'] == 'FFFF'
    assert out['platform'] is None


def test_service_match_is_case_insensitive():
    assert is_timotwo_service('33B5376D-0942-1F91-379B-AC5AF36B9EFA')
    assert is_timotwo_service('33b5376d-0942-1f91-379b-ac5af36b9efa')
    assert not is_timotwo_service('0000180f-0000-1000-8000-00805f9b34fb')
```

- [ ] **Step 2: Run test to verify it fails**

Run from `backend/`: `pytest tests/test_ble_advertisement.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.five12_ble.advertisement'`

- [ ] **Step 3: Write the implementation**

Create `backend/app/five12_ble/advertisement.py`:

```python
"""Passive advertisement decoding — pure, no I/O, no bleak.

Byte layout confirmed against LumenRadio's official example app:

    byte 0      present but not interpreted by the example app
    bytes 1-4   hardware ID
    bytes 5-6   embedded ESTA manufacturer ID
    bytes 7-8   model ID

Observed on a RatPac Cintenna: 03 F1 40 00 00 4C 55 F1 40

Every function here must tolerate arbitrary bytes. The scan loop sees every
BLE advertiser in the room, and one malformed neighbour must not stop it.
"""

from .constants import (
    ACCEPTED_COMPANY_IDS,
    ESTA_LUMENRADIO,
    MODEL_TIMOTWO,
    TIMOTWO_SERVICE_UUID,
)

PLATFORM_TIMOTWO = 'lumenradio-timotwo-compatible'


def is_timotwo_service(uuid):
    """bleak lowercases discovered UUIDs, but advertisement sources and manual
    fixtures may not — compare case-insensitively."""
    return isinstance(uuid, str) and uuid.lower() == TIMOTWO_SERVICE_UUID


def _slice_hex(payload, start, end):
    """Upper-case hex for payload[start:end], or None if the payload is too
    short. Never raises."""
    if len(payload) < end:
        return None
    return payload[start:end].hex().upper()


def decode_manufacturer_data(company_id, payload):
    """Decode a BLE manufacturer-data record.

    `platform` is claimed only when both the outer company key and the embedded
    ESTA/model IDs agree. `product` is ALWAYS None: the radio platform does not
    identify the enclosure, and calling a TimoTwo a "Cintenna 2" on this
    evidence is an overclaim.
    """
    payload = payload or b''
    hardware_id = _slice_hex(payload, 1, 5)
    esta_id = _slice_hex(payload, 5, 7)
    model_id = _slice_hex(payload, 7, 9)

    evidence = []
    if company_id in ACCEPTED_COMPANY_IDS:
        evidence.append('manufacturer-data')

    platform = None
    if evidence and esta_id == ESTA_LUMENRADIO and model_id == MODEL_TIMOTWO:
        platform = PLATFORM_TIMOTWO

    return {
        'platform': platform,
        'product': None,
        'hardwareId': hardware_id,
        'estaManufacturerId': esta_id,
        'modelId': model_id,
        'unknownByte0': _slice_hex(payload, 0, 1),
        'rawManufacturerData': payload.hex().upper(),
        'evidence': evidence if platform else [],
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run from `backend/`: `pytest tests/test_ble_advertisement.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/five12_ble/advertisement.py backend/tests/test_ble_advertisement.py
git commit -m "feat: decode TimoTwo advertisements"
```

---

### Task 4: GATT value decoders

**Files:**
- Create: `backend/app/five12_ble/decoders.py`
- Test: `backend/tests/test_ble_decoders.py`

**Interfaces:**
- Consumes: `constants` from Task 2.
- Produces: `decode_name`, `decode_battery`, `decode_firmware`, `decode_mode`, `decode_dmx_hold`, `decode_output_power`, `decode_universe_color`, `decode_tx_protocol`, `decode_link_status` — each `(raw: bytes) -> dict` with at least `{'raw': str, 'decoded': <value|None>}`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_ble_decoders.py`:

```python
"""Decoders convert verified raw bytes to display values WITHOUT discarding the
evidence. Every result keeps its raw hex so the UI can show what was actually
on the wire. Unknown values decode to None — never an exception, because a
firmware revision we have not seen must degrade, not crash."""

from app.five12_ble import decoders as d


def test_firmware_byte_order_is_reversed():
    """Toolbox displayed 1.0.7.2 while the wire carried 02 07 00 01. This
    reversal is the single easiest thing in the module to silently regress."""
    out = d.decode_firmware(bytes.fromhex('02070001'))
    assert out['decoded'] == '1.0.7.2'
    assert out['raw'] == '02070001'


def test_firmware_wrong_length_is_none():
    assert d.decode_firmware(b'\x02\x07')['decoded'] is None


def test_mode():
    assert d.decode_mode(b'\x00')['decoded'] == 'rx'
    assert d.decode_mode(b'\x01')['decoded'] == 'tx'
    assert d.decode_mode(b'\x7f')['decoded'] is None


def test_dmx_hold():
    assert d.decode_dmx_hold(b'\x00')['decoded'] is False
    assert d.decode_dmx_hold(b'\x01')['decoded'] is True
    assert d.decode_dmx_hold(b'\x09')['decoded'] is None


def test_output_power_keeps_three_separate_labels():
    """Raw enum, official module figure, and Toolbox's product label disagree.
    Keep all three rather than manufacturing a single false number."""
    out = d.decode_output_power(b'\x02')
    assert out['decoded'] == 'max'
    assert out['rawEnum'] == 2
    assert out['moduleFigure'] == '20 dBm / ~100 mW'
    assert out['toolboxLabel'] == '>100 mW'


def test_output_power_min():
    out = d.decode_output_power(b'\x05')
    assert out['decoded'] == 'min'
    assert out['toolboxLabel'] == '5 mW'


def test_output_power_rx_baseline_is_not_applicable_not_error():
    out = d.decode_output_power(b'\x80')
    assert out['decoded'] is None
    assert out['notApplicable'] is True


def test_tx_protocol():
    assert d.decode_tx_protocol(b'\x00')['decoded'] == 'crmx'
    assert d.decode_tx_protocol(b'\x01')['decoded'] == 'w-dmx-g3'
    assert d.decode_tx_protocol(b'\x03')['decoded'] == 'w-dmx-g4s'


def test_tx_protocol_rx_baseline_is_not_applicable():
    out = d.decode_tx_protocol(b'\xff')
    assert out['decoded'] is None
    assert out['notApplicable'] is True


def test_universe_color_rgb():
    out = d.decode_universe_color(bytes.fromhex('00FF00'))
    assert out['decoded'] == '#00FF00'
    assert out['rgb'] == [0, 255, 0]


def test_universe_color_wrong_length_is_none():
    assert d.decode_universe_color(b'\x00\xff')['decoded'] is None


def test_battery_percent():
    assert d.decode_battery(b'\x41')['decoded'] == 65


def test_battery_out_of_range_is_none():
    assert d.decode_battery(b'\xc8')['decoded'] is None    # 200%


def test_name_is_null_padded_utf8():
    raw = b'F12L - 1946' + b'\x00' * 5
    assert d.decode_name(raw)['decoded'] == 'F12L - 1946'


def test_name_invalid_utf8_is_none():
    assert d.decode_name(b'\xff\xfe\xfd')['decoded'] is None


def test_link_status_is_status_not_link_state():
    """LINK_ACTION reads 01 in RX and 03 in TX. These are baseline status
    values, NOT proof of receiver association. The decoder must not return
    anything resembling a linked boolean."""
    out = d.decode_link_status(b'\x01')
    assert out['raw'] == '01'
    assert 'linked' not in out


def test_all_decoders_tolerate_empty_bytes():
    for fn in (d.decode_name, d.decode_battery, d.decode_firmware, d.decode_mode,
               d.decode_dmx_hold, d.decode_output_power, d.decode_universe_color,
               d.decode_tx_protocol, d.decode_link_status):
        out = fn(b'')
        assert out['decoded'] is None, fn.__name__
```

- [ ] **Step 2: Run test to verify it fails**

Run from `backend/`: `pytest tests/test_ble_decoders.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.five12_ble.decoders'`

- [ ] **Step 3: Write the implementation**

Create `backend/app/five12_ble/decoders.py`:

```python
"""Raw GATT bytes → display values. Pure, no I/O, no bleak.

Two rules hold everywhere in this module:

1. Never raise. An unrecognised value decodes to None. A firmware revision we
   have not captured must degrade gracefully, not crash a snapshot.
2. Never discard the raw bytes. Every result carries its hex so the UI can
   show the evidence behind a decoded label.
"""

from .constants import (
    Mode,
    OutputPower,
    RX_POWER_NOT_APPLICABLE,
    RX_PROTOCOL_NOT_APPLICABLE,
    TxProtocol,
)

# Raw enum, the official module table figure, and Toolbox's product-facing
# label are three different things and are kept separate deliberately.
_POWER_LABELS = {
    OutputPower.MAX: ('max', '20 dBm / ~100 mW', '>100 mW'),
    OutputPower.LEVEL_3: ('level-3', '16 dBm / ~40 mW', None),
    OutputPower.LEVEL_4: ('level-4', '11 dBm / ~13 mW', None),
    OutputPower.MIN: ('min', '5 dBm / ~3 mW', '5 mW'),
}

_PROTOCOL_LABELS = {
    TxProtocol.CRMX: 'crmx',
    TxProtocol.W_DMX_G3: 'w-dmx-g3',
    TxProtocol.W_DMX_G4S: 'w-dmx-g4s',
}


def _hex(raw):
    return (raw or b'').hex().upper()


def _one_byte(raw):
    """The single byte of a one-byte characteristic, or None."""
    return raw[0] if raw and len(raw) == 1 else None


def decode_name(raw):
    """Device name is null-padded UTF-8."""
    decoded = None
    if raw:
        try:
            decoded = raw.split(b'\x00', 1)[0].decode('utf-8') or None
        except UnicodeDecodeError:
            decoded = None
    return {'raw': _hex(raw), 'decoded': decoded}


def decode_battery(raw):
    """Standard Battery Service 0x2A19 — one byte, 0-100 percent."""
    value = _one_byte(raw)
    if value is not None and not 0 <= value <= 100:
        value = None
    return {'raw': _hex(raw), 'decoded': value}


def decode_firmware(raw):
    """Wire bytes are least-significant first. 02 07 00 01 displays as 1.0.7.2,
    confirmed against CRMX Toolbox on the captured unit."""
    decoded = None
    if raw and len(raw) == 4:
        decoded = '.'.join(str(b) for b in reversed(raw))
    return {'raw': _hex(raw), 'decoded': decoded}


def decode_mode(raw):
    value = _one_byte(raw)
    decoded = None
    if value == Mode.RX:
        decoded = 'rx'
    elif value == Mode.TX:
        decoded = 'tx'
    return {'raw': _hex(raw), 'decoded': decoded}


def decode_dmx_hold(raw):
    """DMX Hold keeps DMX output active on loss of connectivity."""
    value = _one_byte(raw)
    decoded = None
    if value == 0x00:
        decoded = False
    elif value == 0x01:
        decoded = True
    return {'raw': _hex(raw), 'decoded': decoded}


def decode_output_power(raw):
    value = _one_byte(raw)
    out = {
        'raw': _hex(raw),
        'decoded': None,
        'rawEnum': value,
        'moduleFigure': None,
        'toolboxLabel': None,
        'notApplicable': value == RX_POWER_NOT_APPLICABLE,
    }
    if value in _POWER_LABELS:
        label, module_figure, toolbox_label = _POWER_LABELS[value]
        out['decoded'] = label
        out['moduleFigure'] = module_figure
        out['toolboxLabel'] = toolbox_label
    return out


def decode_universe_color(raw):
    """Three RGB bytes. 00 FF 00 is Green."""
    decoded, rgb = None, None
    if raw and len(raw) == 3:
        rgb = list(raw)
        decoded = '#{:02X}{:02X}{:02X}'.format(*rgb)
    return {'raw': _hex(raw), 'decoded': decoded, 'rgb': rgb}


def decode_tx_protocol(raw):
    value = _one_byte(raw)
    return {
        'raw': _hex(raw),
        'decoded': _PROTOCOL_LABELS.get(value),
        'notApplicable': value == RX_PROTOCOL_NOT_APPLICABLE,
    }


def decode_link_status(raw):
    """LINK_ACTION ordinary reads: 01 observed in RX, 03 observed in TX.

    These are baseline status values whose full semantics are NOT established.
    This returns the observed value only. It deliberately exposes no boolean
    link state — an ATT-level value is not evidence of RF association.
    """
    value = _one_byte(raw)
    return {
        'raw': _hex(raw),
        'decoded': value,
        'note': 'observed status value; not proof of receiver association',
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run from `backend/`: `pytest tests/test_ble_decoders.py -v`
Expected: 16 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/five12_ble/decoders.py backend/tests/test_ble_decoders.py
git commit -m "feat: decode verified Cintenna GATT values"
```

---

### Task 5: Device models and registry

**Files:**
- Create: `backend/app/five12_ble/models.py`, `backend/app/five12_ble/registry.py`
- Test: `backend/tests/test_ble_registry.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `DiscoveredDevice` dataclass with `to_dict()`; `Registry` with `upsert(os_id, name, rssi, advert, now=None)`, `all(now=None) -> list[DiscoveredDevice]`, `get(os_id)`, `count()`. Registry expires entries after `stale_after` seconds (default 60).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_ble_registry.py`:

```python
"""The registry is the single source of truth for "what is nearby". It is
written by the scan thread and read by Flask request threads, so it must be
thread-safe, and it must never grow without bound in a room full of BLE gear."""

from app.five12_ble.registry import Registry


ADVERT = {
    'platform': 'lumenradio-timotwo-compatible',
    'product': None,
    'hardwareId': 'F1400000',
    'estaManufacturerId': '4C55',
    'modelId': 'F140',
    'rawManufacturerData': '03F14000004C55F140',
    'evidence': ['manufacturer-data'],
}


def test_upsert_creates_then_updates_same_device():
    r = Registry()
    r.upsert('os-1', 'F12L - 1946', -50, ADVERT, now=100.0)
    r.upsert('os-1', 'F12L - 1946', -44, ADVERT, now=101.0)
    assert r.count() == 1
    dev = r.get('os-1')
    assert dev.first_seen == 100.0
    assert dev.last_seen == 101.0


def test_rssi_is_smoothed_but_latest_is_kept():
    """A raw RSSI jitters several dB between adverts; the panel needs a stable
    bar. Keep both — smoothed for display, latest for the evidence drawer."""
    r = Registry()
    r.upsert('os-1', 'n', -40, ADVERT, now=100.0)
    r.upsert('os-1', 'n', -60, ADVERT, now=101.0)
    dev = r.get('os-1')
    assert dev.rssi == -60
    assert -60 < dev.rssi_smoothed < -40


def test_first_sample_smoothed_equals_raw():
    r = Registry()
    r.upsert('os-1', 'n', -47, ADVERT, now=100.0)
    assert r.get('os-1').rssi_smoothed == -47


def test_stale_devices_are_excluded_from_all():
    r = Registry(stale_after=60)
    r.upsert('os-old', 'gone', -50, ADVERT, now=100.0)
    r.upsert('os-new', 'here', -50, ADVERT, now=150.0)
    ids = [d.os_id for d in r.all(now=170.0)]
    assert ids == ['os-new']


def test_stale_device_is_retained_for_lookup_not_deleted():
    """Expiry hides a device from the roster; it does not destroy what we
    learned about it, so a device that reappears keeps its first_seen."""
    r = Registry(stale_after=60)
    r.upsert('os-1', 'n', -50, ADVERT, now=100.0)
    assert r.all(now=200.0) == []
    r.upsert('os-1', 'n', -50, ADVERT, now=201.0)
    assert r.get('os-1').first_seen == 100.0


def test_all_sorted_by_signal_strongest_first():
    r = Registry()
    r.upsert('weak', 'w', -80, ADVERT, now=100.0)
    r.upsert('strong', 's', -35, ADVERT, now=100.0)
    assert [d.os_id for d in r.all(now=100.0)] == ['strong', 'weak']


def test_to_dict_is_camel_case_and_carries_no_gatt_fields():
    """A roster entry comes from advertisements only. Nearby is not connected —
    battery/firmware/mode must not appear until someone connects."""
    r = Registry()
    r.upsert('os-1', 'F12L - 1946', -41, ADVERT, now=100.0)
    out = r.get('os-1').to_dict()
    assert out['osId'] == 'os-1'
    assert out['localName'] == 'F12L - 1946'
    assert out['rssi'] == -41
    assert out['platform'] == 'lumenradio-timotwo-compatible'
    assert out['product'] is None
    for forbidden in ('battery', 'firmware', 'mode', 'linked'):
        assert forbidden not in out


def test_concurrent_upserts_do_not_lose_devices():
    import threading
    r = Registry()

    def writer(start):
        for i in range(start, start + 200):
            r.upsert(f'os-{i}', 'n', -50, ADVERT, now=100.0)

    threads = [threading.Thread(target=writer, args=(s,)) for s in (0, 200, 400)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert r.count() == 600
```

- [ ] **Step 2: Run test to verify it fails**

Run from `backend/`: `pytest tests/test_ble_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.five12_ble.registry'`

- [ ] **Step 3: Write the models**

Create `backend/app/five12_ble/models.py`:

```python
"""Dataclasses shared across the BLE package.

Identity note: `os_id` is whatever bleak reports for the peripheral. On Windows
this is an OS-level handle, and the peripheral may use a resolvable private
address that rotates — the captured unit reports address resolution supported
(0x2AA6). Treat os_id as best-effort identity within a session, never as a
stable key equivalent to an Ethernet MAC.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class DiscoveredDevice:
    """A radio seen in a passive scan. Advertisement data only — no GATT."""
    os_id: str
    local_name: Optional[str]
    rssi: int
    rssi_smoothed: float
    first_seen: float
    last_seen: float
    advert: dict

    def to_dict(self):
        return {
            'osId': self.os_id,
            'localName': self.local_name,
            'rssi': self.rssi,
            'rssiSmoothed': round(self.rssi_smoothed, 1),
            'firstSeen': self.first_seen,
            'lastSeen': self.last_seen,
            'platform': self.advert.get('platform'),
            'product': self.advert.get('product'),
            'hardwareId': self.advert.get('hardwareId'),
            'estaManufacturerId': self.advert.get('estaManufacturerId'),
            'modelId': self.advert.get('modelId'),
            'rawManufacturerData': self.advert.get('rawManufacturerData'),
            'evidence': self.advert.get('evidence', []),
        }
```

- [ ] **Step 4: Write the registry**

Create `backend/app/five12_ble/registry.py`:

```python
"""Thread-safe registry of nearby BLE devices.

Written by the scan thread, read by Flask request threads. Entries are hidden
from the roster once stale but retained in the map, so a device that walks out
of range and back keeps its first_seen rather than looking brand new.
"""

import threading
import time

from .models import DiscoveredDevice

# Exponential smoothing factor for displayed RSSI. 0.4 settles within a few
# adverts while still damping the several-dB jitter of a raw reading.
_RSSI_ALPHA = 0.4


class Registry:
    def __init__(self, stale_after=60.0):
        self.stale_after = stale_after
        self._devices = {}
        self._lock = threading.Lock()

    def upsert(self, os_id, name, rssi, advert, now=None):
        now = time.time() if now is None else now
        with self._lock:
            existing = self._devices.get(os_id)
            if existing is None:
                self._devices[os_id] = DiscoveredDevice(
                    os_id=os_id,
                    local_name=name,
                    rssi=rssi,
                    rssi_smoothed=float(rssi),
                    first_seen=now,
                    last_seen=now,
                    advert=advert,
                )
                return self._devices[os_id]

            existing.local_name = name or existing.local_name
            existing.rssi = rssi
            existing.rssi_smoothed = (
                _RSSI_ALPHA * rssi + (1 - _RSSI_ALPHA) * existing.rssi_smoothed
            )
            existing.last_seen = now
            if advert:
                existing.advert = advert
            return existing

    def get(self, os_id):
        with self._lock:
            return self._devices.get(os_id)

    def all(self, now=None):
        """Fresh devices, strongest signal first."""
        now = time.time() if now is None else now
        with self._lock:
            fresh = [
                d for d in self._devices.values()
                if now - d.last_seen <= self.stale_after
            ]
        return sorted(fresh, key=lambda d: d.rssi_smoothed, reverse=True)

    def count(self):
        with self._lock:
            return len(self._devices)

    def clear(self):
        with self._lock:
            self._devices.clear()
```

- [ ] **Step 5: Run tests to verify they pass**

Run from `backend/`: `pytest tests/test_ble_registry.py -v`
Expected: 8 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/five12_ble/models.py backend/app/five12_ble/registry.py backend/tests/test_ble_registry.py
git commit -m "feat: add BLE device registry"
```

---

### Task 6: Typed errors

**Files:**
- Create: `backend/app/five12_ble/errors.py`
- Test: `backend/tests/test_ble_errors.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `BleError` base with `code` and `operator_message`, plus `AdapterUnavailable`, `DeviceNotFound`, `DeviceBusy`, `ToolboxHoldingConnection`, `CharacteristicMissing`, `OperationTimeout`, `NotOwner`. All expose `to_dict()`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_ble_errors.py`:

```python
"""Every BLE failure an operator can hit needs copy they can act on. A lighting
tech mid-focus does not benefit from "BleakError: WinRT: 0x80070490"."""

import pytest

from app.five12_ble import errors as e


def test_all_errors_carry_code_and_operator_message():
    for cls in (e.AdapterUnavailable, e.DeviceNotFound, e.DeviceBusy,
                e.ToolboxHoldingConnection, e.CharacteristicMissing,
                e.OperationTimeout, e.NotOwner):
        err = cls()
        assert err.code, cls.__name__
        assert err.operator_message, cls.__name__
        assert len(err.operator_message) > 20, cls.__name__


def test_toolbox_conflict_names_toolbox_and_says_what_to_do():
    """This is the most common real-world failure — Toolbox holds the BLE
    connection exclusively. The message must name it and give the fix."""
    msg = e.ToolboxHoldingConnection().operator_message.lower()
    assert 'toolbox' in msg
    assert 'close' in msg


def test_to_dict_shape():
    out = e.DeviceNotFound(detail='os-1').to_dict()
    assert out['code'] == 'device-not-found'
    assert 'message' in out
    assert out['detail'] == 'os-1'


def test_errors_are_raisable():
    with pytest.raises(e.BleError):
        raise e.OperationTimeout()


def test_codes_are_unique():
    codes = [cls().code for cls in (
        e.AdapterUnavailable, e.DeviceNotFound, e.DeviceBusy,
        e.ToolboxHoldingConnection, e.CharacteristicMissing,
        e.OperationTimeout, e.NotOwner)]
    assert len(codes) == len(set(codes))
```

- [ ] **Step 2: Run test to verify it fails**

Run from `backend/`: `pytest tests/test_ble_errors.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.five12_ble.errors'`

- [ ] **Step 3: Write the implementation**

Create `backend/app/five12_ble/errors.py`:

```python
"""Typed BLE failures, each with copy an operator can act on.

Raw bleak/WinRT errors are unreadable at a focus call. Every failure the user
can actually cause gets a named class and a sentence that says what to do.
"""


class BleError(Exception):
    code = 'ble-error'
    operator_message = 'Bluetooth operation failed.'

    def __init__(self, detail=None):
        self.detail = detail
        super().__init__(f'{self.code}: {self.operator_message}')

    def to_dict(self):
        out = {'code': self.code, 'message': self.operator_message}
        if self.detail:
            out['detail'] = self.detail
        return out


class AdapterUnavailable(BleError):
    code = 'adapter-unavailable'
    operator_message = (
        'No usable Bluetooth adapter was found. Check that Bluetooth is turned '
        'on in Windows settings, then reload this page.'
    )


class DeviceNotFound(BleError):
    code = 'device-not-found'
    operator_message = (
        'That device is no longer in range. Move closer to the fixture, or wait '
        'for the next scan pass and try again.'
    )


class DeviceBusy(BleError):
    code = 'device-busy'
    operator_message = (
        'Another operation is already using this device. Wait for it to finish '
        'and try again.'
    )


class ToolboxHoldingConnection(BleError):
    code = 'toolbox-holding-connection'
    operator_message = (
        'CRMX Toolbox appears to be connected to this device. Toolbox holds the '
        'Bluetooth connection exclusively — close it completely, then try again.'
    )


class CharacteristicMissing(BleError):
    code = 'characteristic-missing'
    operator_message = (
        'This device did not expose an expected Bluetooth characteristic. It may '
        'be running firmware Five12 has not been verified against.'
    )


class OperationTimeout(BleError):
    code = 'operation-timeout'
    operator_message = (
        'The device stopped responding before the operation finished. This is '
        'common at the edge of range — move closer and try again.'
    )


class NotOwner(BleError):
    code = 'not-owner'
    operator_message = (
        'Another Five12 process owns the Bluetooth adapter. Only one can scan at '
        'a time; close the other window or wait for it to release the adapter.'
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run from `backend/`: `pytest tests/test_ble_errors.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/five12_ble/errors.py backend/tests/test_ble_errors.py
git commit -m "feat: add typed BLE errors with operator copy"
```

---

### Task 7: Sim backend

**Files:**
- Create: `backend/app/five12_ble/sim.py`
- Test: `backend/tests/test_ble_sim.py`

**Interfaces:**
- Consumes: `constants`, `advertisement`, `registry` from Tasks 2, 3, 5.
- Produces: `sim_advertisements() -> list[tuple[os_id, name, rssi, advert_dict]]`; `sim_gatt_values(os_id) -> dict[uuid, bytes]`; `SIM_DEVICE_IDS`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_ble_sim.py`:

```python
"""Sim mode fabricates realistic devices so the Cintennas panel is developable
and demoable without a radio, matching the ?sim=1 convention the Starlink,
Bolero, and Stardust adapters already use.

The fixtures must be the CAPTURED values — if sim drifts from what real
hardware returns, the panel is being developed against fiction."""

from app.five12_ble import constants as c
from app.five12_ble import decoders as d
from app.five12_ble.sim import SIM_DEVICE_IDS, sim_advertisements, sim_gatt_values


def test_sim_yields_at_least_one_rx_and_one_tx():
    """A single simulated device cannot exercise the RX/TX-dependent UI."""
    modes = {
        d.decode_mode(sim_gatt_values(os_id)[c.MODE])['decoded']
        for os_id in SIM_DEVICE_IDS
    }
    assert 'rx' in modes
    assert 'tx' in modes


def test_sim_advertisement_decodes_as_timotwo():
    for os_id, name, rssi, advert in sim_advertisements():
        assert advert['platform'] == 'lumenradio-timotwo-compatible'
        assert advert['product'] is None
        assert advert['estaManufacturerId'] == '4C55'
        assert -100 < rssi < 0
        assert name


def test_sim_firmware_matches_the_captured_unit():
    for os_id in SIM_DEVICE_IDS:
        raw = sim_gatt_values(os_id)[c.FIRMWARE_VERSION]
        assert d.decode_firmware(raw)['decoded'] == '1.0.7.2'


def test_sim_rx_device_uses_captured_rx_baselines():
    rx_id = next(
        i for i in SIM_DEVICE_IDS
        if d.decode_mode(sim_gatt_values(i)[c.MODE])['decoded'] == 'rx'
    )
    values = sim_gatt_values(rx_id)
    assert values[c.OUTPUT_POWER] == b'\x80'      # observed RX baseline
    assert values[c.TX_PROTOCOL] == b'\xff'       # observed RX baseline
    assert values[c.LINK_ACTION] == b'\x01'       # observed RX baseline


def test_sim_tx_device_uses_captured_tx_baselines():
    tx_id = next(
        i for i in SIM_DEVICE_IDS
        if d.decode_mode(sim_gatt_values(i)[c.MODE])['decoded'] == 'tx'
    )
    values = sim_gatt_values(tx_id)
    assert values[c.OUTPUT_POWER] == b'\x02'                 # Max
    assert values[c.UNIVERSE_COLOR] == bytes.fromhex('00FF00')   # Green
    assert values[c.TX_PROTOCOL] == b'\x00'                  # CRMX
    assert values[c.LINK_ACTION] == b'\x03'                  # observed TX baseline


def test_sim_only_returns_readable_uuids():
    """Sim must not invent characteristics the read allowlist does not cover."""
    for os_id in SIM_DEVICE_IDS:
        assert set(sim_gatt_values(os_id)).issubset(c.READABLE_UUIDS)


def test_unknown_sim_device_returns_empty():
    assert sim_gatt_values('not-a-sim-device') == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run from `backend/`: `pytest tests/test_ble_sim.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.five12_ble.sim'`

- [ ] **Step 3: Write the implementation**

Create `backend/app/five12_ble/sim.py`:

```python
"""Fabricated BLE devices for ?sim=1 / FIVE12_DEVICE_SIM=1.

Values are the ACTUAL captured bytes from a RatPac Cintenna on firmware
1.0.7.2, not invented ones — developing the panel against fiction would hide
exactly the decoding bugs these fixtures exist to catch.

Two devices, one RX and one TX, because most of the panel's conditional
rendering keys off mode.
"""

import math
import time

from . import constants as c
from .advertisement import decode_manufacturer_data

SIM_RX_ID = 'sim-cintenna-rx'
SIM_TX_ID = 'sim-cintenna-tx'
SIM_DEVICE_IDS = (SIM_RX_ID, SIM_TX_ID)

_OBSERVED_MFR_PAYLOAD = bytes.fromhex('03F14000004C55F140')

_NAMES = {
    SIM_RX_ID: 'F12L - 1946',
    SIM_TX_ID: 'F12L - 2071',
}

_GATT = {
    SIM_RX_ID: {
        c.DEVICE_NAME: b'F12L - 1946\x00\x00\x00\x00\x00',
        c.MODE: b'\x00',                               # RX
        c.OUTPUT_POWER: b'\x80',                       # RX baseline
        c.UNIVERSE_COLOR: bytes.fromhex('F90000'),     # RX baseline
        c.DMX_HOLD: b'\x00',
        c.TX_PROTOCOL: b'\xff',                        # RX baseline
        c.FIRMWARE_VERSION: bytes.fromhex('02070001'), # 1.0.7.2
        c.BATTERY_LEVEL: b'\x41',                      # 65%
        c.MODE_MIRROR: b'\x00',
        c.COLOR_MIRROR: bytes.fromhex('F90000'),
        c.LINK_ACTION: b'\x01',                        # RX baseline
    },
    SIM_TX_ID: {
        c.DEVICE_NAME: b'F12L - 2071\x00\x00\x00\x00\x00',
        c.MODE: b'\x01',                               # TX
        c.OUTPUT_POWER: b'\x02',                       # Max
        c.UNIVERSE_COLOR: bytes.fromhex('00FF00'),     # Green
        c.DMX_HOLD: b'\x01',
        c.TX_PROTOCOL: b'\x00',                        # CRMX
        c.FIRMWARE_VERSION: bytes.fromhex('02070001'),
        c.BATTERY_LEVEL: b'\x64',                      # 100%
        c.MODE_MIRROR: b'\x01',
        c.COLOR_MIRROR: bytes.fromhex('00FF00'),
        c.LINK_ACTION: b'\x03',                        # TX baseline
    },
}


def _wobble(base, os_id, now=None):
    """Slow deterministic drift so the RSSI bars move like real ones."""
    now = time.time() if now is None else now
    phase = sum(ord(ch) for ch in os_id)
    return int(base + 6 * math.sin((now / 7.0) + phase))


def sim_advertisements(now=None):
    """(os_id, local_name, rssi, advert_dict) for every simulated device."""
    advert = decode_manufacturer_data(0xFFFF, _OBSERVED_MFR_PAYLOAD)
    return [
        (os_id, _NAMES[os_id], _wobble(-48 if os_id == SIM_RX_ID else -63, os_id, now), dict(advert))
        for os_id in SIM_DEVICE_IDS
    ]


def sim_gatt_values(os_id):
    """Raw bytes per UUID, as a real connected read would return them."""
    return dict(_GATT.get(os_id, {}))
```

- [ ] **Step 4: Run tests to verify they pass**

Run from `backend/`: `pytest tests/test_ble_sim.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/five12_ble/sim.py backend/tests/test_ble_sim.py
git commit -m "feat: add simulated Cintenna devices"
```

---

### Task 8: Scan service and single-owner lock

**Files:**
- Create: `backend/app/five12_ble/scanner.py`
- Test: `backend/tests/test_ble_scanner.py`

**Interfaces:**
- Consumes: `registry`, `advertisement`, `sim`, `errors` from Tasks 3, 5, 6, 7.
- Produces: `BleScanService(sim=False, stale_after=60.0)` with `.registry`, `.start()`, `.stop()`, `.status() -> dict`, `.handle_advertisement(os_id, name, rssi, service_uuids, manufacturer_data)`; module function `get_scan_service(sim)`; `start_ble_service(app)`.

`handle_advertisement` is deliberately separated from bleak so the filtering and registry logic is testable without a radio.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_ble_scanner.py`:

```python
"""The scan service filters what bleak reports and feeds the registry.

handle_advertisement is pure with respect to bleak — it takes plain values, so
the whole filter/decode/store path is testable with no radio and no event loop.
"""

from app.five12_ble import constants as c
from app.five12_ble.scanner import BleScanService

TIMOTWO_UUIDS = [c.TIMOTWO_SERVICE_UUID]
MFR = {0xFFFF: bytes.fromhex('03F14000004C55F140')}


def test_timotwo_advertisement_is_recorded():
    svc = BleScanService()
    svc.handle_advertisement('os-1', 'F12L - 1946', -41, TIMOTWO_UUIDS, MFR, now=100.0)
    assert svc.registry.count() == 1
    assert svc.registry.get('os-1').local_name == 'F12L - 1946'


def test_unrelated_ble_device_is_ignored():
    """A room full of phones, headphones, and laptops must not fill the roster."""
    svc = BleScanService()
    svc.handle_advertisement('os-phone', 'Someones iPhone', -55,
                             ['0000180f-0000-1000-8000-00805f9b34fb'],
                             {0x004C: b'\x01\x02'}, now=100.0)
    assert svc.registry.count() == 0


def test_manufacturer_data_alone_is_enough_evidence():
    """Some stacks drop service UUIDs from the advertisement; matching
    manufacturer data still identifies the platform."""
    svc = BleScanService()
    svc.handle_advertisement('os-1', 'F12L - 1946', -41, [], MFR, now=100.0)
    assert svc.registry.count() == 1


def test_service_uuid_alone_is_enough_evidence():
    svc = BleScanService()
    svc.handle_advertisement('os-1', 'F12L - 1946', -41, TIMOTWO_UUIDS, {}, now=100.0)
    assert svc.registry.count() == 1
    assert 'service-uuid' in svc.registry.get('os-1').advert['evidence']


def test_uppercase_service_uuid_still_matches():
    svc = BleScanService()
    svc.handle_advertisement('os-1', 'n', -41,
                             [c.TIMOTWO_SERVICE_UUID.upper()], {}, now=100.0)
    assert svc.registry.count() == 1


def test_malformed_manufacturer_data_does_not_raise():
    svc = BleScanService()
    svc.handle_advertisement('os-1', 'n', -41, TIMOTWO_UUIDS, {0xFFFF: b'\x03'}, now=100.0)
    assert svc.registry.count() == 1
    assert svc.registry.get('os-1').advert['hardwareId'] is None


def test_repeat_advertisements_coalesce():
    svc = BleScanService()
    for i in range(10):
        svc.handle_advertisement('os-1', 'n', -50, TIMOTWO_UUIDS, MFR, now=100.0 + i)
    assert svc.registry.count() == 1


def test_sim_service_populates_registry_without_hardware():
    svc = BleScanService(sim=True)
    svc.poll_sim(now=100.0)
    assert svc.registry.count() == 2
    assert svc.status()['sim'] is True


def test_status_reports_not_running_before_start():
    svc = BleScanService()
    st = svc.status()
    assert st['running'] is False
    assert st['deviceCount'] == 0


def test_sim_status_reports_adapter_available():
    """Sim mode must never claim it needs hardware, or the panel shows a
    hardware error during a demo."""
    svc = BleScanService(sim=True)
    assert svc.status()['adapterAvailable'] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run from `backend/`: `pytest tests/test_ble_scanner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.five12_ble.scanner'`

- [ ] **Step 3: Write the implementation**

Create `backend/app/five12_ble/scanner.py`:

```python
"""BLE scan service — owns the bleak event loop and feeds the registry.

Follows the daemon-thread pattern of app/scanner.py (the ARP sweep), with one
guard that module does not need: only ONE process may own the Bluetooth
adapter. Two workers redundantly ARP-pinging is merely wasteful; two contending
for one radio is broken.

bleak is imported lazily inside _run_loop so this module — and every test that
touches handle_advertisement — works without the dependency installed.
"""

import logging
import os
import tempfile
import threading
import time

from .advertisement import PLATFORM_TIMOTWO, decode_manufacturer_data, is_timotwo_service
from .constants import ACCEPTED_COMPANY_IDS
from .registry import Registry
from .sim import sim_advertisements

log = logging.getLogger(__name__)

SCAN_RESTART_DELAY = 5.0
SIM_POLL_INTERVAL = 2.0
_LOCK_PATH = os.path.join(tempfile.gettempdir(), 'five12-ble-adapter.lock')


class BleScanService:
    def __init__(self, sim=False, stale_after=60.0):
        self.sim = sim
        self.registry = Registry(stale_after=stale_after)
        self._thread = None
        self._stop = threading.Event()
        self._running = False
        self._adapter_available = sim
        self._last_error = None
        self._lock_handle = None

    # ── advertisement handling (pure w.r.t. bleak, hence directly testable) ──
    def handle_advertisement(self, os_id, name, rssi, service_uuids,
                             manufacturer_data, now=None):
        """Filter one advertisement and record it if it is TimoTwo evidence.

        Accepts either signal independently: some stacks drop service UUIDs
        from the advertisement while still carrying manufacturer data.
        """
        service_uuids = service_uuids or []
        manufacturer_data = manufacturer_data or {}

        by_service = any(is_timotwo_service(u) for u in service_uuids)

        advert, by_mfr = None, False
        for company_id, payload in manufacturer_data.items():
            if company_id not in ACCEPTED_COMPANY_IDS:
                continue
            advert = decode_manufacturer_data(company_id, payload)
            by_mfr = advert['platform'] == PLATFORM_TIMOTWO
            break

        if not (by_service or by_mfr):
            return None

        if advert is None:
            advert = decode_manufacturer_data(0, b'')
        advert = dict(advert)

        evidence = list(advert.get('evidence') or [])
        if by_service and 'service-uuid' not in evidence:
            evidence.insert(0, 'service-uuid')
        advert['evidence'] = evidence
        # Service-UUID match alone is sufficient platform evidence.
        advert['platform'] = PLATFORM_TIMOTWO
        advert['product'] = None

        return self.registry.upsert(os_id, name, rssi, advert, now=now)

    # ── sim ──
    def poll_sim(self, now=None):
        for os_id, name, rssi, advert in sim_advertisements(now=now):
            self.registry.upsert(os_id, name, rssi, advert, now=now)

    # ── lifecycle ──
    def _acquire_adapter_lock(self):
        """Exclusive OS-level lock so only one Five12 process scans. Under
        gunicorn every worker runs this module; only one may own the radio."""
        if self.sim:
            return True
        try:
            fd = os.open(_LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_RDWR)
        except FileExistsError:
            # A stale lock from a killed process would block scanning forever.
            try:
                if time.time() - os.path.getmtime(_LOCK_PATH) > 300:
                    os.unlink(_LOCK_PATH)
                    return self._acquire_adapter_lock()
            except OSError:
                pass
            return False
        except OSError:
            return False
        self._lock_handle = fd
        os.write(fd, str(os.getpid()).encode())
        return True

    def _release_adapter_lock(self):
        if self._lock_handle is not None:
            try:
                os.close(self._lock_handle)
                os.unlink(_LOCK_PATH)
            except OSError:
                pass
            self._lock_handle = None

    def start(self):
        if self._running:
            return
        if not self._acquire_adapter_lock():
            self._last_error = 'not-owner'
            log.info('BLE: another process owns the adapter; not scanning')
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._sim_loop if self.sim else self._run_loop,
            name='five12-ble-scan',
            daemon=True,
        )
        self._running = True
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._running = False
        self._release_adapter_lock()

    def status(self):
        return {
            'running': self._running,
            'sim': self.sim,
            'adapterAvailable': self._adapter_available,
            'deviceCount': len(self.registry.all()),
            'lastError': self._last_error,
        }

    # ── loops ──
    def _sim_loop(self):
        while not self._stop.is_set():
            self.poll_sim()
            self._stop.wait(SIM_POLL_INTERVAL)

    def _run_loop(self):
        """Own a bleak event loop for the life of the process.

        bleak is imported here, not at module scope, so the pure modules and
        their tests never require the dependency.
        """
        import asyncio

        try:
            from bleak import BleakScanner
        except ImportError:
            self._last_error = 'adapter-unavailable'
            self._adapter_available = False
            self._running = False
            log.error('BLE: bleak is not installed; scanning disabled')
            return

        def _on_advert(device, advertisement_data):
            try:
                self.handle_advertisement(
                    os_id=str(device.address),
                    name=advertisement_data.local_name or device.name,
                    rssi=advertisement_data.rssi,
                    service_uuids=advertisement_data.service_uuids,
                    manufacturer_data=advertisement_data.manufacturer_data,
                )
            except Exception as exc:   # one bad advert must not kill the scan
                log.debug('BLE: bad advertisement ignored: %s', exc)

        async def _scan_forever():
            while not self._stop.is_set():
                try:
                    async with BleakScanner(detection_callback=_on_advert):
                        self._adapter_available = True
                        self._last_error = None
                        while not self._stop.is_set():
                            await asyncio.sleep(0.5)
                except Exception as exc:
                    self._adapter_available = False
                    self._last_error = 'adapter-unavailable'
                    log.error('BLE scan error: %s', exc)
                    await asyncio.sleep(SCAN_RESTART_DELAY)

        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_scan_forever())
        finally:
            loop.close()
            self._running = False
            self._release_adapter_lock()


# ── module-level service registry (one per sim flag, like get_adapter) ───────
_services = {}
_services_lock = threading.Lock()


def get_scan_service(sim=False):
    key = bool(sim)
    with _services_lock:
        if key not in _services:
            _services[key] = BleScanService(sim=key)
        return _services[key]


def start_ble_service(app):
    """Called from the app factory when ENABLE_BLE_TOOLS is set."""
    from ..integrations import sim_enabled
    service = get_scan_service(sim_enabled())
    service.start()
    app.logger.info('BLE scan service started (sim=%s)', service.sim)
    return service
```

- [ ] **Step 4: Run tests to verify they pass**

Run from `backend/`: `pytest tests/test_ble_scanner.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/five12_ble/scanner.py backend/tests/test_ble_scanner.py
git commit -m "feat: add passive BLE scan service"
```

---

### Task 9: Connection manager and read-only snapshot

**Files:**
- Create: `backend/app/five12_ble/connection_manager.py`, `backend/app/five12_ble/gatt_client.py`
- Test: `backend/tests/test_ble_gatt_client.py`

**Interfaces:**
- Consumes: `constants`, `decoders`, `errors`, `sim`, `models` from Tasks 2, 4, 6, 7.
- Produces: `build_snapshot(client, os_id, now=None) -> dict` where `client` exposes `async read_gatt_char(uuid) -> bytes` and `has_characteristic(uuid) -> bool`; `build_sim_snapshot(os_id, now=None) -> dict`; `ConnectionManager.acquire(os_id)` context manager.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_ble_gatt_client.py`:

```python
"""Snapshot building. A single failed characteristic read must degrade to one
null field, never fail the whole device — a Cintenna missing one characteristic
is still worth showing battery and mode for."""

import asyncio

import pytest

from app.five12_ble import constants as c
from app.five12_ble.gatt_client import build_sim_snapshot, build_snapshot
from app.five12_ble.sim import SIM_RX_ID, SIM_TX_ID, sim_gatt_values


class FakeClient:
    """Stands in for a bleak client. Records reads, and NEVER offers a write
    method — this phase has no write path, so an accidental call fails loudly."""

    def __init__(self, values, failing=(), missing=()):
        self.values = values
        self.failing = set(failing)
        self.missing = set(missing)
        self.reads = []

    def has_characteristic(self, uuid):
        return uuid in self.values and uuid not in self.missing

    async def read_gatt_char(self, uuid):
        self.reads.append(uuid)
        if uuid in self.failing:
            raise RuntimeError('simulated read failure')
        return self.values[uuid]


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_snapshot_decodes_rx_device():
    client = FakeClient(sim_gatt_values(SIM_RX_ID))
    snap = _run(build_snapshot(client, SIM_RX_ID, now=100.0))
    assert snap['osId'] == SIM_RX_ID
    assert snap['fields']['mode']['decoded'] == 'rx'
    assert snap['fields']['battery']['decoded'] == 65
    assert snap['fields']['firmware']['decoded'] == '1.0.7.2'


def test_snapshot_decodes_tx_device():
    client = FakeClient(sim_gatt_values(SIM_TX_ID))
    snap = _run(build_snapshot(client, SIM_TX_ID, now=100.0))
    assert snap['fields']['mode']['decoded'] == 'tx'
    assert snap['fields']['outputPower']['decoded'] == 'max'
    assert snap['fields']['universeColor']['decoded'] == '#00FF00'
    assert snap['fields']['txProtocol']['decoded'] == 'crmx'


def test_every_field_carries_source_and_timestamp():
    client = FakeClient(sim_gatt_values(SIM_TX_ID))
    snap = _run(build_snapshot(client, SIM_TX_ID, now=100.0))
    for name, field in snap['fields'].items():
        assert field['source'] in ('gatt-read', 'mirror'), name
        assert field['readAt'] == 100.0, name


def test_one_failing_read_does_not_fail_the_device():
    client = FakeClient(sim_gatt_values(SIM_RX_ID), failing=[c.FIRMWARE_VERSION])
    snap = _run(build_snapshot(client, SIM_RX_ID, now=100.0))
    assert snap['fields']['firmware']['decoded'] is None
    assert snap['fields']['firmware']['error']
    assert snap['fields']['battery']['decoded'] == 65


def test_missing_characteristic_is_warned_not_fatal():
    client = FakeClient(sim_gatt_values(SIM_RX_ID), missing=[c.DMX_HOLD])
    snap = _run(build_snapshot(client, SIM_RX_ID, now=100.0))
    assert 'dmxHold' not in snap['fields']
    assert any('dmxHold' in w for w in snap['warnings'])


def test_snapshot_never_reads_outside_the_allowlist():
    client = FakeClient(sim_gatt_values(SIM_TX_ID))
    _run(build_snapshot(client, SIM_TX_ID, now=100.0))
    assert set(client.reads).issubset(c.READABLE_UUIDS)


def test_snapshot_never_reads_the_opaque_blob():
    client = FakeClient(sim_gatt_values(SIM_TX_ID))
    _run(build_snapshot(client, SIM_TX_ID, now=100.0))
    assert not any(r.startswith('10351003') for r in client.reads)


def test_snapshot_has_no_linked_field_anywhere():
    """ATT-level values are not evidence of RF association. Nothing in a
    snapshot may imply a receiver is linked."""
    client = FakeClient(sim_gatt_values(SIM_TX_ID))
    snap = _run(build_snapshot(client, SIM_TX_ID, now=100.0))
    assert 'linked' not in str(snap).lower().replace('unlinked', '')


def test_mirror_fields_are_sourced_as_mirror():
    client = FakeClient(sim_gatt_values(SIM_TX_ID))
    snap = _run(build_snapshot(client, SIM_TX_ID, now=100.0))
    assert snap['fields']['modeMirror']['source'] == 'mirror'


def test_sim_snapshot_matches_real_path():
    sim_snap = build_sim_snapshot(SIM_RX_ID, now=100.0)
    client = FakeClient(sim_gatt_values(SIM_RX_ID))
    real_snap = _run(build_snapshot(client, SIM_RX_ID, now=100.0))
    assert sim_snap['fields'].keys() == real_snap['fields'].keys()
    assert sim_snap['fields']['mode']['decoded'] == 'rx'


def test_sim_snapshot_unknown_device_returns_none():
    assert build_sim_snapshot('nope', now=100.0) is None


def test_fake_client_offers_no_write_method():
    """Structural check: this phase ships no write path."""
    assert not hasattr(FakeClient(sim_gatt_values(SIM_RX_ID)), 'write_gatt_char')
```

- [ ] **Step 2: Run test to verify it fails**

Run from `backend/`: `pytest tests/test_ble_gatt_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.five12_ble.gatt_client'`

- [ ] **Step 3: Write the connection manager**

Create `backend/app/five12_ble/connection_manager.py`:

```python
"""Single-owner BLE connections with bounded timeouts.

One connection operation per device at a time. Connections are explicit and
short-lived; nothing here connects on its own.

bleak is imported lazily so the pure modules stay importable without it.
"""

import asyncio
import contextlib
import logging
import threading

from .errors import (
    AdapterUnavailable,
    DeviceBusy,
    DeviceNotFound,
    OperationTimeout,
    ToolboxHoldingConnection,
)

log = logging.getLogger(__name__)

CONNECT_TIMEOUT = 12.0
READ_TIMEOUT = 6.0


class _DeviceLocks:
    """One lock per device, created on demand."""

    def __init__(self):
        self._locks = {}
        self._guard = threading.Lock()

    def for_device(self, os_id):
        with self._guard:
            if os_id not in self._locks:
                self._locks[os_id] = threading.Lock()
            return self._locks[os_id]


_device_locks = _DeviceLocks()


class BleakClientAdapter:
    """Wraps a bleak client in the tiny interface build_snapshot expects.

    Deliberately exposes only read operations. There is no write method on this
    class, and adding one is out of scope for the read-only phase.
    """

    def __init__(self, client):
        self._client = client
        self._uuids = {
            char.uuid.lower()
            for service in client.services
            for char in service.characteristics
        }

    def has_characteristic(self, uuid):
        return uuid.lower() in self._uuids

    async def read_gatt_char(self, uuid):
        return await asyncio.wait_for(
            self._client.read_gatt_char(uuid), timeout=READ_TIMEOUT
        )


@contextlib.asynccontextmanager
async def connect(os_id):
    """Connect to one device, yielding a read-only client adapter.

    Always disconnects, including on error. Raises a typed BleError the panel
    can render rather than a raw bleak exception.
    """
    try:
        from bleak import BleakClient
        from bleak.exc import BleakError
    except ImportError:
        raise AdapterUnavailable()

    lock = _device_locks.for_device(os_id)
    if not lock.acquire(blocking=False):
        raise DeviceBusy(detail=os_id)

    client = BleakClient(os_id, timeout=CONNECT_TIMEOUT)
    try:
        try:
            await asyncio.wait_for(client.connect(), timeout=CONNECT_TIMEOUT)
        except asyncio.TimeoutError:
            raise OperationTimeout(detail=os_id)
        except BleakError as exc:
            # Windows reports an in-use peripheral as a generic connect
            # failure. CRMX Toolbox holding the connection is by far the most
            # likely cause in the field, so name it rather than guessing.
            text = str(exc).lower()
            if 'in use' in text or 'access' in text or 'busy' in text:
                raise ToolboxHoldingConnection(detail=os_id)
            raise DeviceNotFound(detail=str(exc))

        yield BleakClientAdapter(client)
    finally:
        with contextlib.suppress(Exception):
            await client.disconnect()
        lock.release()
```

- [ ] **Step 4: Write the snapshot builder**

Create `backend/app/five12_ble/gatt_client.py`:

```python
"""Read-only connected status snapshot.

Reads only characteristics in the verified allowlist that the device actually
advertises. A per-field failure yields one null field with an error string; it
never fails the whole device.

This module contains no write path.
"""

import time

from . import constants as c
from . import decoders as d
from .sim import sim_gatt_values

# field name → (uuid, decoder, source). Order is the read order.
_FIELDS = (
    ('name', c.DEVICE_NAME, d.decode_name, 'gatt-read'),
    ('battery', c.BATTERY_LEVEL, d.decode_battery, 'gatt-read'),
    ('firmware', c.FIRMWARE_VERSION, d.decode_firmware, 'gatt-read'),
    ('mode', c.MODE, d.decode_mode, 'gatt-read'),
    ('dmxHold', c.DMX_HOLD, d.decode_dmx_hold, 'gatt-read'),
    ('outputPower', c.OUTPUT_POWER, d.decode_output_power, 'gatt-read'),
    ('universeColor', c.UNIVERSE_COLOR, d.decode_universe_color, 'gatt-read'),
    ('txProtocol', c.TX_PROTOCOL, d.decode_tx_protocol, 'gatt-read'),
    ('modeMirror', c.MODE_MIRROR, d.decode_mode, 'mirror'),
    ('colorMirror', c.COLOR_MIRROR, d.decode_universe_color, 'mirror'),
    ('linkStatus', c.LINK_ACTION, d.decode_link_status, 'mirror'),
)


def _finish(decoded, source, now, error=None):
    out = dict(decoded)
    out['source'] = source
    out['readAt'] = now
    if error:
        out['error'] = error
        out['decoded'] = None
    return out


async def build_snapshot(client, os_id, now=None):
    """Read every allowlisted characteristic the device exposes.

    `client` needs only `has_characteristic(uuid)` and
    `async read_gatt_char(uuid) -> bytes`, which keeps this testable with a
    fake and keeps bleak out of this module entirely.
    """
    now = time.time() if now is None else now
    fields, warnings = {}, []

    for name, uuid, decoder, source in _FIELDS:
        if not client.has_characteristic(uuid):
            warnings.append(f'{name}: characteristic not present on this device')
            continue
        try:
            raw = await client.read_gatt_char(uuid)
            fields[name] = _finish(decoder(raw), source, now)
        except Exception as exc:
            fields[name] = _finish(decoder(b''), source, now, error=str(exc))

    return {
        'osId': os_id,
        'readAt': now,
        'fields': fields,
        'warnings': warnings,
    }


def build_sim_snapshot(os_id, now=None):
    """Same shape as build_snapshot, without a radio or an event loop."""
    values = sim_gatt_values(os_id)
    if not values:
        return None
    now = time.time() if now is None else now
    fields = {
        name: _finish(decoder(values[uuid]), source, now)
        for name, uuid, decoder, source in _FIELDS
        if uuid in values
    }
    return {'osId': os_id, 'readAt': now, 'fields': fields, 'warnings': []}
```

- [ ] **Step 5: Run tests to verify they pass**

Run from `backend/`: `pytest tests/test_ble_gatt_client.py -v`
Expected: 12 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/five12_ble/connection_manager.py backend/app/five12_ble/gatt_client.py backend/tests/test_ble_gatt_client.py
git commit -m "feat: read Cintenna BLE status snapshot"
```

---

### Task 10: CintennaAdapter and Devices integration

**Files:**
- Create: `backend/app/integrations/cintenna.py`
- Modify: `backend/app/integrations/__init__.py:125-141`
- Test: `backend/tests/test_ble_adapter.py`

**Interfaces:**
- Consumes: `scanner.get_scan_service` from Task 8.
- Produces: `CintennaAdapter(sim=False)` with `id = 'cintenna'`, `name = 'Cintenna (CRMX)'`, `detect()`, `get_status()`. `ALL_DEVICE_IDS` gains `'cintenna'`.

**This is the task that makes the tab appear.**

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_ble_adapter.py`:

```python
"""CintennaAdapter is the bridge between the BLE service and the existing
Devices page. Adding it to ALL_DEVICE_IDS is what makes the tab render."""

from app.integrations import ALL_DEVICE_IDS, get_adapter
from app.integrations.cintenna import CintennaAdapter


def test_cintenna_is_a_known_device_id():
    assert 'cintenna' in ALL_DEVICE_IDS


def test_get_adapter_returns_cintenna():
    adapter = get_adapter('cintenna', sim=True)
    assert isinstance(adapter, CintennaAdapter)
    assert adapter.id == 'cintenna'


def test_adapter_is_cached_per_sim_flag():
    assert get_adapter('cintenna', sim=True) is get_adapter('cintenna', sim=True)
    assert get_adapter('cintenna', sim=True) is not get_adapter('cintenna', sim=False)


def test_detect_reports_found_in_sim_with_device_count():
    adapter = get_adapter('cintenna', sim=True)
    adapter.service.poll_sim()
    det = adapter.detect()
    assert det['found'] is True
    assert '2' in det['detail']


def test_status_lists_devices_and_is_camel_case():
    adapter = get_adapter('cintenna', sim=True)
    adapter.service.poll_sim()
    status = adapter.get_status()
    assert status['available'] is True
    assert 'alerts' in status
    assert len(status['devices']) == 2
    assert 'osId' in status['devices'][0]


def test_status_devices_carry_no_gatt_fields():
    """The roster is advertisement-only. Nearby is not connected."""
    adapter = get_adapter('cintenna', sim=True)
    adapter.service.poll_sim()
    for dev in adapter.get_status()['devices']:
        for forbidden in ('battery', 'firmware', 'mode', 'linked'):
            assert forbidden not in dev


def test_devices_route_includes_cintenna(client):
    """The whole point: GET /api/devices must return a cintenna entry, because
    Devices.jsx renders its tab strip from that response."""
    resp = client.get('/api/devices?sim=1')
    assert resp.status_code == 200
    ids = [d['id'] for d in resp.get_json()]
    assert 'cintenna' in ids


def test_devices_route_cintenna_entry_shape(client):
    entry = next(d for d in client.get('/api/devices?sim=1').get_json()
                 if d['id'] == 'cintenna')
    assert entry['name']
    assert 'found' in entry
    assert 'detail' in entry
```

- [ ] **Step 2: Run test to verify it fails**

Run from `backend/`: `pytest tests/test_ble_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.integrations.cintenna'`

- [ ] **Step 3: Write the adapter**

Create `backend/app/integrations/cintenna.py`:

```python
"""Cintenna (LumenRadio TimoTwo / CRMX) adapter — read-only BLE inventory.

Unlike the Starlink, Bolero, and Stardust adapters this one does NOT talk to
its devices on demand: BLE is async and scanning is continuous, so a background
service owns the radio (see app/five12_ble/scanner.py) and this adapter is a
thin synchronous reader over its registry. No method here blocks on radio I/O.

Read-only. Configuration writes, TX Link, and RX Unlink are a later, separately
gated piece of work.
"""

from . import DeviceAdapter
from ..five12_ble.scanner import get_scan_service


class CintennaAdapter(DeviceAdapter):
    id = 'cintenna'
    name = 'Cintenna (CRMX)'

    def __init__(self, sim=False):
        super().__init__()
        self.sim = sim
        self.service = get_scan_service(sim)

    def detect(self):
        st = self.service.status()
        count = st['deviceCount']

        if not st['adapterAvailable']:
            return {
                'found': False,
                'address': None,
                'detail': 'no Bluetooth adapter',
            }
        if st.get('lastError') == 'not-owner':
            return {
                'found': False,
                'address': None,
                'detail': 'another Five12 process owns the adapter',
            }
        return {
            'found': count > 0,
            'address': None,   # BLE has no network address
            'detail': (
                f'{count} nearby' if count
                else ('scanning — none nearby' if st['running'] else 'not scanning')
            ),
        }

    def get_status(self):
        st = self.service.status()
        devices = [d.to_dict() for d in self.service.registry.all()]
        status = {
            'available': st['adapterAvailable'],
            'scanning': st['running'],
            'sim': st['sim'],
            'deviceCount': len(devices),
            'devices': devices,
            'alerts': [],
        }
        if not st['adapterAvailable']:
            status['alerts'] = [{
                'level': 'warn',
                'message': 'No Bluetooth adapter available — Cintennas cannot be discovered',
            }]
        return status
```

- [ ] **Step 4: Register it**

In `backend/app/integrations/__init__.py`, replace the body of `get_adapter` (currently lines 125–138) so the imports and class map include Cintenna:

```python
def get_adapter(device_id, sim):
    """Adapters are cached per (device, sim) so history accumulates."""
    from .starlink import StarlinkAdapter
    from .bolero import BoleroAdapter
    from .stardust import StardustAdapter
    from .cintenna import CintennaAdapter
    classes = {
        'starlink': StarlinkAdapter,
        'bolero': BoleroAdapter,
        'stardust': StardustAdapter,
        'cintenna': CintennaAdapter,
    }
    cls = classes.get(device_id)
    if cls is None:
        return None
    key = (device_id, bool(sim))
    with _registry_lock:
        if key not in _registry:
            _registry[key] = cls(sim=bool(sim))
        return _registry[key]
```

And on the last line of the file:

```python
ALL_DEVICE_IDS = ('starlink', 'bolero', 'stardust', 'cintenna')
```

- [ ] **Step 5: Run tests to verify they pass**

Run from `backend/`: `pytest tests/test_ble_adapter.py -v`
Expected: 8 passed.

- [ ] **Step 6: Confirm the other adapters still work**

Run from `backend/`: `pytest`
Expected: all tests pass, including the pre-existing Starlink/Bolero/Stardust suites.

- [ ] **Step 7: Commit**

```bash
git add backend/app/integrations/cintenna.py backend/app/integrations/__init__.py backend/tests/test_ble_adapter.py
git commit -m "feat: add Cintenna adapter to device detection"
```

---

### Task 11: BLE read endpoints

**Files:**
- Modify: `backend/app/ble_routes.py`
- Modify: `backend/app/__init__.py` (start the scan service)
- Test: `backend/tests/test_ble_routes.py`

**Interfaces:**
- Consumes: Tasks 8, 9, 10.
- Produces: `GET /api/ble/devices`, `GET /api/ble/devices/<os_id>/snapshot`, `GET /api/ble/status`; updated `GET /api/ble/capabilities`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_ble_routes.py`:

```python
"""BLE read endpoints. Every route in this module is read-only; there is no
POST anywhere in this phase."""

import pytest

from app import create_app


@pytest.fixture(scope='module')
def ble_app():
    return create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'ENABLE_BLE_TOOLS': True,
    })


@pytest.fixture
def ble_client(ble_app):
    return ble_app.test_client()


def test_capabilities_reports_sim_adapter_available(ble_client):
    body = ble_client.get('/api/ble/capabilities?sim=1').get_json()
    assert body['bleToolsEnabled'] is True
    assert body['adapterAvailable'] is True


def test_devices_lists_simulated_radios(ble_client):
    body = ble_client.get('/api/ble/devices?sim=1').get_json()
    assert body['deviceCount'] == 2
    assert {d['localName'] for d in body['devices']} == {'F12L - 1946', 'F12L - 2071'}


def test_devices_are_advertisement_only(ble_client):
    body = ble_client.get('/api/ble/devices?sim=1').get_json()
    for dev in body['devices']:
        assert dev['platform'] == 'lumenradio-timotwo-compatible'
        assert dev['product'] is None
        assert 'battery' not in dev


def test_snapshot_returns_decoded_fields(ble_client):
    body = ble_client.get('/api/ble/devices/sim-cintenna-tx/snapshot?sim=1').get_json()
    assert body['fields']['mode']['decoded'] == 'tx'
    assert body['fields']['firmware']['decoded'] == '1.0.7.2'
    assert body['fields']['outputPower']['toolboxLabel'] == '>100 mW'


def test_snapshot_unknown_device_404s(ble_client):
    resp = ble_client.get('/api/ble/devices/nope/snapshot?sim=1')
    assert resp.status_code == 404
    assert resp.get_json()['code'] == 'device-not-found'


def test_status_reports_scan_state(ble_client):
    body = ble_client.get('/api/ble/status?sim=1').get_json()
    assert 'running' in body
    assert body['sim'] is True


def test_no_post_routes_exist_in_this_phase(ble_app):
    """RELEASE GATE. The read-only phase must expose no mutating endpoint."""
    for rule in ble_app.url_map.iter_rules():
        if str(rule).startswith('/api/ble'):
            assert rule.methods & {'POST', 'PUT', 'PATCH', 'DELETE'} == set(), str(rule)
```

- [ ] **Step 2: Run test to verify it fails**

Run from `backend/`: `pytest tests/test_ble_routes.py -v`
Expected: FAIL — `/api/ble/devices` 404s.

- [ ] **Step 3: Replace the routes module**

Replace the whole of `backend/app/ble_routes.py`:

```python
"""Bluetooth device routes — read-only CRMX/TimoTwo discovery.

Registered ONLY when ENABLE_BLE_TOOLS is set, so with the gate off these
routes do not exist rather than returning 403.

Every route here is a GET. This module contains no write path: configuration
writes, TX Link, and RX Unlink are a later, separately gated piece of work.
"""

import asyncio
import sys

from flask import Blueprint, jsonify, request

from .five12_ble.errors import BleError, DeviceNotFound
from .five12_ble.gatt_client import build_sim_snapshot, build_snapshot
from .five12_ble.scanner import get_scan_service
from .integrations import sim_enabled

ble = Blueprint('ble', __name__, url_prefix='/api/ble')


def _platform_supported():
    """bleak supports Windows 10+ / macOS / Linux with BlueZ. Five12's target
    is Windows 11; anything else is 'works, unverified' rather than a hard no."""
    return sys.platform in ('win32', 'darwin', 'linux')


def _service():
    return get_scan_service(sim_enabled(request.args))


@ble.get('/capabilities')
def capabilities():
    st = _service().status()
    return jsonify({
        'bleToolsEnabled': True,   # this route only exists when the gate is on
        'adapterAvailable': st['adapterAvailable'],
        'platformSupported': _platform_supported(),
        'sim': st['sim'],
    })


@ble.get('/status')
def status():
    return jsonify(_service().status())


@ble.get('/devices')
def list_devices():
    """Nearby radios, from passive advertisements only.

    NEARBY IS NOT CONNECTED — entries carry no GATT fields. Battery, firmware,
    and mode appear only after an explicit snapshot request.
    """
    service = _service()
    if service.sim:
        service.poll_sim()
    devices = [d.to_dict() for d in service.registry.all()]
    return jsonify({'deviceCount': len(devices), 'devices': devices})


@ble.get('/devices/<os_id>/snapshot')
def device_snapshot(os_id):
    """Connect, read the allowlisted characteristics, disconnect."""
    service = _service()

    if service.sim:
        snap = build_sim_snapshot(os_id)
        if snap is None:
            return jsonify(DeviceNotFound(detail=os_id).to_dict()), 404
        return jsonify(snap)

    if service.registry.get(os_id) is None:
        return jsonify(DeviceNotFound(detail=os_id).to_dict()), 404

    try:
        return jsonify(asyncio.run(_read_snapshot(os_id)))
    except BleError as exc:
        return jsonify(exc.to_dict()), 409


async def _read_snapshot(os_id):
    from .five12_ble.connection_manager import connect
    async with connect(os_id) as client:
        return await build_snapshot(client, os_id)
```

- [ ] **Step 4: Start the scan service in the factory**

In `backend/app/__init__.py`, replace the BLE block added in Task 1 with:

```python
    # Bluetooth (CRMX/TimoTwo discovery) registers only when explicitly enabled.
    # Default is OFF — see config.ENABLE_BLE_TOOLS. With the gate off no scan
    # thread starts and /api/ble/* does not exist.
    if app.config.get('ENABLE_BLE_TOOLS'):
        from .ble_routes import ble as ble_bp
        app.register_blueprint(ble_bp)

        # Not under TESTING: tests drive the registry directly and must not
        # spawn a radio thread. Only one process wins the adapter lock, so
        # under gunicorn the other workers no-op here.
        if not app.config.get('TESTING'):
            from .five12_ble.scanner import start_ble_service
            start_ble_service(app)
```

- [ ] **Step 5: Run tests to verify they pass**

Run from `backend/`: `pytest tests/test_ble_routes.py -v`
Expected: 7 passed.

- [ ] **Step 6: Run the whole backend suite**

Run from `backend/`: `pytest`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/ble_routes.py backend/app/__init__.py backend/tests/test_ble_routes.py
git commit -m "feat: expose read-only BLE device API"
```

---

### Task 12: Frontend test infrastructure and API wrapper

**Files:**
- Modify: `app/package.json`
- Modify: `app/vite.config.mjs`
- Create: `app/src/test/setup.js`, `app/src/lib/bleApi.js`, `app/src/lib/bleApi.test.js`

**Interfaces:**
- Consumes: Task 11's endpoints.
- Produces: `npm run test`; `bleApi.js` exporting `fetchBleDevices()`, `fetchBleSnapshot(osId)`, `fetchBleCapabilities()`, `signalBars(rssi)`.

- [ ] **Step 1: Install the test dependencies**

Run from `app/`:

```bash
npm install -D vitest@^2 jsdom @testing-library/react@^16 @testing-library/jest-dom @testing-library/user-event
```

React Testing Library v16 is required — earlier majors do not support React 19.

- [ ] **Step 2: Add the test scripts**

In `app/package.json`, add to `"scripts"` alongside the existing `dev`, `build`, `preview`:

```json
    "test": "vitest run",
    "test:watch": "vitest"
```

- [ ] **Step 3: Configure Vitest**

In `app/vite.config.mjs`, add a `test` block inside `defineConfig({...})`, after `plugins`:

```javascript
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.js',
  },
```

- [ ] **Step 4: Create the setup file**

Create `app/src/test/setup.js`:

```javascript
import '@testing-library/jest-dom'
```

- [ ] **Step 5: Write the failing test**

Create `app/src/lib/bleApi.test.js`:

```javascript
import { describe, expect, it, vi, beforeEach } from 'vitest'
import axios from 'axios'
import { fetchBleDevices, fetchBleSnapshot, fetchBleCapabilities, signalBars } from './bleApi'

vi.mock('axios')

beforeEach(() => { vi.resetAllMocks() })

describe('bleApi', () => {
  it('fetches the device roster', async () => {
    axios.get.mockResolvedValue({ data: { deviceCount: 1, devices: [{ osId: 'a' }] } })
    const out = await fetchBleDevices()
    expect(axios.get).toHaveBeenCalledWith('/api/ble/devices')
    expect(out.devices).toHaveLength(1)
  })

  it('returns an empty roster when the backend is unreachable', async () => {
    // The BLE gate defaults off, so 404 is the NORMAL case, not an error the
    // operator should see as a crash.
    axios.get.mockRejectedValue(new Error('404'))
    expect(await fetchBleDevices()).toEqual({ deviceCount: 0, devices: [], unavailable: true })
  })

  it('encodes the device id in the snapshot URL', async () => {
    axios.get.mockResolvedValue({ data: { fields: {} } })
    await fetchBleSnapshot('AA:BB:CC:DD:EE:FF')
    expect(axios.get).toHaveBeenCalledWith('/api/ble/devices/AA%3ABB%3ACC%3ADD%3AEE%3AFF/snapshot')
  })

  it('surfaces a typed backend error from a snapshot', async () => {
    axios.get.mockRejectedValue({
      response: { data: { code: 'toolbox-holding-connection', message: 'Close Toolbox.' } },
    })
    await expect(fetchBleSnapshot('a')).rejects.toMatchObject({
      code: 'toolbox-holding-connection',
    })
  })

  it('reports capabilities as disabled when the route is absent', async () => {
    axios.get.mockRejectedValue(new Error('404'))
    expect(await fetchBleCapabilities()).toEqual({
      bleToolsEnabled: false, adapterAvailable: false, platformSupported: true,
    })
  })

  it('maps RSSI to bars without ever implying distance', () => {
    expect(signalBars(-35)).toBe(4)
    expect(signalBars(-60)).toBe(3)
    expect(signalBars(-75)).toBe(2)
    expect(signalBars(-95)).toBe(1)
    expect(signalBars(null)).toBe(0)
  })
})
```

- [ ] **Step 6: Run test to verify it fails**

Run from `app/`: `npm run test`
Expected: FAIL — cannot resolve `./bleApi`.

- [ ] **Step 7: Write the implementation**

Create `app/src/lib/bleApi.js`:

```javascript
// Wrapper for /api/ble/*. Those routes exist only when FIVE12_BLE_TOOLS=1, so
// a 404 is a normal state (feature off), not a failure to shout about.
import axios from 'axios'

export async function fetchBleCapabilities() {
  try {
    const { data } = await axios.get('/api/ble/capabilities')
    return data
  } catch {
    return { bleToolsEnabled: false, adapterAvailable: false, platformSupported: true }
  }
}

export async function fetchBleDevices() {
  try {
    const { data } = await axios.get('/api/ble/devices')
    return data
  } catch {
    return { deviceCount: 0, devices: [], unavailable: true }
  }
}

export async function fetchBleSnapshot(osId) {
  try {
    const { data } = await axios.get(`/api/ble/devices/${encodeURIComponent(osId)}/snapshot`)
    return data
  } catch (err) {
    // The backend sends typed errors with operator-ready copy; pass them
    // through rather than replacing them with a generic message.
    const payload = err?.response?.data
    throw payload?.code ? payload : { code: 'unknown', message: 'Could not read this device.' }
  }
}

// RSSI → 0-4 bars. Deliberately NOT a distance: signal strength depends on
// orientation, obstruction, and antenna, so the UI shows bars and raw dBm only.
export function signalBars(rssi) {
  if (typeof rssi !== 'number') return 0
  if (rssi >= -50) return 4
  if (rssi >= -65) return 3
  if (rssi >= -80) return 2
  return 1
}
```

- [ ] **Step 8: Run tests to verify they pass**

Run from `app/`: `npm run test`
Expected: 6 passed.

- [ ] **Step 9: Commit**

```bash
git add app/package.json app/package-lock.json app/vite.config.mjs app/src/test/setup.js app/src/lib/bleApi.js app/src/lib/bleApi.test.js
git commit -m "test: add Vitest and BLE API wrapper"
```

---

### Task 13: Cintennas panel and tab

**Files:**
- Create: `app/src/components/devices/BleEvidenceBadge.jsx`, `app/src/components/devices/CintennaPanel.jsx`, `app/src/components/devices/CintennaPanel.test.jsx`
- Modify: `app/src/pages/Devices.jsx:473-477` (the `PANELS` map)

**Interfaces:**
- Consumes: `bleApi.js` from Task 12.
- Produces: `CintennaPanel` default export; `PANELS.cintenna`.

- [ ] **Step 1: Write the failing test**

Create `app/src/components/devices/CintennaPanel.test.jsx`:

```jsx
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import CintennaPanel from './CintennaPanel'
import * as bleApi from '../../lib/bleApi'

vi.mock('../../lib/bleApi')

const DEVICES = {
  deviceCount: 2,
  devices: [
    { osId: 'rx-1', localName: 'F12L - 1946', rssi: -41, rssiSmoothed: -41,
      platform: 'lumenradio-timotwo-compatible', product: null,
      hardwareId: 'F1400000', evidence: ['service-uuid', 'manufacturer-data'],
      firstSeen: 100, lastSeen: 160 },
    { osId: 'tx-1', localName: 'F12L - 2071', rssi: -70, rssiSmoothed: -70,
      platform: 'lumenradio-timotwo-compatible', product: null,
      hardwareId: 'F1400000', evidence: ['manufacturer-data'],
      firstSeen: 100, lastSeen: 160 },
  ],
}

const SNAPSHOT = {
  osId: 'rx-1',
  fields: {
    name: { decoded: 'F12L - 1946', raw: '', source: 'gatt-read', readAt: 1 },
    battery: { decoded: 65, raw: '41', source: 'gatt-read', readAt: 1 },
    firmware: { decoded: '1.0.7.2', raw: '02070001', source: 'gatt-read', readAt: 1 },
    mode: { decoded: 'rx', raw: '00', source: 'gatt-read', readAt: 1 },
    dmxHold: { decoded: false, raw: '00', source: 'gatt-read', readAt: 1 },
  },
  warnings: [],
}

beforeEach(() => {
  vi.resetAllMocks()
  bleApi.signalBars.mockReturnValue(3)
})

describe('CintennaPanel', () => {
  it('lists nearby radios', async () => {
    bleApi.fetchBleDevices.mockResolvedValue(DEVICES)
    render(<CintennaPanel />)
    expect(await screen.findByText('F12L - 1946')).toBeInTheDocument()
    expect(screen.getByText('F12L - 2071')).toBeInTheDocument()
  })

  it('labels the platform without claiming an enclosure model', async () => {
    bleApi.fetchBleDevices.mockResolvedValue(DEVICES)
    render(<CintennaPanel />)
    await screen.findByText('F12L - 1946')
    expect(screen.getAllByText(/TimoTwo-compatible/i).length).toBeGreaterThan(0)
    expect(screen.queryByText(/Cintenna 2/)).not.toBeInTheDocument()
  })

  it('shows no battery or firmware before connecting', async () => {
    // Nearby is not connected. The roster is advertisement-only.
    bleApi.fetchBleDevices.mockResolvedValue(DEVICES)
    render(<CintennaPanel />)
    await screen.findByText('F12L - 1946')
    expect(screen.queryByText(/65%/)).not.toBeInTheDocument()
    expect(screen.queryByText(/1\.0\.7\.2/)).not.toBeInTheDocument()
  })

  it('reads a snapshot when the operator asks for one', async () => {
    bleApi.fetchBleDevices.mockResolvedValue(DEVICES)
    bleApi.fetchBleSnapshot.mockResolvedValue(SNAPSHOT)
    render(<CintennaPanel />)
    await userEvent.click(await screen.findByRole('button', { name: /F12L - 1946/ }))
    await userEvent.click(screen.getByRole('button', { name: /read status/i }))
    expect(await screen.findByText(/65%/)).toBeInTheDocument()
    expect(screen.getByText('1.0.7.2')).toBeInTheDocument()
  })

  it('shows the operator message for a Toolbox conflict', async () => {
    bleApi.fetchBleDevices.mockResolvedValue(DEVICES)
    bleApi.fetchBleSnapshot.mockRejectedValue({
      code: 'toolbox-holding-connection',
      message: 'CRMX Toolbox appears to be connected to this device. Close it completely.',
    })
    render(<CintennaPanel />)
    await userEvent.click(await screen.findByRole('button', { name: /F12L - 1946/ }))
    await userEvent.click(screen.getByRole('button', { name: /read status/i }))
    expect(await screen.findByText(/CRMX Toolbox/)).toBeInTheDocument()
  })

  it('explains itself when BLE tools are switched off', async () => {
    bleApi.fetchBleDevices.mockResolvedValue({ deviceCount: 0, devices: [], unavailable: true })
    render(<CintennaPanel />)
    expect(await screen.findByText(/FIVE12_BLE_TOOLS/)).toBeInTheDocument()
  })

  it('says so when scanning finds nothing', async () => {
    bleApi.fetchBleDevices.mockResolvedValue({ deviceCount: 0, devices: [] })
    render(<CintennaPanel />)
    expect(await screen.findByText(/no CRMX devices nearby/i)).toBeInTheDocument()
  })

  it('renders no control that could write to a radio', async () => {
    // RELEASE GATE for this phase.
    bleApi.fetchBleDevices.mockResolvedValue(DEVICES)
    bleApi.fetchBleSnapshot.mockResolvedValue(SNAPSHOT)
    render(<CintennaPanel />)
    await userEvent.click(await screen.findByRole('button', { name: /F12L - 1946/ }))
    for (const label of [/^link$/i, /unlink/i, /set mode/i, /apply/i]) {
      expect(screen.queryByRole('button', { name: label })).not.toBeInTheDocument()
    }
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run from `app/`: `npm run test`
Expected: FAIL — cannot resolve `./CintennaPanel`.

- [ ] **Step 3: Write the evidence badge**

Create `app/src/components/devices/BleEvidenceBadge.jsx`:

```jsx
// Shows WHERE a value came from. The distinction matters: an advertisement is
// passive and proves only presence, while a GATT read required a connection.
const LABELS = {
  'service-uuid': 'service UUID',
  'manufacturer-data': 'mfr data',
  'gatt-read': 'GATT read',
  mirror: 'mirror',
  sim: 'simulated',
}

export default function BleEvidenceBadge({ source }) {
  if (!source) return null
  return (
    <span className="text-[8px] font-mono px-1 py-[1px] rounded-sm border border-[var(--color-border)] text-text-muted">
      {LABELS[source] || source}
    </span>
  )
}
```

- [ ] **Step 4: Write the panel**

Create `app/src/components/devices/CintennaPanel.jsx`:

```jsx
import { useEffect, useState } from 'react'
import { fetchBleDevices, fetchBleSnapshot, signalBars } from '../../lib/bleApi'
import BleEvidenceBadge from './BleEvidenceBadge'

// Language rules from the verified protocol reference, enforced in copy:
//   "nearby" is not "connected"      — the roster carries no GATT fields
//   "TimoTwo-compatible" is not      — the radio platform does not identify
//     "Cintenna 2"                     the enclosure
//   RSSI is not distance             — bars and raw dBm only, never metres

function Bars({ rssi }) {
  const bars = signalBars(rssi)
  return (
    <span className="inline-flex items-end gap-[2px] h-3" title={`${rssi} dBm`}>
      {[1, 2, 3, 4].map((n) => (
        <span
          key={n}
          className={'w-[3px] ' + (n <= bars ? 'bg-brand' : 'bg-[var(--color-surface-2)]')}
          style={{ height: `${n * 25}%` }}
        />
      ))}
    </span>
  )
}

function Field({ label, value, source, suffix = '' }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-[2px]">
      <span className="text-[9px] font-mono text-text-muted uppercase">{label}</span>
      <span className="flex items-center gap-2">
        <span className="text-[11px] font-mono text-text">
          {value === null || value === undefined ? '—' : `${value}${suffix}`}
        </span>
        <BleEvidenceBadge source={source} />
      </span>
    </div>
  )
}

export default function CintennaPanel() {
  const [roster, setRoster] = useState(null)
  const [selected, setSelected] = useState(null)
  const [snapshot, setSnapshot] = useState(null)
  const [snapError, setSnapError] = useState(null)
  const [reading, setReading] = useState(false)

  useEffect(() => {
    let alive = true
    const poll = async () => {
      const data = await fetchBleDevices()
      if (alive) setRoster(data)
    }
    poll()
    const i = setInterval(poll, 5000)
    return () => { alive = false; clearInterval(i) }
  }, [])

  const readStatus = async () => {
    setReading(true)
    setSnapError(null)
    setSnapshot(null)
    try {
      setSnapshot(await fetchBleSnapshot(selected.osId))
    } catch (err) {
      setSnapError(err)
    } finally {
      setReading(false)
    }
  }

  if (!roster) {
    return <div className="text-[10px] font-mono text-text-muted py-2">scanning…</div>
  }

  if (roster.unavailable) {
    return (
      <div className="text-[10px] font-mono text-text-muted py-2 leading-relaxed">
        Bluetooth tools are switched off.<br />
        Set <span className="text-text">FIVE12_BLE_TOOLS=1</span> and restart the
        backend to discover CRMX devices.
      </div>
    )
  }

  const fields = snapshot?.fields || {}

  return (
    <div className="space-y-3">
      <div className="text-[9px] font-mono text-text-muted">
        passive Bluetooth scan · nearby is not connected · signal strength is not distance
      </div>

      {roster.devices.length === 0 && (
        <div className="text-[10px] font-mono text-text-muted py-2">
          no CRMX devices nearby
        </div>
      )}

      <div className="flex gap-2 flex-wrap">
        {roster.devices.map((d) => (
          <button
            key={d.osId}
            onClick={() => { setSelected(d); setSnapshot(null); setSnapError(null) }}
            className={'text-left px-3 py-2 rounded-sm border min-w-[200px] ' +
              (selected?.osId === d.osId
                ? 'border-brand bg-brand-dim/30'
                : 'border-[var(--color-border)] bg-[var(--color-surface)] hover:border-border')}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-mono font-bold text-text">
                {d.localName || '(unnamed)'}
              </span>
              <Bars rssi={d.rssiSmoothed} />
            </div>
            <div className="text-[8px] font-mono text-text-muted mt-[2px]">
              TimoTwo-compatible · {d.rssi} dBm
            </div>
            <div className="flex gap-1 mt-1">
              {(d.evidence || []).map((e) => <BleEvidenceBadge key={e} source={e} />)}
            </div>
          </button>
        ))}
      </div>

      {selected && (
        <div className="border border-[var(--color-border)] rounded-sm p-3 max-w-md">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] font-mono font-bold text-text">
              {selected.localName}
            </span>
            <button
              onClick={readStatus}
              disabled={reading}
              className="text-[9px] font-mono px-2 py-1 border border-[var(--color-border)] rounded-sm hover:border-brand disabled:opacity-40"
            >
              {reading ? 'reading…' : 'Read status'}
            </button>
          </div>

          <Field label="hardware id" value={selected.hardwareId} source="manufacturer-data" />

          {snapError && (
            <div className="text-[10px] font-mono text-amber-400 mt-2 leading-relaxed">
              {snapError.message}
            </div>
          )}

          {snapshot && (
            <div className="mt-2 border-t border-[var(--color-surface-2)] pt-2">
              <Field label="battery" value={fields.battery?.decoded} suffix="%"
                     source={fields.battery?.source} />
              <Field label="firmware" value={fields.firmware?.decoded}
                     source={fields.firmware?.source} />
              <Field label="mode" value={fields.mode?.decoded?.toUpperCase()}
                     source={fields.mode?.source} />
              <Field label="dmx hold"
                     value={fields.dmxHold?.decoded === undefined ? null
                            : fields.dmxHold.decoded ? 'On' : 'Off'}
                     source={fields.dmxHold?.source} />
              {fields.outputPower && (
                <Field label="output power"
                       value={fields.outputPower.notApplicable
                              ? 'n/a in RX'
                              : fields.outputPower.toolboxLabel || fields.outputPower.decoded}
                       source={fields.outputPower.source} />
              )}
              {fields.txProtocol && (
                <Field label="protocol"
                       value={fields.txProtocol.notApplicable
                              ? 'n/a in RX'
                              : fields.txProtocol.decoded?.toUpperCase()}
                       source={fields.txProtocol.source} />
              )}
              {snapshot.warnings?.length > 0 && (
                <div className="text-[8px] font-mono text-text-muted mt-2">
                  {snapshot.warnings.join(' · ')}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      <div className="text-[8px] text-text-muted font-mono border-t border-[var(--color-surface-2)] pt-2">
        read-only · passive BLE advertisement + connected GATT reads · no configuration writes
      </div>
    </div>
  )
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run from `app/`: `npm run test`
Expected: 14 passed (6 from bleApi, 8 from CintennaPanel).

- [ ] **Step 6: Wire the tab**

In `app/src/pages/Devices.jsx`, add the import beside the other top-of-file imports:

```javascript
import CintennaPanel from '../components/devices/CintennaPanel'
```

Then extend the `PANELS` map (currently lines 473–477):

```javascript
const PANELS = {
  starlink: StarlinkPanel,
  bolero: BoleroPanel,
  stardust: StardustPanel,
  cintenna: CintennaPanel,
};
```

The tab button itself needs no change — the strip renders from `GET /api/devices`, which now returns a `cintenna` entry.

- [ ] **Step 7: Verify in the browser**

Start the backend from `backend/` with BLE and sim on:

```bash
FIVE12_BLE_TOOLS=1 FIVE12_DEVICE_SIM=1 flask run
```

On PowerShell:

```bash
$env:FIVE12_BLE_TOOLS='1'; $env:FIVE12_DEVICE_SIM='1'; flask run
```

Start the frontend from `app/`: `npm run dev`

Open `http://localhost:5173`, go to Devices, and confirm: a **Cintenna (CRMX)** tab appears reading "2 nearby"; clicking it lists `F12L - 1946` and `F12L - 2071` with moving signal bars; selecting one and clicking **Read status** shows battery, firmware `1.0.7.2`, and mode.

- [ ] **Step 8: Verify the feature-off path**

Restart the backend from `backend/` with no BLE env vars: `flask run`

Confirm the Cintenna tab still appears, reads "no Bluetooth adapter", and that Patch, Labels, and Network are unaffected.

- [ ] **Step 9: Commit**

```bash
git add app/src/components/devices/ app/src/pages/Devices.jsx
git commit -m "feat: show nearby CRMX devices on the Devices page"
```

---

## Read-only gate

Everything above ships without a write path. Before starting the command-policy work in Plan 2, verify on real hardware:

- [ ] Passive scan finds the Cintenna without connecting (Toolbox closed)
- [ ] Advertised name, RSSI, service UUID, and manufacturer payload all appear
- [ ] Connect and read battery, firmware, and the RX snapshot
- [ ] Open Toolbox, attempt a snapshot, confirm the conflict message names Toolbox
- [ ] Close Toolbox, reconnect successfully
- [ ] Unset `FIVE12_BLE_TOOLS`, confirm Patch/Labels/Network/Devices all still work
- [ ] `pytest` green from `backend/`, `npm run test` green from `app/`

Record the results, then plan the write phase against what the hardware actually did.
