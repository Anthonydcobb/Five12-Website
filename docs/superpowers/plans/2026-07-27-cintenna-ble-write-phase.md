# Cintenna BLE Write Phase Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an operator switch a Cintenna between RX and TX, Link from a transmitter, and Unlink a receiver, from the Devices page — every write allowlisted, mode-gated, and confirmed.

**Architecture:** One new backend module, `command_service.py`, holds the entire write surface as a frozen table; the client posts a command *name* and the server maps it to a UUID and payload byte. A second env gate, `FIVE12_BLE_WRITE`, registers a separate blueprint so the write routes do not exist unless deliberately switched on. The read path is untouched: writes ride a subclass of the existing connection adapter, leaving the read adapter's "no write method" guarantee intact.

**Tech Stack:** Python 3 / Flask / bleak (backend), React / Vite / Vitest + React Testing Library (frontend), pytest (backend tests).

Design: [`../specs/2026-07-27-cintenna-ble-write-phase-design.md`](../specs/2026-07-27-cintenna-ble-write-phase-design.md)

## Global Constraints

Every task's requirements implicitly include this section.

- **Two interpreters.** Tests run on the global Python 3.14; the app runs on `C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe`. `bleak` is installed **only** on the app runtime. No module added by this plan may import `bleak` at module scope — follow the existing lazy-import-inside-function pattern in `connection_manager.py`.
- **`pytest` is not on PATH.** Always `cd backend && python -m pytest`.
- **Never claim RF association.** No field, variable, CSS class, or string named `linked`. An ATT acknowledgement is `attAcknowledged`, nothing more.
- **The client never names a UUID or a payload byte.** Any API accepting either from the client is a plan violation.
- **"Accepted, unverified" is an outcome, not an error.** Never collapse it into success or failure.
- **`FIVE12_BLE_WRITE` defaults off.** With it unset the app must behave exactly as the read-only phase shipped.
- **No new characteristic UUIDs.** Only `MODE` and `LINK_ACTION` are written. The opaque blob `10351003-3555-4907-0431-2b27430c2642` is never read or written.
- Existing style: 4-space Python indent, single-quoted strings, module docstrings explaining *why*.

## File Structure

| File | Responsibility |
|---|---|
| `backend/config.py` | + `ENABLE_BLE_WRITE` on both config classes |
| `backend/app/__init__.py` | + conditional registration of the command blueprint |
| `backend/app/five12_ble/errors.py` | + six typed write-rejection errors |
| `backend/app/five12_ble/command_service.py` | **NEW** — command table, token store, execution, verification, audit |
| `backend/app/five12_ble/connection_manager.py` | + `BleakWriteClientAdapter`, `connect_for_write` |
| `backend/app/five12_ble/sim.py` | + mutable sim state and a write side |
| `backend/app/ble_routes.py` | + `bleWriteEnabled` in capabilities |
| `backend/app/ble_command_routes.py` | **NEW** — the only two mutating routes |
| `app/src/lib/bleApi.js` | + `prepareBleCommand`, `executeBleCommand` |
| `app/src/components/devices/BleActionDialog.jsx` | **NEW** — confirmation modal |
| `app/src/components/devices/CintennaPanel.jsx` | + Control section |

---

## Task 1: Write gate

**Files:**
- Modify: `backend/config.py` — add the flag to BOTH `DevelopmentConfig` and `DesktopConfig`, mirroring each class's existing `ENABLE_BLE_TOOLS` line
- Modify: `backend/app/__init__.py:60-69`
- Modify: `backend/app/ble_routes.py:50-58`
- Test: `backend/tests/test_ble_write_gate.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `app.config['ENABLE_BLE_WRITE']` (bool); `GET /api/ble/capabilities` gains `bleWriteEnabled` (bool).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_ble_write_gate.py`:

```python
"""The write gate is separate from the read gate on purpose: discovering
radios and changing them are different risks. Read-only must remain the
default even with Bluetooth fully enabled."""

import pytest

from app import create_app


def _app(**overrides):
    config = {
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'ENABLE_BLE_TOOLS': True,
    }
    config.update(overrides)
    return create_app(config)


@pytest.fixture(scope='module')
def read_only_app():
    return _app(ENABLE_BLE_WRITE=False)


@pytest.fixture(scope='module')
def write_app():
    return _app(ENABLE_BLE_WRITE=True)


def test_write_gate_defaults_off():
    """FIVE12_BLE_WRITE is unset in the test environment, so a config built
    without an explicit override must come back False."""
    from config import DevelopmentConfig
    assert DevelopmentConfig.ENABLE_BLE_WRITE is False


def test_capabilities_reports_write_disabled(read_only_app):
    body = read_only_app.test_client().get('/api/ble/capabilities?sim=1').get_json()
    assert body['bleToolsEnabled'] is True
    assert body['bleWriteEnabled'] is False


def test_capabilities_reports_write_enabled(write_app):
    body = write_app.test_client().get('/api/ble/capabilities?sim=1').get_json()
    assert body['bleWriteEnabled'] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_ble_write_gate.py -v`
Expected: FAIL — `AttributeError: type object 'Config' has no attribute 'ENABLE_BLE_WRITE'`, and `KeyError: 'bleWriteEnabled'`.

- [ ] **Step 3: Add the config flag**

In `backend/config.py`, directly below the existing `ENABLE_BLE_TOOLS` line in `DevelopmentConfig` (the dev config class — note it is `DevelopmentConfig`, not `Config`):

```python
    # Gates configuration WRITES, separately from ENABLE_BLE_TOOLS. Discovery
    # and status reads are one risk; changing a radio mid-show is another, so
    # they get separate switches. Read-only stays the default even with
    # Bluetooth fully enabled. Set FIVE12_BLE_WRITE=1.
    ENABLE_BLE_WRITE = os.getenv("FIVE12_BLE_WRITE", "0") == "1"
```

And below `ENABLE_BLE_TOOLS` in `DesktopConfig` (line 52):

```python
    # Writes stay opt-in on desktop too — same reasoning as the dev config.
    ENABLE_BLE_WRITE = os.getenv("FIVE12_BLE_WRITE", "0") == "1"
```

- [ ] **Step 4: Report the flag in capabilities**

In `backend/app/ble_routes.py`, replace the `capabilities()` body:

```python
@ble.get('/capabilities')
def capabilities():
    st = _service().status()
    return jsonify({
        'bleToolsEnabled': True,   # this route only exists when the gate is on
        # Unlike the line above this is NOT a tautology: the read routes exist
        # whenever tools are on, but writes may still be switched off. The
        # panel uses this to decide whether to render any control at all.
        'bleWriteEnabled': bool(current_app.config.get('ENABLE_BLE_WRITE')),
        'adapterAvailable': st['adapterAvailable'],
        'platformSupported': _platform_supported(),
        'sim': st['sim'],
    })
```

Add `current_app` to the existing Flask import at line 15:

```python
from flask import Blueprint, current_app, jsonify, request
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_ble_write_gate.py -v`
Expected: 3 passed.

- [ ] **Step 6: Run the whole BLE suite for regressions**

Run: `cd backend && python -m pytest tests/ -k ble -v`
Expected: all pass — nothing registered a write route yet.

- [ ] **Step 7: Commit**

```bash
git add backend/config.py backend/app/ble_routes.py backend/tests/test_ble_write_gate.py
git commit -m "feat(ble): add FIVE12_BLE_WRITE gate, separate from FIVE12_BLE_TOOLS"
```

---

## Task 2: Command policy table

The entire write surface, as data. Nothing here performs I/O, so it is importable and testable on the interpreter that has no `bleak`.

**Files:**
- Create: `backend/app/five12_ble/command_service.py`
- Modify: `backend/tests/test_ble_constants.py:63-69`
- Test: `backend/tests/test_ble_command_policy.py` (create)

**Interfaces:**
- Consumes: `constants.MODE`, `constants.LINK_ACTION`, `constants.Mode`.
- Produces:
  - `CommandSpec` frozen dataclass: `.name: str`, `.uuid: str`, `.payload: bytes`, `.required_mode: tuple[str, ...]`, `.verification: str`, `.warning: str`
  - `COMMANDS: dict[str, CommandSpec]` with keys `set_mode_rx`, `set_mode_tx`, `link`, `unlink`
  - `WRITABLE_UUIDS: frozenset[str]`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_ble_command_policy.py`:

```python
"""RELEASE GATE for the write phase. The command table is the entire write
surface; if a UUID or payload byte can reach a radio without appearing here,
the 'no arbitrary write path' guarantee is gone."""

from app.five12_ble import constants as c
from app.five12_ble.command_service import COMMANDS, WRITABLE_UUIDS


def test_exactly_four_commands():
    assert set(COMMANDS) == {'set_mode_rx', 'set_mode_tx', 'link', 'unlink'}


def test_writable_uuids_are_derived_not_handwritten():
    """Derived from the table, so a new command cannot widen the allowlist
    without also appearing in COMMANDS."""
    assert WRITABLE_UUIDS == frozenset(spec.uuid for spec in COMMANDS.values())


def test_writable_uuids_are_exactly_mode_and_link_action():
    assert WRITABLE_UUIDS == frozenset({c.MODE, c.LINK_ACTION})


def test_every_writable_uuid_is_a_captured_constant():
    """No UUID may be written that was not confirmed by GATT capture."""
    assert WRITABLE_UUIDS <= c.READABLE_UUIDS


def test_exact_wire_payloads():
    assert COMMANDS['set_mode_rx'].payload == bytes([0x00])
    assert COMMANDS['set_mode_tx'].payload == bytes([0x01])
    assert COMMANDS['link'].payload == bytes([0x05])
    assert COMMANDS['unlink'].payload == bytes([0x00])


def test_mode_gates():
    assert COMMANDS['link'].required_mode == ('tx',)
    assert COMMANDS['unlink'].required_mode == ('rx',)
    # Mode changes are allowed from either direction, but only from a KNOWN
    # mode — an undecodable mode is never a reason to guess.
    assert set(COMMANDS['set_mode_rx'].required_mode) == {'rx', 'tx'}
    assert set(COMMANDS['set_mode_tx'].required_mode) == {'rx', 'tx'}


def test_verification_strategies():
    assert COMMANDS['set_mode_rx'].verification == 'reboot-tolerant'
    assert COMMANDS['set_mode_tx'].verification == 'reboot-tolerant'
    assert COMMANDS['link'].verification == 'ack-only'
    assert COMMANDS['unlink'].verification == 'ack-only'


def test_every_command_warns_the_operator():
    for name, spec in COMMANDS.items():
        assert spec.warning.strip(), f'{name} has no operator warning'


def test_link_warning_names_the_actual_hazard():
    """Link puts a transmitter into pairing mode; any unlinked receiver in
    range pairs to it. The operator must be told that, not just 'are you
    sure'."""
    assert 'range' in COMMANDS['link'].warning.lower()


# NOTE: there is deliberately no test asserting the warning prose does not
# claim a completed outcome. Two attempts at that via substring denylists
# both false-positived on legitimate English ('unlinked receiver', 'until it
# is paired again') — the distinction is semantic, not lexical. The rule it
# was reaching for ("never claim RF association") is enforced where it is
# structurally checkable instead: the command result carries no field named
# `linked`. See test_ble_command_service.py.


def test_command_table_is_immutable():
    from dataclasses import FrozenInstanceError
    import pytest
    with pytest.raises(FrozenInstanceError):
        COMMANDS['link'].payload = bytes([0xFF])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_ble_command_policy.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.five12_ble.command_service'`.

- [ ] **Step 3: Create the command table**

Create `backend/app/five12_ble/command_service.py`:

```python
"""Mode-gated, allowlisted, confirmed writes — the ENTIRE write surface.

The read-only phase had no write path because this module did not exist. That
was structural, not a promise. Now that it does exist, the same structure
confines every write to this one file.

The client posts a command NAME. This module maps it to a UUID and a payload
byte. The client can name neither, which is what makes "no arbitrary UUID
write path" impossible by construction rather than policed by review.

Pure enough to import without bleak: nothing here opens a radio. The one
function that connects imports connection_manager lazily.
"""

from dataclasses import dataclass

from . import constants as c


@dataclass(frozen=True)
class CommandSpec:
    """One row of the write policy.

    required_mode lists the modes the device may be in for this command to be
    legal. A device whose MODE does not decode is in none of them, so an
    unknown mode blocks every command.
    """

    name: str
    uuid: str
    payload: bytes
    required_mode: tuple
    verification: str   # 'reboot-tolerant' | 'ack-only'
    warning: str


COMMANDS = {
    'set_mode_rx': CommandSpec(
        name='set_mode_rx',
        uuid=c.MODE,
        payload=bytes([c.Mode.RX]),
        required_mode=('rx', 'tx'),
        verification='reboot-tolerant',
        warning=(
            'This radio will restart and disappear for several seconds. '
            'If it is currently transmitting, everything it feeds goes dark.'
        ),
    ),
    'set_mode_tx': CommandSpec(
        name='set_mode_tx',
        uuid=c.MODE,
        payload=bytes([c.Mode.TX]),
        required_mode=('rx', 'tx'),
        verification='reboot-tolerant',
        warning=(
            'This radio will restart and disappear for several seconds. '
            'If it is currently receiving, its fixture goes dark.'
        ),
    ),
    'link': CommandSpec(
        name='link',
        uuid=c.LINK_ACTION,
        payload=bytes([0x05]),
        required_mode=('tx',),
        verification='ack-only',
        warning=(
            'This puts the transmitter into pairing mode. Any unlinked '
            'receiver in range will pair to it — not only the one you mean.'
        ),
    ),
    'unlink': CommandSpec(
        name='unlink',
        uuid=c.LINK_ACTION,
        payload=bytes([0x00]),
        required_mode=('rx',),
        verification='ack-only',
        warning=(
            'This receiver will lose its transmitter. Anything it is '
            'currently feeding goes dark until it is paired again.'
        ),
    ),
}

# DERIVED, never hand-written: a new command cannot widen the allowlist
# without also appearing in COMMANDS above.
WRITABLE_UUIDS = frozenset(spec.uuid for spec in COMMANDS.values())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_ble_command_policy.py -v`
Expected: 11 passed.

- [ ] **Step 5: Invert the read-only constants guard**

In `backend/tests/test_ble_constants.py`, replace `test_no_write_allowlist_exists_in_this_phase` (lines 63-69) with:

```python
def test_write_allowlist_is_confined_to_the_command_table():
    """RELEASE GATE, inverted from the read-only phase. That phase asserted no
    write allowlist existed at all. This phase allows exactly two writable
    characteristics, both already members of the captured read set, and both
    reachable only through a named command in the policy table."""
    from app.five12_ble.command_service import WRITABLE_UUIDS
    assert WRITABLE_UUIDS == frozenset({c.MODE, c.LINK_ACTION})
    assert WRITABLE_UUIDS <= c.READABLE_UUIDS


def test_opaque_blob_is_never_writable():
    from app.five12_ble.command_service import WRITABLE_UUIDS
    assert '10351003-3555-4907-0431-2b27430c2642' not in WRITABLE_UUIDS
```

- [ ] **Step 6: Pay the READABLE_UUIDS debt the handoff flagged**

The handoff records that `READABLE_UUIDS` is not load-bearing — `gatt_client._FIELDS` is the de facto allowlist, and the chain holds only transitively. It asks for a direct assertion before the write phase. Append to `backend/tests/test_ble_constants.py`:

```python
def test_every_read_field_is_in_the_readable_allowlist():
    """Makes READABLE_UUIDS actually enforce something. Without this the
    snapshot builder's _FIELDS could drift to a UUID nobody vetted and every
    other test would still pass."""
    from app.five12_ble.gatt_client import _FIELDS
    for name, uuid, _decoder, _source in _FIELDS:
        assert uuid in c.READABLE_UUIDS, f'{name} reads an unvetted UUID'
```

- [ ] **Step 7: Run the constants suite**

Run: `cd backend && python -m pytest tests/test_ble_constants.py -v`
Expected: all pass, including the two new tests and the inverted guard.

- [ ] **Step 8: Commit**

```bash
git add backend/app/five12_ble/command_service.py backend/tests/test_ble_command_policy.py backend/tests/test_ble_constants.py
git commit -m "feat(ble): add the command policy table, the whole write surface"
```

---

## Task 3: Typed write rejections

**Files:**
- Modify: `backend/app/five12_ble/errors.py` (append)
- Test: `backend/tests/test_ble_write_errors.py` (create)

**Interfaces:**
- Produces: `UnknownCommand`, `UnknownMode`, `WrongMode`, `StaleSnapshot`, `ConfirmationInvalid`, `IdentityMismatch` — all `BleError` subclasses with `.code`, `.operator_message`, `.to_dict()`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_ble_write_errors.py`:

```python
"""Every write rejection an operator can cause gets a named class and a
sentence saying what to do about it. A raw 400 with no copy is a defect."""

import pytest

from app.five12_ble import errors as e


@pytest.mark.parametrize('cls, code', [
    (e.UnknownCommand, 'unknown-command'),
    (e.UnknownMode, 'unknown-mode'),
    (e.WrongMode, 'wrong-mode'),
    (e.StaleSnapshot, 'stale-snapshot'),
    (e.ConfirmationInvalid, 'confirmation-invalid'),
    (e.IdentityMismatch, 'identity-mismatch'),
])
def test_write_errors_have_codes_and_operator_copy(cls, code):
    err = cls(detail='x')
    assert err.code == code
    assert len(err.operator_message) > 20
    body = err.to_dict()
    assert body['code'] == code
    assert body['message'] == err.operator_message


def test_all_write_errors_are_ble_errors():
    """The routes catch BleError as one family; an error outside it would
    escape as a 500 with a traceback."""
    for cls in (e.UnknownCommand, e.UnknownMode, e.WrongMode,
                e.StaleSnapshot, e.ConfirmationInvalid, e.IdentityMismatch):
        assert issubclass(cls, e.BleError)


def test_stale_snapshot_copy_tells_the_operator_to_re_read():
    assert 'read' in e.StaleSnapshot().operator_message.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_ble_write_errors.py -v`
Expected: FAIL — `AttributeError: module 'app.five12_ble.errors' has no attribute 'UnknownCommand'`.

- [ ] **Step 3: Append the error classes**

Append to `backend/app/five12_ble/errors.py`:

```python
# ── Write-phase rejections ───────────────────────────────────────────────────
# Each of these is a refusal to write, not a failure to talk to the radio.


class UnknownCommand(BleError):
    code = 'unknown-command'
    operator_message = (
        'Five12 does not recognise that command. Reload this page; if it keeps '
        'happening the app and the server are running different versions.'
    )


class UnknownMode(BleError):
    code = 'unknown-mode'
    operator_message = (
        'This radio did not report a mode Five12 understands, so it will not be '
        'changed. It may be running firmware Five12 has not been verified '
        'against.'
    )


class WrongMode(BleError):
    code = 'wrong-mode'
    operator_message = (
        'That action is not available in this radio\'s current mode. Link is a '
        'transmitter action; Unlink is a receiver action.'
    )


class StaleSnapshot(BleError):
    code = 'stale-snapshot'
    operator_message = (
        'This radio changed since you opened this dialog, so nothing was '
        'written. Read its status again and retry.'
    )


class ConfirmationInvalid(BleError):
    code = 'confirmation-invalid'
    operator_message = (
        'That confirmation has expired or was already used. Start the action '
        'again — confirmations are single-use and last 60 seconds.'
    )


class IdentityMismatch(BleError):
    code = 'identity-mismatch'
    operator_message = (
        'The radio at this address is not the one you confirmed against, so '
        'nothing was written. Bluetooth addresses can change; pick the radio '
        'from the list again.'
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_ble_write_errors.py -v`
Expected: 8 passed (6 parametrized cases + 2 standalone).

- [ ] **Step 5: Commit**

```bash
git add backend/app/five12_ble/errors.py backend/tests/test_ble_write_errors.py
git commit -m "feat(ble): add typed write-rejection errors with operator copy"
```

---

## Task 4: Write-capable connection adapter

The read adapter must keep its "no write-shaped method of any name" property — `test_ble_gatt_client.py:123` asserts it, and that test stays untouched. So writes ride a subclass.

**Files:**
- Modify: `backend/app/five12_ble/connection_manager.py:70-120`
- Test: `backend/tests/test_ble_write_client.py` (create)

**Interfaces:**
- Consumes: `command_service.WRITABLE_UUIDS`, `errors.UnknownCommand`, `errors.CharacteristicMissing`.
- Produces:
  - `BleakWriteClientAdapter(BleakClientAdapter)` with `async write_gatt_char(uuid, payload) -> None`
  - `connect_for_write(os_id)` async context manager yielding a `BleakWriteClientAdapter`
  - `WRITE_TIMEOUT = 6.0`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_ble_write_client.py`:

```python
"""The write adapter is a SEPARATE class from the read adapter on purpose.
BleakClientAdapter is asserted elsewhere to expose no write-shaped method,
and the read path must keep that property forever."""

import asyncio

import pytest

from app.five12_ble import constants as c
from app.five12_ble import errors as e
from app.five12_ble.connection_manager import (
    BleakClientAdapter,
    BleakWriteClientAdapter,
)


class FakeBleakClient:
    """Minimal stand-in for a bleak client, recording writes so tests can
    assert exact wire bytes."""

    def __init__(self, uuids):
        self.services = []
        self._uuids = {u.lower() for u in uuids}
        self.writes = []

    async def write_gatt_char(self, uuid, payload, response=False):
        self.writes.append((uuid.lower(), bytes(payload), response))


def _adapter(uuids=(c.MODE, c.LINK_ACTION)):
    adapter = BleakWriteClientAdapter.__new__(BleakWriteClientAdapter)
    adapter._client = FakeBleakClient(uuids)
    adapter._uuids = {u.lower() for u in uuids}
    return adapter


def test_read_adapter_still_has_no_write_method():
    """The single most important property carried over from the read-only
    phase. Writes live in the subclass; the base class must stay clean."""
    write_shaped = [n for n in vars(BleakClientAdapter) if 'write' in n.lower()]
    assert write_shaped == []


def test_write_adapter_sends_exact_bytes_with_response():
    adapter = _adapter()
    asyncio.run(adapter.write_gatt_char(c.LINK_ACTION, bytes([0x05])))
    assert adapter._client.writes == [(c.LINK_ACTION, bytes([0x05]), True)]


def test_write_adapter_demands_an_acknowledgement():
    """response=True means an ATT acknowledgement. A write-without-response
    would give us no evidence the radio accepted anything at all."""
    adapter = _adapter()
    asyncio.run(adapter.write_gatt_char(c.MODE, bytes([0x01])))
    assert adapter._client.writes[0][2] is True


def test_write_adapter_refuses_a_uuid_outside_the_allowlist():
    adapter = _adapter(uuids=(c.MODE, c.LINK_ACTION, c.OUTPUT_POWER))
    with pytest.raises(e.UnknownCommand):
        asyncio.run(adapter.write_gatt_char(c.OUTPUT_POWER, bytes([0x02])))
    assert adapter._client.writes == []


def test_write_adapter_refuses_a_characteristic_the_device_lacks():
    adapter = _adapter(uuids=(c.MODE,))
    with pytest.raises(e.CharacteristicMissing):
        asyncio.run(adapter.write_gatt_char(c.LINK_ACTION, bytes([0x05])))
    assert adapter._client.writes == []


def test_write_adapter_can_still_read():
    """It is a subclass, so a command can verify its own write without
    opening a second connection."""
    assert hasattr(BleakWriteClientAdapter, 'read_gatt_char')
    assert hasattr(BleakWriteClientAdapter, 'has_characteristic')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_ble_write_client.py -v`
Expected: FAIL — `ImportError: cannot import name 'BleakWriteClientAdapter'`.

- [ ] **Step 3: Add the write adapter and refactor connect to share its body**

In `backend/app/five12_ble/connection_manager.py`, add `CharacteristicMissing` and `UnknownCommand` to the existing error import at line 14:

```python
from .errors import (
    AdapterUnavailable,
    CharacteristicMissing,
    DeviceBusy,
    DeviceNotFound,
    OperationTimeout,
    ToolboxHoldingConnection,
    UnknownCommand,
)
```

Add the timeout constant below `DISCONNECT_TIMEOUT` (line 26):

```python
WRITE_TIMEOUT = 6.0
```

Add the subclass directly below `BleakClientAdapter` (after line 68):

```python
class BleakWriteClientAdapter(BleakClientAdapter):
    """The read adapter plus exactly one write method.

    Deliberately a separate class. test_ble_gatt_client.py asserts that
    BleakClientAdapter exposes no write-shaped method of any name, and the
    read path must keep that guarantee — so writes get their own type that
    only the command service ever constructs.
    """

    async def write_gatt_char(self, uuid, payload):
        # Second, independent check on the allowlist. The command service has
        # already mapped a command name to this UUID; this refuses anything
        # that reached here by another route. Imported lazily so the module
        # graph stays acyclic.
        from .command_service import WRITABLE_UUIDS

        if uuid.lower() not in WRITABLE_UUIDS:
            raise UnknownCommand(detail=uuid)
        if not self.has_characteristic(uuid):
            raise CharacteristicMissing(detail=uuid)
        # response=True demands an ATT acknowledgement. Without it we would
        # have no evidence the radio accepted anything.
        await asyncio.wait_for(
            self._client.write_gatt_char(uuid, payload, response=True),
            timeout=WRITE_TIMEOUT,
        )
```

Now replace the `connect` context manager (lines 70-120) so read and write share one body:

```python
@contextlib.asynccontextmanager
async def _connect_with(os_id, adapter_cls):
    """Connect to one device, yielding `adapter_cls` wrapped around the client.

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

        yield adapter_cls(client)
    finally:
        # The lock must be released no matter how disconnect exits, including
        # via asyncio.CancelledError (a BaseException, not caught by
        # `except Exception` / contextlib.suppress(Exception)). A held lock
        # never expires on its own, so a cancelled disconnect used to poison
        # the device for the rest of the process. The nested finally runs
        # release() before any exception — cancellation included — keeps
        # propagating past this frame.
        try:
            with contextlib.suppress(Exception):
                # A hung disconnect is real, common BLE behaviour; bound it
                # like every other bleak call here so cleanup can't stall
                # forever. Failing to disconnect cleanly must not mask
                # whatever the caller's body was actually doing, so the
                # timeout (and any other disconnect failure) is swallowed.
                await asyncio.wait_for(client.disconnect(), timeout=DISCONNECT_TIMEOUT)
        finally:
            lock.release()


@contextlib.asynccontextmanager
async def connect(os_id):
    """Read-only connection. Cannot write: the adapter has no write method."""
    async with _connect_with(os_id, BleakClientAdapter) as adapter:
        yield adapter


@contextlib.asynccontextmanager
async def connect_for_write(os_id):
    """Write-capable connection. Only the command service should call this."""
    async with _connect_with(os_id, BleakWriteClientAdapter) as adapter:
        yield adapter
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_ble_write_client.py -v`
Expected: 6 passed.

- [ ] **Step 5: Verify the read-path guards still hold**

Run: `cd backend && python -m pytest tests/test_ble_gatt_client.py tests/test_ble_connection_manager.py -v`
Expected: all pass, including `test_production_client_adapter_offers_no_write_method` — the base class was not modified.

- [ ] **Step 6: Commit**

```bash
git add backend/app/five12_ble/connection_manager.py backend/tests/test_ble_write_client.py
git commit -m "feat(ble): add a write-capable connection adapter as a separate class"
```

---

## Task 5: Confirmation tokens

**Files:**
- Modify: `backend/app/five12_ble/command_service.py` (append)
- Test: `backend/tests/test_ble_confirmation.py` (create)

**Interfaces:**
- Consumes: `errors.ConfirmationInvalid`.
- Produces:
  - `TOKEN_TTL_S = 60.0`
  - `ConfirmationToken` frozen dataclass: `.value`, `.os_id`, `.hardware_id`, `.command`, `.mode`, `.issued_at`
  - `TokenStore` with `issue(os_id, hardware_id, command, mode, now=None) -> ConfirmationToken` and `consume(value, os_id, command, now=None) -> ConfirmationToken`
  - module-level `tokens = TokenStore()`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_ble_confirmation.py`:

```python
"""A confirmation the server did not issue is not a confirmation. Tokens are
server-minted, single-use, short-lived, and bound to one device and one
command, so a stale browser tab cannot replay one."""

import pytest

from app.five12_ble import errors as e
from app.five12_ble.command_service import TOKEN_TTL_S, TokenStore


def _store():
    return TokenStore()


def test_issue_returns_an_unguessable_value():
    t = _store().issue('dev-1', 'F1400000', 'link', 'tx', now=100.0)
    assert len(t.value) >= 32


def test_two_tokens_are_never_equal():
    s = _store()
    a = s.issue('dev-1', 'F1400000', 'link', 'tx', now=100.0)
    b = s.issue('dev-1', 'F1400000', 'link', 'tx', now=100.0)
    assert a.value != b.value


def test_consume_returns_the_binding():
    s = _store()
    t = s.issue('dev-1', 'F1400000', 'link', 'tx', now=100.0)
    got = s.consume(t.value, 'dev-1', 'link', now=101.0)
    assert got.hardware_id == 'F1400000'
    assert got.mode == 'tx'


def test_a_token_is_single_use():
    s = _store()
    t = s.issue('dev-1', 'F1400000', 'link', 'tx', now=100.0)
    s.consume(t.value, 'dev-1', 'link', now=101.0)
    with pytest.raises(e.ConfirmationInvalid):
        s.consume(t.value, 'dev-1', 'link', now=102.0)


def test_a_token_expires():
    s = _store()
    t = s.issue('dev-1', 'F1400000', 'link', 'tx', now=100.0)
    with pytest.raises(e.ConfirmationInvalid):
        s.consume(t.value, 'dev-1', 'link', now=100.0 + TOKEN_TTL_S + 0.1)


def test_a_token_is_bound_to_its_device():
    s = _store()
    t = s.issue('dev-1', 'F1400000', 'link', 'tx', now=100.0)
    with pytest.raises(e.ConfirmationInvalid):
        s.consume(t.value, 'dev-2', 'link', now=101.0)


def test_a_token_is_bound_to_its_command():
    """A confirmation for 'unlink' must never execute 'set_mode_tx'."""
    s = _store()
    t = s.issue('dev-1', 'F1400000', 'unlink', 'rx', now=100.0)
    with pytest.raises(e.ConfirmationInvalid):
        s.consume(t.value, 'dev-1', 'set_mode_tx', now=101.0)


def test_an_unknown_token_is_rejected():
    with pytest.raises(e.ConfirmationInvalid):
        _store().consume('not-a-real-token', 'dev-1', 'link', now=100.0)


def test_a_failed_consume_does_not_burn_the_token():
    """Fumbling the device id must not invalidate a confirmation the operator
    is about to use correctly."""
    s = _store()
    t = s.issue('dev-1', 'F1400000', 'link', 'tx', now=100.0)
    with pytest.raises(e.ConfirmationInvalid):
        s.consume(t.value, 'wrong-device', 'link', now=101.0)
    assert s.consume(t.value, 'dev-1', 'link', now=102.0).mode == 'tx'


def test_expired_tokens_are_swept_on_issue():
    """The store must not grow without bound over a long show."""
    s = TokenStore()
    s.issue('dev-1', 'F1400000', 'link', 'tx', now=100.0)
    s.issue('dev-2', 'F1400000', 'link', 'tx', now=100.0 + TOKEN_TTL_S + 1)
    assert len(s._tokens) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_ble_confirmation.py -v`
Expected: FAIL — `ImportError: cannot import name 'TOKEN_TTL_S'`.

- [ ] **Step 3: Implement the token store**

Append to `backend/app/five12_ble/command_service.py`. Extend the imports at the top of the file:

```python
import secrets
import threading
import time
from dataclasses import dataclass

from . import constants as c
from .errors import ConfirmationInvalid
```

Then append:

```python
# ── Confirmation tokens ──────────────────────────────────────────────────────

TOKEN_TTL_S = 60.0


@dataclass(frozen=True)
class ConfirmationToken:
    """Binds one confirmation to one device, one command, and the mode the
    radio was in when the operator was shown the warning."""

    value: str
    os_id: str
    hardware_id: str
    command: str
    mode: str
    issued_at: float


class TokenStore:
    """In-process, single-use, expiring confirmations.

    In-process is correct here rather than a limitation: only one worker owns
    the Bluetooth adapter at a time (see scanner.py's lock file), so a token
    issued by a worker that cannot write would be useless anyway.
    """

    def __init__(self):
        self._tokens = {}
        self._guard = threading.Lock()

    def issue(self, os_id, hardware_id, command, mode, now=None):
        now = time.time() if now is None else now
        token = ConfirmationToken(
            value=secrets.token_urlsafe(32),
            os_id=os_id,
            hardware_id=hardware_id,
            command=command,
            mode=mode,
            issued_at=now,
        )
        with self._guard:
            self._sweep(now)
            self._tokens[token.value] = token
        return token

    def consume(self, value, os_id, command, now=None):
        """Return the token, removing it. Raises ConfirmationInvalid unless it
        exists, is unexpired, and matches this device AND this command.

        A mismatch does NOT remove the token: fumbling a device id must not
        invalidate a confirmation the operator is about to use correctly.
        """
        now = time.time() if now is None else now
        with self._guard:
            token = self._tokens.get(value)
            if token is None:
                raise ConfirmationInvalid(detail='unknown token')
            if now - token.issued_at > TOKEN_TTL_S:
                del self._tokens[value]
                raise ConfirmationInvalid(detail='expired')
            if token.os_id != os_id:
                raise ConfirmationInvalid(detail='device mismatch')
            if token.command != command:
                raise ConfirmationInvalid(detail='command mismatch')
            del self._tokens[value]
            return token

    def _sweep(self, now):
        """Caller holds the guard."""
        stale = [v for v, t in self._tokens.items() if now - t.issued_at > TOKEN_TTL_S]
        for v in stale:
            del self._tokens[v]


tokens = TokenStore()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_ble_confirmation.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/five12_ble/command_service.py backend/tests/test_ble_confirmation.py
git commit -m "feat(ble): add single-use, device- and command-bound confirmations"
```

---

## Task 6: Command execution and the ack-only path

Link and Unlink complete here. Mode writes reach the reboot state machine in Task 7.

**Files:**
- Modify: `backend/app/five12_ble/command_service.py` (append)
- Test: `backend/tests/test_ble_command_service.py` (create)

**Interfaces:**
- Consumes: `connection_manager.connect_for_write`, `decoders.decode_mode`, `TokenStore`, `COMMANDS`.
- Produces:
  - `async prepare_command(os_id, command_name, registry) -> dict` with keys `token`, `ttlS`, `deviceAlias`, `currentMode`, `warning`, `command`
  - `async execute_command(os_id, command_name, expected_mode, token_value, registry) -> dict` with keys `command`, `attAcknowledged`, `verification`, `mode`, `durationMs`
  - `async _read_mode(client) -> str | None`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_ble_command_service.py`:

```python
"""Execution asserts EXACT wire bytes, because the whole safety argument
rests on 'link' meaning 0x05 to 45a41003 and nothing else ever reaching a
radio."""

import asyncio
import contextlib

import pytest

from app.five12_ble import constants as c
from app.five12_ble import errors as e
from app.five12_ble import command_service as cs


class FakeDevice:
    """Mirrors DiscoveredDevice: the hardware id lives in the decoded
    advertisement dict, NOT as an attribute of its own."""

    def __init__(self, os_id='dev-1', hardware_id='F1400000', name='F12L - 1946'):
        self.os_id = os_id
        self.local_name = name
        self.advert = {'hardwareId': hardware_id}


class FakeRegistry:
    def __init__(self, device=None):
        self._device = device

    def get(self, os_id):
        if self._device is not None and self._device.os_id == os_id:
            return self._device
        return None


class FakeWriteClient:
    """Records writes so tests can assert exact bytes; serves reads from a
    mutable dict so a write can be verified by a subsequent read."""

    def __init__(self, values):
        self.values = dict(values)
        self.writes = []

    def has_characteristic(self, uuid):
        return uuid in self.values

    async def read_gatt_char(self, uuid):
        return self.values[uuid]

    async def write_gatt_char(self, uuid, payload):
        self.writes.append((uuid, bytes(payload)))
        self.values[uuid] = bytes(payload)

    def assert_write(self, uuid, payload):
        assert (uuid, payload) in self.writes, self.writes


def _rx_values():
    return {c.MODE: b'\x00', c.LINK_ACTION: b'\x01'}


def _tx_values():
    return {c.MODE: b'\x01', c.LINK_ACTION: b'\x03'}


@pytest.fixture
def patched(monkeypatch):
    """Replace connect_for_write with a fake, and give the module a fresh
    token store so tests cannot leak confirmations into each other."""
    state = {'client': None}

    @contextlib.asynccontextmanager
    async def fake_connect(os_id):
        yield state['client']

    monkeypatch.setattr(cs, '_connect_for_write', fake_connect)
    monkeypatch.setattr(cs, 'tokens', cs.TokenStore())
    return state


def _prepare_and_execute(state, values, command, expected_mode,
                         device=None, registry=None):
    state['client'] = FakeWriteClient(values)
    device = device or FakeDevice()
    registry = registry or FakeRegistry(device)
    prep = asyncio.run(cs.prepare_command(device.os_id, command, registry))
    result = asyncio.run(cs.execute_command(
        device.os_id, command, expected_mode, prep['token'], registry))
    return prep, result


# ── the happy paths ──────────────────────────────────────────────────────────

def test_link_writes_exactly_05_to_link_action(patched):
    _, result = _prepare_and_execute(patched, _tx_values(), 'link', 'tx')
    patched['client'].assert_write(c.LINK_ACTION, bytes([0x05]))
    assert result['attAcknowledged'] is True
    assert result['verification'] == 'ack-only'


def test_unlink_writes_exactly_00_to_link_action(patched):
    _, result = _prepare_and_execute(patched, _rx_values(), 'unlink', 'rx')
    patched['client'].assert_write(c.LINK_ACTION, bytes([0x00]))
    assert result['verification'] == 'ack-only'


def test_result_never_claims_a_link_was_made(patched):
    """RELEASE GATE. An ATT acknowledgement is not RF association."""
    _, result = _prepare_and_execute(patched, _tx_values(), 'link', 'tx')
    assert 'linked' not in result
    for value in result.values():
        assert str(value).lower() != 'linked'


def test_prepare_returns_the_server_side_warning(patched):
    patched['client'] = FakeWriteClient(_tx_values())
    device = FakeDevice()
    prep = asyncio.run(cs.prepare_command('dev-1', 'link', FakeRegistry(device)))
    assert prep['warning'] == cs.COMMANDS['link'].warning
    assert prep['currentMode'] == 'tx'
    assert prep['deviceAlias'] == 'F12L - 1946'
    assert prep['ttlS'] == cs.TOKEN_TTL_S


# ── the rejections ───────────────────────────────────────────────────────────

def test_unknown_command_is_rejected(patched):
    patched['client'] = FakeWriteClient(_tx_values())
    with pytest.raises(e.UnknownCommand):
        asyncio.run(cs.prepare_command('dev-1', 'set_output_power',
                                       FakeRegistry(FakeDevice())))


def test_link_in_rx_is_rejected(patched):
    patched['client'] = FakeWriteClient(_rx_values())
    registry = FakeRegistry(FakeDevice())
    prep = asyncio.run(cs.prepare_command('dev-1', 'link', registry))
    with pytest.raises(e.WrongMode):
        asyncio.run(cs.execute_command('dev-1', 'link', 'rx', prep['token'], registry))
    assert patched['client'].writes == []


def test_unlink_in_tx_is_rejected(patched):
    patched['client'] = FakeWriteClient(_tx_values())
    registry = FakeRegistry(FakeDevice())
    prep = asyncio.run(cs.prepare_command('dev-1', 'unlink', registry))
    with pytest.raises(e.WrongMode):
        asyncio.run(cs.execute_command('dev-1', 'unlink', 'tx', prep['token'], registry))
    assert patched['client'].writes == []


def test_undecodable_mode_blocks_every_command(patched):
    patched['client'] = FakeWriteClient({c.MODE: b'\x7f', c.LINK_ACTION: b'\x01'})
    with pytest.raises(e.UnknownMode):
        asyncio.run(cs.prepare_command('dev-1', 'set_mode_tx',
                                       FakeRegistry(FakeDevice())))


def test_stale_expected_mode_is_rejected(patched):
    """The operator opened the dialog on a TX radio; someone flipped it to RX
    before they hit confirm. Nothing may be written."""
    patched['client'] = FakeWriteClient(_tx_values())
    registry = FakeRegistry(FakeDevice())
    prep = asyncio.run(cs.prepare_command('dev-1', 'link', registry))
    patched['client'].values[c.MODE] = b'\x00'   # flipped to RX behind our back
    with pytest.raises(e.StaleSnapshot):
        asyncio.run(cs.execute_command('dev-1', 'link', 'tx', prep['token'], registry))
    assert patched['client'].writes == []


def test_missing_confirmation_is_rejected(patched):
    patched['client'] = FakeWriteClient(_tx_values())
    registry = FakeRegistry(FakeDevice())
    with pytest.raises(e.ConfirmationInvalid):
        asyncio.run(cs.execute_command('dev-1', 'link', 'tx', '', registry))
    assert patched['client'].writes == []


def test_replayed_confirmation_is_rejected(patched):
    """A confirmation is single use. Clicking Link twice, or a duplicated
    request from a flaky network, must not write twice."""
    patched['client'] = FakeWriteClient(_tx_values())
    registry = FakeRegistry(FakeDevice())
    prep = asyncio.run(cs.prepare_command('dev-1', 'link', registry))
    asyncio.run(cs.execute_command('dev-1', 'link', 'tx', prep['token'], registry))
    assert len(patched['client'].writes) == 1

    with pytest.raises(e.ConfirmationInvalid):
        asyncio.run(cs.execute_command('dev-1', 'link', 'tx', prep['token'], registry))
    assert len(patched['client'].writes) == 1


def test_a_confirmation_cannot_execute_a_different_command(patched):
    """Confirming 'unlink' must never be redeemable as a mode change."""
    patched['client'] = FakeWriteClient(_rx_values())
    registry = FakeRegistry(FakeDevice())
    prep = asyncio.run(cs.prepare_command('dev-1', 'unlink', registry))
    with pytest.raises(e.ConfirmationInvalid):
        asyncio.run(cs.execute_command('dev-1', 'set_mode_tx', 'rx',
                                       prep['token'], registry))
    assert patched['client'].writes == []


def test_a_command_cannot_run_while_another_owns_the_connection(monkeypatch):
    """Ownership check. The real connection manager holds a per-device lock and
    raises DeviceBusy; a command must surface that rather than queueing behind
    an operation the operator cannot see."""
    monkeypatch.setattr(cs, 'tokens', cs.TokenStore())

    @contextlib.asynccontextmanager
    async def busy_connect(os_id):
        raise e.DeviceBusy(detail=os_id)
        yield   # pragma: no cover - makes this an async generator

    monkeypatch.setattr(cs, '_connect_for_write', busy_connect)
    with pytest.raises(e.DeviceBusy):
        asyncio.run(cs.prepare_command('dev-1', 'link', FakeRegistry(FakeDevice())))


def test_audit_log_records_symbolic_names_and_no_key_material(patched, caplog):
    """Audit entries name the characteristic symbolically. They must never
    carry a linking key, the opaque blob, or a raw UUID."""
    with caplog.at_level('INFO'):
        _prepare_and_execute(patched, _tx_values(), 'link', 'tx')
    entry = '\n'.join(r.getMessage() for r in caplog.records if 'BLE WRITE' in r.getMessage())
    assert 'LINK_ACTION' in entry
    assert 'cmd=link' in entry
    assert c.LINK_ACTION not in entry            # symbolic name, not the UUID
    assert '10351003' not in entry               # never the opaque blob


def test_identity_mismatch_is_rejected(patched):
    """Bluetooth addresses rotate. If the hardware id behind this address is
    not the one confirmed against, the write must not land."""
    patched['client'] = FakeWriteClient(_tx_values())
    device = FakeDevice()
    registry = FakeRegistry(device)
    prep = asyncio.run(cs.prepare_command('dev-1', 'link', registry))
    device.advert['hardwareId'] = 'DEADBEEF'
    with pytest.raises(e.IdentityMismatch):
        asyncio.run(cs.execute_command('dev-1', 'link', 'tx', prep['token'], registry))
    assert patched['client'].writes == []


def test_device_not_in_roster_is_rejected(patched):
    patched['client'] = FakeWriteClient(_tx_values())
    with pytest.raises(e.DeviceNotFound):
        asyncio.run(cs.prepare_command('ghost', 'link', FakeRegistry(None)))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_ble_command_service.py -v`
Expected: FAIL — `AttributeError: module 'app.five12_ble.command_service' has no attribute 'prepare_command'`.

- [ ] **Step 3: Implement prepare and execute**

Append to `backend/app/five12_ble/command_service.py`. First extend the imports:

```python
import contextlib
import logging

from . import decoders as d
from .errors import (
    ConfirmationInvalid,
    DeviceNotFound,
    IdentityMismatch,
    StaleSnapshot,
    UnknownCommand,
    UnknownMode,
    WrongMode,
)

log = logging.getLogger(__name__)
```

Then append:

```python
# ── Execution ────────────────────────────────────────────────────────────────


@contextlib.asynccontextmanager
async def _connect_for_write(os_id):
    """Indirection so tests can substitute a fake client without importing
    bleak. Imported lazily for the same reason the read path does."""
    from .connection_manager import connect_for_write

    async with connect_for_write(os_id) as client:
        yield client


async def _read_mode(client):
    """Current mode as 'rx' | 'tx' | None. None means the radio reported a
    value this firmware contract does not define — never a reason to guess."""
    raw = await client.read_gatt_char(c.MODE)
    return d.decode_mode(raw)['decoded']


def _spec_or_reject(command_name):
    spec = COMMANDS.get(command_name)
    if spec is None:
        raise UnknownCommand(detail=command_name)
    return spec


def _device_or_reject(registry, os_id):
    device = registry.get(os_id)
    if device is None:
        raise DeviceNotFound(detail=os_id)
    return device


def _hardware_id(device):
    """The hardware id lives in the decoded advertisement, not as an attribute
    of DiscoveredDevice — see its to_dict(). It is the closest thing to stable
    identity we have: os_id is a Bluetooth address and can rotate.
    """
    return device.advert.get('hardwareId')


async def prepare_command(os_id, command_name, registry):
    """Step one of two. Reads the radio's actual mode and mints a confirmation
    bound to it, so the operator confirms against server-side fact rather than
    whatever their browser last happened to render."""
    spec = _spec_or_reject(command_name)
    device = _device_or_reject(registry, os_id)

    async with _connect_for_write(os_id) as client:
        mode = await _read_mode(client)

    if mode is None:
        raise UnknownMode(detail=os_id)

    token = tokens.issue(os_id, _hardware_id(device), command_name, mode)
    return {
        'command': command_name,
        'token': token.value,
        'ttlS': TOKEN_TTL_S,
        'deviceAlias': device.local_name,
        'currentMode': mode,
        'warning': spec.warning,
    }


async def execute_command(os_id, command_name, expected_mode, token_value, registry):
    """Step two. Every check runs here regardless of what the UI did — a
    disabled button is a courtesy, not a security boundary."""
    started = time.monotonic()

    spec = _spec_or_reject(command_name)
    device = _device_or_reject(registry, os_id)
    token = tokens.consume(token_value or '', os_id, command_name)

    if _hardware_id(device) != token.hardware_id:
        raise IdentityMismatch(detail=os_id)

    async with _connect_for_write(os_id) as client:
        mode = await _read_mode(client)
        if mode is None:
            raise UnknownMode(detail=os_id)
        # Freshness: the radio's mode NOW must match both what the client
        # believed and what it was when the operator was warned.
        if mode != expected_mode or mode != token.mode:
            raise StaleSnapshot(detail=f'{token.mode} -> {mode}')
        if mode not in spec.required_mode:
            raise WrongMode(detail=f'{command_name} requires {spec.required_mode}')

        await client.write_gatt_char(spec.uuid, spec.payload)

        # Only ack-only commands (link, unlink) are complete at this point.
        # Mode writes reboot the module and cannot be verified on the
        # connection that made them; the next task adds that state machine,
        # so until then every command reports the acknowledgement alone.
        result_mode = mode
        verification = 'ack-only'

    result = {
        'command': command_name,
        'attAcknowledged': True,
        'verification': verification,
        'mode': {'decoded': result_mode, 'source': 'post-write-readback'},
        'durationMs': int((time.monotonic() - started) * 1000),
    }
    _audit(command_name, device, token.mode, spec, result)
    return result


def _audit(command_name, device, mode, spec, result, error=None):
    """Symbolic names only. Never linking keys, never the opaque blob, never
    the raw OS identifier."""
    log.info(
        'BLE WRITE cmd=%s device=%s mode=%s uuid=%s payload=0x%02X '
        'ack=%s verification=%s durationMs=%s error=%s',
        command_name,
        device.local_name,
        mode,
        _symbolic_uuid(spec.uuid),
        spec.payload[0],
        result.get('attAcknowledged') if result else False,
        result.get('verification') if result else None,
        result.get('durationMs') if result else None,
        error,
    )


def _symbolic_uuid(uuid):
    return {c.MODE: 'MODE', c.LINK_ACTION: 'LINK_ACTION'}.get(uuid, 'UNKNOWN')
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_ble_command_service.py -v`
Expected: 16 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/five12_ble/command_service.py backend/tests/test_ble_command_service.py
git commit -m "feat(ble): execute allowlisted, mode-gated, confirmed link and unlink"
```

---

## Task 7: Reboot-tolerant mode verification

**Files:**
- Modify: `backend/app/five12_ble/command_service.py`
- Test: `backend/tests/test_ble_reboot_verification.py` (create)

**Interfaces:**
- Consumes: `_connect_for_write`, `_read_mode`.
- Produces:
  - `REBOOT_REDISCOVERY_TIMEOUT_S = 30.0`
  - `REBOOT_POLL_INTERVAL_S = 2.0`
  - `async _verify_after_reboot(os_id, expected_mode, timeout_s=None, sleep=None) -> tuple[str, str | None]`
  - `execute_command` now returns `verification` in `{'verified', 'accepted-unverified', 'device-did-not-return'}` for mode commands

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_ble_reboot_verification.py`:

```python
"""Writing MODE restarts the module, so the write cannot be verified on the
connection that made it. 'Accepted, unverified' is a real outcome the
operator sees, never an error and never smoothed into a success."""

import asyncio
import contextlib

import pytest

from app.five12_ble import constants as c
from app.five12_ble import command_service as cs
from app.five12_ble import errors as e


class FakeDevice:
    def __init__(self):
        self.os_id = 'dev-1'
        self.local_name = 'F12L - 1946'
        self.advert = {'hardwareId': 'F1400000'}


class FakeRegistry:
    def __init__(self, device):
        self._device = device

    def get(self, os_id):
        return self._device if os_id == self._device.os_id else None


class FakeWriteClient:
    def __init__(self, values):
        self.values = dict(values)
        self.writes = []

    def has_characteristic(self, uuid):
        return uuid in self.values

    async def read_gatt_char(self, uuid):
        return self.values[uuid]

    async def write_gatt_char(self, uuid, payload):
        self.writes.append((uuid, bytes(payload)))
        self.values[uuid] = bytes(payload)


@pytest.fixture
def rebooting(monkeypatch):
    """Scripted post-reboot reconnection attempts, on a virtual clock.

    Two things this has to get right, both of which the obvious version gets
    wrong:

    1. execute_command's OWN connect — the one that reads MODE for the
       freshness gate and then writes — must NOT draw from the script. Only
       connects that happen after a write represent the radio coming back
       from its reboot. `client.writes` is how we tell them apart. Without
       this, the first scripted entry lands before the freshness read and the
       command dies with StaleSnapshot instead of ever reaching the write.
    2. _verify_after_reboot polls against a real deadline, so a no-op sleep
       would spin for the full 30s of wall clock and then succeed by running
       the script dry. The injected sleep advances a virtual clock that
       time.monotonic reads, making every outcome deterministic and instant.

    Each entry in `attempts` is either an exception to raise on that
    reconnection attempt, or the MODE bytes the radio returns.
    """
    script = {'attempts': [], 'client': None, 'now': 0.0}

    @contextlib.asynccontextmanager
    async def fake_connect(os_id):
        client = script['client']
        if client.writes and script['attempts']:
            step = script['attempts'].pop(0)
            if isinstance(step, Exception):
                raise step
            client.values[c.MODE] = step
        yield client

    async def fake_sleep(seconds):
        script['now'] += seconds

    monkeypatch.setattr(cs.time, 'monotonic', lambda: script['now'])
    monkeypatch.setattr(cs, '_connect_for_write', fake_connect)
    monkeypatch.setattr(cs, 'tokens', cs.TokenStore())
    script['sleep'] = fake_sleep
    return script


def _run_mode_change(script, start_mode, command, attempts):
    script['client'] = FakeWriteClient({c.MODE: start_mode, c.LINK_ACTION: b'\x01'})
    device = FakeDevice()
    registry = FakeRegistry(device)
    prep = asyncio.run(cs.prepare_command('dev-1', command, registry))
    script['attempts'] = attempts
    return asyncio.run(cs.execute_command(
        'dev-1', command, 'rx' if start_mode == b'\x00' else 'tx',
        prep['token'], registry, sleep=script['sleep']))


def test_mode_change_verified_when_the_radio_returns_in_the_new_mode(rebooting):
    result = _run_mode_change(rebooting, b'\x00', 'set_mode_tx',
                              attempts=[b'\x01'])
    assert result['verification'] == 'verified'
    assert result['mode']['decoded'] == 'tx'
    assert result['attAcknowledged'] is True


def test_mode_change_tolerates_failed_reconnect_attempts(rebooting):
    """The radio is rebooting; the first attempts legitimately fail."""
    result = _run_mode_change(
        rebooting, b'\x00', 'set_mode_tx',
        attempts=[e.DeviceNotFound(), e.DeviceNotFound(), b'\x01'])
    assert result['verification'] == 'verified'


def test_mode_change_accepted_unverified_when_the_old_mode_comes_back(rebooting):
    """The write was acknowledged but the radio still reports the old mode.
    That is neither a success nor a failure and must be reported as itself."""
    result = _run_mode_change(rebooting, b'\x00', 'set_mode_tx',
                              attempts=[b'\x00'])
    assert result['verification'] == 'accepted-unverified'
    assert result['attAcknowledged'] is True


def test_mode_change_reports_a_radio_that_never_comes_back(rebooting):
    result = _run_mode_change(
        rebooting, b'\x00', 'set_mode_tx',
        attempts=[e.DeviceNotFound()] * 200)
    assert result['verification'] == 'device-did-not-return'
    assert result['mode']['decoded'] is None
    assert result['attAcknowledged'] is True


def test_a_failed_verification_is_never_reported_as_an_error(rebooting):
    """It must come back as a 200 result the panel can render, not an
    exception the route turns into a red failure."""
    result = _run_mode_change(
        rebooting, b'\x00', 'set_mode_tx',
        attempts=[e.DeviceNotFound()] * 200)
    assert result['command'] == 'set_mode_tx'
    assert 'durationMs' in result


def test_link_still_takes_the_ack_only_path(rebooting):
    """Regression: adding the state machine must not make link wait for a
    reboot that never happens."""
    rebooting['client'] = FakeWriteClient({c.MODE: b'\x01', c.LINK_ACTION: b'\x03'})
    device = FakeDevice()
    registry = FakeRegistry(device)
    prep = asyncio.run(cs.prepare_command('dev-1', 'link', registry))
    rebooting['attempts'] = []
    result = asyncio.run(cs.execute_command(
        'dev-1', 'link', 'tx', prep['token'], registry, sleep=rebooting['sleep']))
    assert result['verification'] == 'ack-only'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_ble_reboot_verification.py -v`
Expected: FAIL — `TypeError: execute_command() got an unexpected keyword argument 'sleep'`.

- [ ] **Step 3: Add the state machine**

In `backend/app/five12_ble/command_service.py`, add `asyncio` to the imports and add these constants below `TOKEN_TTL_S`:

```python
# How long to keep trying to find the radio again after a mode write reboots
# it. PROVISIONAL — the design records this as a number to measure on real
# hardware during acceptance, not to guess. 30s is a deliberately generous
# starting point; narrow it once the true figure is observed.
REBOOT_REDISCOVERY_TIMEOUT_S = 30.0
REBOOT_POLL_INTERVAL_S = 2.0
```

Add the verification coroutine directly above `execute_command`:

```python
async def _verify_after_reboot(os_id, expected_mode, timeout_s=None, sleep=None):
    """Poll for the radio to come back, then re-read MODE.

    Returns (verification, decoded_mode). The three outcomes are all normal:
    the radio came back in the new mode, came back in the old one, or did not
    come back inside the window. None of them is an exception.

    `sleep` is injectable so tests do not spend real seconds waiting.
    """
    timeout_s = REBOOT_REDISCOVERY_TIMEOUT_S if timeout_s is None else timeout_s
    sleep = asyncio.sleep if sleep is None else sleep

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        await sleep(REBOOT_POLL_INTERVAL_S)
        try:
            async with _connect_for_write(os_id) as client:
                mode = await _read_mode(client)
        except BleError:
            # Expected while the module is down. Keep trying until the
            # deadline; a reboot legitimately refuses connections for a while.
            continue
        if mode == expected_mode:
            return 'verified', mode
        # It answered, but with the old mode. The write was acknowledged and
        # did not take effect — say exactly that.
        return 'accepted-unverified', mode
    return 'device-did-not-return', None
```

Add `BleError` to the error imports in this module:

```python
from .errors import (
    BleError,
    ConfirmationInvalid,
    DeviceNotFound,
    IdentityMismatch,
    StaleSnapshot,
    UnknownCommand,
    UnknownMode,
    WrongMode,
)
```

Now replace `execute_command`'s signature and its verification branch:

```python
async def execute_command(os_id, command_name, expected_mode, token_value,
                          registry, sleep=None):
    """Step two. Every check runs here regardless of what the UI did — a
    disabled button is a courtesy, not a security boundary.

    `sleep` is injectable purely so reboot-verification tests run instantly.
    """
    started = time.monotonic()

    spec = _spec_or_reject(command_name)
    device = _device_or_reject(registry, os_id)
    token = tokens.consume(token_value or '', os_id, command_name)

    if _hardware_id(device) != token.hardware_id:
        raise IdentityMismatch(detail=os_id)

    async with _connect_for_write(os_id) as client:
        mode = await _read_mode(client)
        if mode is None:
            raise UnknownMode(detail=os_id)
        if mode != expected_mode or mode != token.mode:
            raise StaleSnapshot(detail=f'{token.mode} -> {mode}')
        if mode not in spec.required_mode:
            raise WrongMode(detail=f'{command_name} requires {spec.required_mode}')

        await client.write_gatt_char(spec.uuid, spec.payload)

    if spec.verification == 'ack-only':
        verification, result_mode = 'ack-only', mode
    else:
        # The connection above is closed before we start polling: the module
        # is rebooting and holding a dead connection open would only delay
        # rediscovery.
        target = 'rx' if command_name == 'set_mode_rx' else 'tx'
        verification, result_mode = await _verify_after_reboot(
            os_id, target, sleep=sleep)

    result = {
        'command': command_name,
        'attAcknowledged': True,
        'verification': verification,
        'mode': {'decoded': result_mode, 'source': 'post-write-readback'},
        'durationMs': int((time.monotonic() - started) * 1000),
    }
    _audit(command_name, device, token.mode, spec, result)
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_ble_reboot_verification.py -v`
Expected: 6 passed.

- [ ] **Step 5: Run every command test together**

Run: `cd backend && python -m pytest tests/test_ble_command_service.py tests/test_ble_reboot_verification.py -v`
Expected: 22 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/five12_ble/command_service.py backend/tests/test_ble_reboot_verification.py
git commit -m "feat(ble): verify mode writes across the module reboot"
```

---

## Task 8: Sim write side

Keeps the panel developable without hardware, and lets the frontend tests in Tasks 11–12 run against a real backend shape.

**Files:**
- Modify: `backend/app/five12_ble/sim.py`
- Test: `backend/tests/test_ble_sim_writes.py` (create)

**Interfaces:**
- Consumes: `sim._GATT`.
- Produces: `sim_write(os_id, uuid, payload) -> None`, `sim_reset()` (test helper), `sim_gatt_values` now reads mutated state.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_ble_sim_writes.py`:

```python
"""Sim must mirror the real path's SHAPE, including that a mode write changes
what a later read returns. A sim that silently ignores writes would let the
panel look correct while doing nothing."""

import pytest

from app.five12_ble import constants as c
from app.five12_ble.sim import (
    SIM_RX_ID,
    SIM_TX_ID,
    sim_gatt_values,
    sim_reset,
    sim_write,
)


@pytest.fixture(autouse=True)
def clean():
    sim_reset()
    yield
    sim_reset()


def test_sim_starts_from_the_captured_fixtures():
    assert sim_gatt_values(SIM_RX_ID)[c.MODE] == b'\x00'
    assert sim_gatt_values(SIM_TX_ID)[c.MODE] == b'\x01'


def test_a_mode_write_changes_what_a_later_read_returns():
    sim_write(SIM_RX_ID, c.MODE, bytes([0x01]))
    assert sim_gatt_values(SIM_RX_ID)[c.MODE] == b'\x01'


def test_a_link_write_changes_the_link_action_value():
    sim_write(SIM_TX_ID, c.LINK_ACTION, bytes([0x05]))
    assert sim_gatt_values(SIM_TX_ID)[c.LINK_ACTION] == b'\x05'


def test_writes_do_not_bleed_between_devices():
    sim_write(SIM_RX_ID, c.MODE, bytes([0x01]))
    assert sim_gatt_values(SIM_TX_ID)[c.MODE] == b'\x01'   # TX was always TX
    sim_reset()
    sim_write(SIM_TX_ID, c.MODE, bytes([0x00]))
    assert sim_gatt_values(SIM_RX_ID)[c.MODE] == b'\x00'   # RX was always RX


def test_reset_restores_the_fixtures():
    sim_write(SIM_RX_ID, c.MODE, bytes([0x01]))
    sim_reset()
    assert sim_gatt_values(SIM_RX_ID)[c.MODE] == b'\x00'


def test_writing_an_unknown_device_is_a_no_op():
    sim_write('nope', c.MODE, bytes([0x01]))
    assert sim_gatt_values('nope') == {}


def test_returned_values_are_a_copy_not_the_live_state():
    """Regression guard: callers mutating the returned dict must not corrupt
    the fixtures for every later read."""
    values = sim_gatt_values(SIM_RX_ID)
    values[c.MODE] = b'\xff'
    assert sim_gatt_values(SIM_RX_ID)[c.MODE] == b'\x00'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_ble_sim_writes.py -v`
Expected: FAIL — `ImportError: cannot import name 'sim_reset'`.

- [ ] **Step 3: Make the sim state mutable**

In `backend/app/five12_ble/sim.py`, rename the module-level fixture dict to `_FIXTURES` (change the `_GATT = {` line at line 28 to `_FIXTURES = {`), then append below it:

```python
# Live sim state, seeded from the captured fixtures. Writes mutate this copy
# so the panel behaves like the real thing — a sim that swallowed writes would
# let the UI look correct while doing nothing.
_GATT = {os_id: dict(values) for os_id, values in _FIXTURES.items()}


def sim_reset():
    """Restore the captured fixtures. Tests use this; nothing in the app does."""
    global _GATT
    _GATT = {os_id: dict(values) for os_id, values in _FIXTURES.items()}


def sim_write(os_id, uuid, payload):
    """Apply a write to the simulated device. Unknown devices are a no-op —
    the caller has already rejected them by the time we get here."""
    if os_id in _GATT:
        _GATT[os_id][uuid] = bytes(payload)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_ble_sim_writes.py -v`
Expected: 7 passed.

- [ ] **Step 5: Confirm the read-side sim tests still pass**

Run: `cd backend && python -m pytest tests/test_ble_sim.py tests/test_ble_gatt_client.py -v`
Expected: all pass — `sim_gatt_values` still returns a copy of the same starting bytes.

- [ ] **Step 6: Commit**

```bash
git add backend/app/five12_ble/sim.py backend/tests/test_ble_sim_writes.py
git commit -m "feat(ble): give the sim a write side so the panel is demoable"
```

---

## Task 9: The command routes

**Files:**
- Create: `backend/app/ble_command_routes.py`
- Modify: `backend/app/__init__.py:60-69`
- Modify: `backend/tests/test_ble_routes.py:164-168`
- Test: `backend/tests/test_ble_command_routes.py` (create)

**Interfaces:**
- Consumes: `command_service.prepare_command`, `command_service.execute_command`, `scanner.get_scan_service`.
- Produces:
  - `POST /api/ble/devices/<os_id>/commands/prepare` → `{command, token, ttlS, deviceAlias, currentMode, warning}`
  - `POST /api/ble/devices/<os_id>/commands` → the execute result
  - Blueprint `ble_write`, registered only when **both** gates are on.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_ble_command_routes.py`:

```python
"""The only two mutating routes in the app's Bluetooth surface. With the
write gate off they must not exist at all — a 404, not a 403."""

import pytest

from app import create_app


def _app(write_enabled):
    return create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'ENABLE_BLE_TOOLS': True,
        'ENABLE_BLE_WRITE': write_enabled,
    })


@pytest.fixture(scope='module')
def read_only_client():
    return _app(False).test_client()


@pytest.fixture(scope='module')
def write_client():
    return _app(True).test_client()


def test_no_mutating_route_is_registered_with_the_write_gate_off():
    """The real assertion: with the gate off, no handler exists at all. This
    is the mirror of test_exactly_two_mutating_routes_exist_with_the_gate_on,
    so the pair reads as a matched set and neither can drift alone."""
    app = _app(False)
    for rule in app.url_map.iter_rules():
        if str(rule).startswith('/api/ble'):
            assert rule.methods & {'POST', 'PUT', 'PATCH', 'DELETE'} == set(), str(rule)


def test_posting_to_a_command_route_cannot_reach_a_handler_with_the_gate_off(read_only_client):
    """Secondary end-to-end check — fails for a different reason than the
    structural test above.

    NOTE the accepted set is {404, 405}, not a bare 404. `backend/app/routes.py`
    registers an SPA catch-all `/<path:path>` for GET/HEAD/OPTIONS only, so a
    POST to ANY unregistered path in this app returns 405 rather than 404 —
    app-wide behaviour, nothing to do with Bluetooth. Do not "fix" this back
    to a bare 404.
    """
    for path in ('/api/ble/devices/sim-cintenna-tx/commands',
                 '/api/ble/devices/sim-cintenna-tx/commands/prepare'):
        status = read_only_client.post(path, json={'command': 'link'}).status_code
        assert status in (404, 405)
        assert status not in (200, 403)


def test_exactly_two_mutating_routes_exist_with_the_gate_on():
    """RELEASE GATE, inverted from the read-only phase."""
    app = _app(True)
    mutating = sorted(
        str(rule) for rule in app.url_map.iter_rules()
        if str(rule).startswith('/api/ble')
        and rule.methods & {'POST', 'PUT', 'PATCH', 'DELETE'}
    )
    assert mutating == [
        '/api/ble/devices/<os_id>/commands',
        '/api/ble/devices/<os_id>/commands/prepare',
    ]


def test_prepare_then_execute_a_link_in_sim(write_client):
    prep = write_client.post(
        '/api/ble/devices/sim-cintenna-tx/commands/prepare?sim=1',
        json={'command': 'link'}).get_json()
    assert prep['currentMode'] == 'tx'
    assert 'range' in prep['warning'].lower()

    resp = write_client.post(
        '/api/ble/devices/sim-cintenna-tx/commands?sim=1',
        json={'command': 'link', 'expectedMode': 'tx',
              'confirmationToken': prep['token']})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['attAcknowledged'] is True
    assert body['verification'] == 'ack-only'
    assert 'linked' not in body


def test_link_on_a_receiver_is_refused_with_operator_copy(write_client):
    prep = write_client.post(
        '/api/ble/devices/sim-cintenna-rx/commands/prepare?sim=1',
        json={'command': 'link'}).get_json()
    resp = write_client.post(
        '/api/ble/devices/sim-cintenna-rx/commands?sim=1',
        json={'command': 'link', 'expectedMode': 'rx',
              'confirmationToken': prep['token']})
    assert resp.status_code == 409
    assert resp.get_json()['code'] == 'wrong-mode'
    assert 'message' in resp.get_json()


def test_execute_without_a_confirmation_is_refused(write_client):
    resp = write_client.post(
        '/api/ble/devices/sim-cintenna-tx/commands?sim=1',
        json={'command': 'link', 'expectedMode': 'tx'})
    assert resp.status_code == 409
    assert resp.get_json()['code'] == 'confirmation-invalid'


def test_unknown_command_is_refused(write_client):
    resp = write_client.post(
        '/api/ble/devices/sim-cintenna-tx/commands/prepare?sim=1',
        json={'command': 'set_output_power'})
    assert resp.status_code == 409
    assert resp.get_json()['code'] == 'unknown-command'


def test_the_client_cannot_name_a_uuid_or_a_payload(write_client):
    """The request body has no field that could carry either. Anything extra
    is ignored, not honoured."""
    prep = write_client.post(
        '/api/ble/devices/sim-cintenna-tx/commands/prepare?sim=1',
        json={'command': 'link'}).get_json()
    resp = write_client.post(
        '/api/ble/devices/sim-cintenna-tx/commands?sim=1',
        json={'command': 'link', 'expectedMode': 'tx',
              'confirmationToken': prep['token'],
              'uuid': '33b53770-0942-1f91-379b-ac5af36b9efa',
              'payload': 'FF'})
    assert resp.status_code == 200
    # The write that landed is the one the TABLE specifies, not the one the
    # client tried to smuggle in.
    from app.five12_ble import constants as c
    from app.five12_ble.sim import sim_gatt_values
    assert sim_gatt_values('sim-cintenna-tx')[c.LINK_ACTION] == b'\x05'
    assert sim_gatt_values('sim-cintenna-tx')[c.OUTPUT_POWER] == b'\x02'


def test_unknown_device_404s(write_client):
    resp = write_client.post('/api/ble/devices/ghost/commands/prepare?sim=1',
                             json={'command': 'link'})
    assert resp.status_code == 404
    assert resp.get_json()['code'] == 'device-not-found'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_ble_command_routes.py -v`
Expected: FAIL — the routes 404 even with the gate on.

- [ ] **Step 3: Add sim dispatch to the command service**

The sim path is fully synchronous — no bleak, no event loop — exactly like `build_sim_snapshot`. Append to `backend/app/five12_ble/command_service.py`:

```python
# ── Sim ──────────────────────────────────────────────────────────────────────


class _SimClient:
    """Serves reads from, and applies writes to, the simulated GATT state.

    Shape parity with the real client is the point: the same execute_command
    code path runs, so the sim exercises every gate rather than bypassing them.
    """

    def __init__(self, os_id):
        from .sim import sim_gatt_values

        self.os_id = os_id
        self.values = sim_gatt_values(os_id)

    def has_characteristic(self, uuid):
        return uuid in self.values

    async def read_gatt_char(self, uuid):
        return self.values[uuid]

    async def write_gatt_char(self, uuid, payload):
        from .sim import sim_gatt_values, sim_write

        if uuid.lower() not in WRITABLE_UUIDS:
            raise UnknownCommand(detail=uuid)
        if not self.has_characteristic(uuid):
            raise CharacteristicMissing(detail=uuid)
        sim_write(self.os_id, uuid, payload)
        self.values = sim_gatt_values(self.os_id)


@contextlib.asynccontextmanager
async def _connect_sim(os_id):
    yield _SimClient(os_id)
```

Add `CharacteristicMissing` to this module's error imports.

Then make the connection choice explicit by giving both entry points a `sim` flag. Change the two signatures and their connect calls:

```python
async def prepare_command(os_id, command_name, registry, sim=False):
    ...
    connect = _connect_sim if sim else _connect_for_write
    async with connect(os_id) as client:
        mode = await _read_mode(client)
```

```python
async def execute_command(os_id, command_name, expected_mode, token_value,
                          registry, sim=False, sleep=None):
    ...
    connect = _connect_sim if sim else _connect_for_write
    async with connect(os_id) as client:
        ...
```

And in `_verify_after_reboot`, accept the same flag:

```python
async def _verify_after_reboot(os_id, expected_mode, timeout_s=None, sleep=None,
                               sim=False):
    ...
    connect = _connect_sim if sim else _connect_for_write
    ...
        try:
            async with connect(os_id) as client:
                mode = await _read_mode(client)
```

with the call site in `execute_command` passing it through:

```python
        verification, result_mode = await _verify_after_reboot(
            os_id, target, sleep=sleep, sim=sim)
```

- [ ] **Step 4: Create the routes**

Create `backend/app/ble_command_routes.py`:

```python
"""The ONLY mutating Bluetooth routes in the app.

Registered only when BOTH ENABLE_BLE_TOOLS and ENABLE_BLE_WRITE are set, so
with either gate off these endpoints do not exist rather than returning 403.

The request body names a COMMAND. It cannot name a characteristic UUID or a
payload byte — those live in command_service.COMMANDS and nowhere else. Extra
fields in the body are ignored, never honoured.
"""

import asyncio
import logging
from concurrent.futures import TimeoutError as FutureTimeoutError

from flask import Blueprint, jsonify, request

from .five12_ble.command_service import execute_command, prepare_command
from .five12_ble.errors import (
    BleError,
    DeviceNotFound,
    OperationTimeout,
    ScanLoopUnavailable,
    UnexpectedBleFailure,
)
from .five12_ble.scanner import get_scan_service
from .integrations import sim_enabled

log = logging.getLogger(__name__)

ble_write = Blueprint('ble_write', __name__, url_prefix='/api/ble')

# Generous outer bound. A mode write legitimately takes tens of seconds
# (write, reboot, rediscover, reconnect, re-read), so this must comfortably
# exceed REBOOT_REDISCOVERY_TIMEOUT_S without being unbounded.
COMMAND_FUTURE_TIMEOUT = 120.0


def _run(coro_factory, os_id, sim):
    """Run a command coroutine and translate every failure into the typed
    {code, message} shape the panel renders.

    Sim runs synchronously via asyncio.run: there is no radio and no shared
    loop to protect. The real path submits to the scan service's own loop for
    the same reason device_snapshot does — bleak/WinRT tolerates exactly one
    loop driving the adapter, and the scan service already owns it.
    """
    service = get_scan_service(sim)

    if sim:
        # The sim registry is populated lazily by whoever polls first. The read
        # route does this too; without it a command against a simulated radio
        # would 404 until the roster happened to be fetched. (Recorded in the
        # handoff as the split sim-polling responsibility.)
        service.poll_sim()
        return jsonify(asyncio.run(coro_factory(service.registry)))

    if service.registry.get(os_id) is None:
        return jsonify(DeviceNotFound(detail=os_id).to_dict()), 404

    loop = service.loop
    if loop is None:
        return jsonify(ScanLoopUnavailable(detail=os_id).to_dict()), 409

    future = asyncio.run_coroutine_threadsafe(coro_factory(service.registry), loop)
    try:
        return jsonify(future.result(timeout=COMMAND_FUTURE_TIMEOUT))
    except FutureTimeoutError:
        future.cancel()
        return jsonify(OperationTimeout(detail=os_id).to_dict()), 409
    except BleError as exc:
        return jsonify(exc.to_dict()), 409
    except Exception as exc:
        # Never leak a traceback or a raw WinRT string to the operator; log it
        # server-side and return the typed shape the frontend expects.
        log.error('BLE: unexpected error running command for %s: %s',
                  os_id, exc, exc_info=True)
        return jsonify(UnexpectedBleFailure(detail=os_id).to_dict()), 409


def _sim_or_404(handler):
    """Sim device lookups happen inside the command service, which raises
    DeviceNotFound; translate that one case to 404 to match the read routes."""
    try:
        return handler()
    except DeviceNotFound as exc:
        return jsonify(exc.to_dict()), 404
    except BleError as exc:
        return jsonify(exc.to_dict()), 409


@ble_write.post('/devices/<os_id>/commands/prepare')
def prepare(os_id):
    """Step one: read the radio's real mode and mint a confirmation bound to
    it. Nothing is written here."""
    sim = sim_enabled(request.args)
    command = (request.get_json(silent=True) or {}).get('command', '')
    return _sim_or_404(lambda: _run(
        lambda registry: prepare_command(os_id, command, registry, sim=sim),
        os_id, sim))


@ble_write.post('/devices/<os_id>/commands')
def execute(os_id):
    """Step two: re-check everything server-side and write."""
    sim = sim_enabled(request.args)
    body = request.get_json(silent=True) or {}
    command = body.get('command', '')
    expected_mode = body.get('expectedMode')
    token = body.get('confirmationToken', '')
    return _sim_or_404(lambda: _run(
        lambda registry: execute_command(
            os_id, command, expected_mode, token, registry, sim=sim),
        os_id, sim))
```

- [ ] **Step 5: Register the blueprint behind both gates**

In `backend/app/__init__.py`, inside the existing `if app.config.get('ENABLE_BLE_TOOLS'):` block, after the `start_ble_service(app)` call (line 69), add:

```python
        # Writes are a second, separate opt-in. With ENABLE_BLE_WRITE off the
        # command routes do not exist at all, so the app is exactly the
        # read-only build.
        if app.config.get('ENABLE_BLE_WRITE'):
            from .ble_command_routes import ble_write as ble_write_bp
            app.register_blueprint(ble_write_bp)
```

Note this sits inside the `ENABLE_BLE_TOOLS` block but **outside** the `if not app.config.get('TESTING')` guard, so tests can exercise the routes without a radio thread.

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_ble_command_routes.py -v`
Expected: 8 passed.

- [ ] **Step 7: Invert the read-only route guard**

In `backend/tests/test_ble_routes.py`, replace `test_no_post_routes_exist_in_this_phase` (lines 164-168) with:

```python
def test_read_only_app_still_exposes_no_mutating_route(ble_app):
    """RELEASE GATE, carried forward. `ble_app` is built without
    ENABLE_BLE_WRITE, so it is the read-only build — and that build must
    still have no way to change a radio. The write build's routes are
    asserted separately in test_ble_command_routes.py."""
    for rule in ble_app.url_map.iter_rules():
        if str(rule).startswith('/api/ble'):
            assert rule.methods & {'POST', 'PUT', 'PATCH', 'DELETE'} == set(), str(rule)
```

- [ ] **Step 8: Run the full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: all pass. Report the count — the read-only phase ended at 286.

- [ ] **Step 9: Commit**

```bash
git add backend/app/ble_command_routes.py backend/app/__init__.py backend/app/five12_ble/command_service.py backend/tests/test_ble_command_routes.py backend/tests/test_ble_routes.py
git commit -m "feat(ble): add the prepare/execute command routes behind both gates"
```

---

## Task 10: Frontend API wrappers

**Files:**
- Modify: `app/src/lib/bleApi.js`
- Test: `app/src/lib/bleApi.test.js` (create)

**Interfaces:**
- Produces:
  - `prepareBleCommand(osId, command) -> Promise<{command, token, ttlS, deviceAlias, currentMode, warning}>`
  - `executeBleCommand(osId, {command, expectedMode, confirmationToken}) -> Promise<result>`
  - `fetchBleCapabilities()` fallback now includes `bleWriteEnabled: false`
  - Both throw the backend's typed `{code, message}` payload, matching `fetchBleSnapshot`'s existing contract.

- [ ] **Step 1: Write the failing test**

Create `app/src/lib/bleApi.test.js`:

```javascript
import { describe, expect, it, vi, beforeEach } from 'vitest'
import axios from 'axios'
import {
  executeBleCommand,
  fetchBleCapabilities,
  prepareBleCommand,
} from './bleApi'

vi.mock('axios')

beforeEach(() => { vi.resetAllMocks() })

describe('prepareBleCommand', () => {
  it('posts only the command name', async () => {
    axios.post.mockResolvedValue({ data: { token: 't', currentMode: 'tx' } })
    await prepareBleCommand('tx-1', 'link')
    expect(axios.post).toHaveBeenCalledWith(
      '/api/ble/devices/tx-1/commands/prepare',
      { command: 'link' },
    )
  })

  it('encodes an os id containing a colon', async () => {
    axios.post.mockResolvedValue({ data: {} })
    await prepareBleCommand('AA:BB:CC', 'link')
    expect(axios.post.mock.calls[0][0]).toBe(
      '/api/ble/devices/AA%3ABB%3ACC/commands/prepare')
  })

  it('rethrows the backend typed error so the operator sees its copy', async () => {
    axios.post.mockRejectedValue({
      response: { data: { code: 'wrong-mode', message: 'Link is a transmitter action.' } },
    })
    await expect(prepareBleCommand('rx-1', 'link')).rejects.toMatchObject({
      code: 'wrong-mode',
    })
  })

  it('falls back to a generic typed error when the backend sends nothing usable', async () => {
    axios.post.mockRejectedValue(new Error('network down'))
    await expect(prepareBleCommand('tx-1', 'link')).rejects.toMatchObject({
      code: 'unknown',
    })
  })
})

describe('executeBleCommand', () => {
  it('sends the command, expected mode and confirmation', async () => {
    axios.post.mockResolvedValue({ data: { attAcknowledged: true } })
    await executeBleCommand('tx-1', {
      command: 'link', expectedMode: 'tx', confirmationToken: 'tok',
    })
    expect(axios.post).toHaveBeenCalledWith('/api/ble/devices/tx-1/commands', {
      command: 'link', expectedMode: 'tx', confirmationToken: 'tok',
    })
  })

  it('never sends a uuid or a payload', async () => {
    axios.post.mockResolvedValue({ data: {} })
    await executeBleCommand('tx-1', {
      command: 'link', expectedMode: 'tx', confirmationToken: 'tok',
    })
    const body = axios.post.mock.calls[0][1]
    expect(Object.keys(body).sort()).toEqual(
      ['command', 'confirmationToken', 'expectedMode'])
  })
})

describe('fetchBleCapabilities', () => {
  it('reports writes disabled when the endpoint is unreachable', async () => {
    axios.get.mockRejectedValue(new Error('404'))
    expect(await fetchBleCapabilities()).toMatchObject({ bleWriteEnabled: false })
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app && npm run test -- bleApi`
Expected: FAIL — `prepareBleCommand is not a function`.

- [ ] **Step 3: Add the wrappers**

In `app/src/lib/bleApi.js`, add `bleWriteEnabled: false` to the `fetchBleCapabilities` fallback:

```javascript
  } catch {
    return {
      bleToolsEnabled: false,
      bleWriteEnabled: false,
      adapterAvailable: false,
      platformSupported: true,
    }
  }
```

Then append:

```javascript
// The backend sends typed errors with operator-ready copy. Pass them through
// rather than replacing them with a generic message — same contract as
// fetchBleSnapshot. Note these reject with a plain object, not an Error;
// consumers read `.message`, so do NOT add instanceof Error checks against it.
function rethrowTyped(err, fallback) {
  const payload = err?.response?.data
  throw payload?.code ? payload : { code: 'unknown', message: fallback }
}

// Step one of a write. Reads the radio's real mode server-side and returns a
// single-use confirmation bound to it, plus the warning copy the dialog must
// render verbatim. Nothing is written by this call.
export async function prepareBleCommand(osId, command) {
  try {
    const { data } = await axios.post(
      `/api/ble/devices/${encodeURIComponent(osId)}/commands/prepare`,
      { command },
    )
    return data
  } catch (err) {
    rethrowTyped(err, 'Could not prepare that action.')
  }
}

// Step two. The body carries a command NAME only — never a characteristic
// UUID and never a payload byte. The server owns that mapping.
export async function executeBleCommand(osId, { command, expectedMode, confirmationToken }) {
  try {
    const { data } = await axios.post(
      `/api/ble/devices/${encodeURIComponent(osId)}/commands`,
      { command, expectedMode, confirmationToken },
    )
    return data
  } catch (err) {
    rethrowTyped(err, 'Could not complete that action.')
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd app && npm run test -- bleApi`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add app/src/lib/bleApi.js app/src/lib/bleApi.test.js
git commit -m "feat(ble): add prepare/execute command wrappers to the BLE api client"
```

---

## Task 11: The confirmation dialog

**Files:**
- Create: `app/src/components/devices/BleActionDialog.jsx`
- Test: `app/src/components/devices/BleActionDialog.test.jsx` (create)

**Interfaces:**
- Produces: default export `BleActionDialog({ deviceAlias, hardwareId, warning, actionLabel, busy, onConfirm, onCancel })`.

- [ ] **Step 1: Write the failing test**

Create `app/src/components/devices/BleActionDialog.test.jsx`:

```javascript
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import BleActionDialog from './BleActionDialog'

const PROPS = {
  deviceAlias: 'F12L - 2071',
  hardwareId: 'F1400000',
  warning: 'Any unlinked receiver in range will pair to it.',
  actionLabel: 'Link',
  busy: false,
}

function setup(overrides = {}) {
  const onConfirm = vi.fn()
  const onCancel = vi.fn()
  render(<BleActionDialog {...PROPS} {...overrides} onConfirm={onConfirm} onCancel={onCancel} />)
  return { onConfirm, onCancel }
}

describe('BleActionDialog', () => {
  it('names the device it is about to change', () => {
    setup()
    expect(screen.getByText(/F12L - 2071/)).toBeInTheDocument()
    expect(screen.getByText(/F1400000/)).toBeInTheDocument()
  })

  it('renders the server-supplied warning verbatim', () => {
    setup()
    expect(screen.getByText(PROPS.warning)).toBeInTheDocument()
  })

  it('disables confirm until the operator acknowledges', async () => {
    const { onConfirm } = setup()
    const confirm = screen.getByRole('button', { name: /^link$/i })
    expect(confirm).toBeDisabled()
    await userEvent.click(screen.getByRole('checkbox'))
    expect(confirm).toBeEnabled()
    await userEvent.click(confirm)
    expect(onConfirm).toHaveBeenCalledTimes(1)
  })

  it('does not confirm on Enter', async () => {
    // The whole reason this is not window.confirm: muscle memory must not be
    // able to fire an action that can black out a fixture.
    const { onConfirm } = setup()
    await userEvent.click(screen.getByRole('checkbox'))
    await userEvent.keyboard('{Enter}')
    expect(onConfirm).not.toHaveBeenCalled()
  })

  it('cancels on Escape', async () => {
    const { onCancel } = setup()
    await userEvent.keyboard('{Escape}')
    expect(onCancel).toHaveBeenCalledTimes(1)
  })

  it('cancels from the cancel button', async () => {
    const { onCancel } = setup()
    await userEvent.click(screen.getByRole('button', { name: /cancel/i }))
    expect(onCancel).toHaveBeenCalledTimes(1)
  })

  it('locks both buttons while the command is in flight', async () => {
    setup({ busy: true })
    expect(screen.getByRole('button', { name: /working/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /cancel/i })).toBeDisabled()
  })

  it('is announced as a modal dialog', () => {
    setup()
    expect(screen.getByRole('dialog')).toHaveAttribute('aria-modal', 'true')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app && npm run test -- BleActionDialog`
Expected: FAIL — cannot resolve `./BleActionDialog`.

- [ ] **Step 3: Build the dialog**

Create `app/src/components/devices/BleActionDialog.jsx`:

```jsx
import { useEffect, useState } from 'react'

// Deliberately NOT window.confirm, which the Stardust panel uses for its own
// link action. A browser confirm accepts on Enter, and these commands can put
// a live fixture dark — muscle memory must not be able to fire one. So:
// a real modal, Enter does nothing, and confirm stays disabled until the
// operator ticks an acknowledgement.
export default function BleActionDialog({
  deviceAlias, hardwareId, warning, actionLabel, busy, onConfirm, onCancel,
}) {
  const [acknowledged, setAcknowledged] = useState(false)

  useEffect(() => {
    const onKeyDown = (e) => {
      if (e.key === 'Escape' && !busy) onCancel()
      // Enter is swallowed on purpose. There is no keyboard shortcut to
      // confirm; the operator must click.
      if (e.key === 'Enter') e.preventDefault()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [busy, onCancel])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`${actionLabel} ${deviceAlias}`}
        className="border border-brand bg-[var(--color-surface)] rounded-sm p-4 max-w-sm w-full space-y-3"
      >
        <div>
          <div className="text-[11px] font-mono font-bold text-text">
            {actionLabel} — {deviceAlias}
          </div>
          <div className="text-[8px] font-mono text-text-muted mt-[2px]">
            hardware id {hardwareId}
          </div>
        </div>

        {/* Server-supplied copy, rendered verbatim: the text the operator
            agrees to is the text the server will enforce. */}
        <p className="text-[10px] font-mono text-warn leading-relaxed">{warning}</p>

        <label className="flex items-start gap-2 text-[10px] font-mono text-text cursor-pointer">
          <input
            type="checkbox"
            checked={acknowledged}
            disabled={busy}
            onChange={(e) => setAcknowledged(e.target.checked)}
            className="mt-[2px]"
          />
          <span>I understand what this will do.</span>
        </label>

        <div className="flex justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="text-[9px] font-mono px-3 py-1 border border-[var(--color-border)] rounded-sm hover:border-brand disabled:opacity-40"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={!acknowledged || busy}
            className="text-[9px] font-mono px-3 py-1 border border-brand text-brand-hi rounded-sm hover:bg-brand/10 disabled:opacity-40"
          >
            {busy ? 'working…' : actionLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd app && npm run test -- BleActionDialog`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add app/src/components/devices/BleActionDialog.jsx app/src/components/devices/BleActionDialog.test.jsx
git commit -m "feat(ble): add a checkbox-gated confirmation modal for radio writes"
```

---

## Task 12: The Control section

**Files:**
- Modify: `app/src/components/devices/CintennaPanel.jsx`
- Modify: `app/src/components/devices/CintennaPanel.test.jsx:109-118`

**Interfaces:**
- Consumes: `fetchBleCapabilities`, `prepareBleCommand`, `executeBleCommand`, `BleActionDialog`.
- Produces: no exports beyond the existing default.

- [ ] **Step 1: Write the failing tests**

In `app/src/components/devices/CintennaPanel.test.jsx`, replace the release-gate test at lines 109-118 with the block below, and add `bleApi.fetchBleCapabilities.mockResolvedValue({ bleToolsEnabled: true, bleWriteEnabled: false })` to the existing `beforeEach`:

```javascript
  const WRITE_ON = { bleToolsEnabled: true, bleWriteEnabled: true }

  const TX_SNAPSHOT = {
    osId: 'tx-1',
    fields: { mode: { decoded: 'tx', raw: '01', source: 'gatt-read', readAt: 1 } },
    warnings: [],
  }

  // Note: once the Control section renders, 'TX' appears BOTH as the mode
  // field and as the active segment of the mode toggle, so findByText would
  // throw on multiple matches. findAllByText is correct in both states.
  async function openTx() {
    bleApi.fetchBleDevices.mockResolvedValue(DEVICES)
    bleApi.fetchBleSnapshot.mockResolvedValue(TX_SNAPSHOT)
    render(<CintennaPanel />)
    await userEvent.click(await screen.findByRole('button', { name: /F12L - 2071/ }))
    await userEvent.click(screen.getByRole('button', { name: /read status/i }))
    await screen.findAllByText('TX')
  }

  // With the dialog open, the panel's trigger and the dialog's confirm share a
  // label. The confirm button is the last one in the DOM.
  function confirmButton(label) {
    return screen.getAllByRole('button', { name: label }).pop()
  }

  it('renders no write control when the write gate is off', async () => {
    // RELEASE GATE, inverted: the read-only build must stay read-only.
    bleApi.fetchBleCapabilities.mockResolvedValue({
      bleToolsEnabled: true, bleWriteEnabled: false,
    })
    bleApi.fetchBleDevices.mockResolvedValue(DEVICES)
    bleApi.fetchBleSnapshot.mockResolvedValue(TX_SNAPSHOT)
    render(<CintennaPanel />)
    await userEvent.click(await screen.findByRole('button', { name: /F12L - 2071/ }))
    await userEvent.click(screen.getByRole('button', { name: /read status/i }))
    // Single-match findByText on purpose here, unlike openTx(): with the gate
    // off the mode toggle must not render, so a second 'TX' would mean the
    // control leaked into the read-only build. Do not "fix" this to findAll.
    await screen.findByText('TX')
    for (const label of [/^link$/i, /^unlink$/i, /switch to/i]) {
      expect(screen.queryByRole('button', { name: label })).not.toBeInTheDocument()
    }
  })

  it('renders no write control before a status read, when the mode is unknown', async () => {
    bleApi.fetchBleCapabilities.mockResolvedValue(WRITE_ON)
    bleApi.fetchBleDevices.mockResolvedValue(DEVICES)
    render(<CintennaPanel />)
    await userEvent.click(await screen.findByRole('button', { name: /F12L - 2071/ }))
    expect(screen.queryByRole('button', { name: /^link$/i })).not.toBeInTheDocument()
  })

  it('offers Link but never Unlink on a transmitter', async () => {
    bleApi.fetchBleCapabilities.mockResolvedValue(WRITE_ON)
    await openTx()
    expect(screen.getByRole('button', { name: /^link$/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^unlink$/i })).not.toBeInTheDocument()
  })

  it('offers Unlink but never Link on a receiver', async () => {
    bleApi.fetchBleCapabilities.mockResolvedValue(WRITE_ON)
    bleApi.fetchBleDevices.mockResolvedValue(DEVICES)
    bleApi.fetchBleSnapshot.mockResolvedValue(SNAPSHOT)   // mode rx
    render(<CintennaPanel />)
    await userEvent.click(await screen.findByRole('button', { name: /F12L - 1946/ }))
    await userEvent.click(screen.getByRole('button', { name: /read status/i }))
    await screen.findAllByText('RX')
    expect(screen.getByRole('button', { name: /^unlink$/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^link$/i })).not.toBeInTheDocument()
  })

  it('confirms before writing, and sends the prepared token', async () => {
    bleApi.fetchBleCapabilities.mockResolvedValue(WRITE_ON)
    bleApi.prepareBleCommand.mockResolvedValue({
      command: 'link', token: 'tok-1', ttlS: 60, deviceAlias: 'F12L - 2071',
      currentMode: 'tx', warning: 'Any unlinked receiver in range will pair to it.',
    })
    bleApi.executeBleCommand.mockResolvedValue({
      command: 'link', attAcknowledged: true, verification: 'ack-only',
      mode: { decoded: 'tx' }, durationMs: 400,
    })
    await openTx()
    await userEvent.click(screen.getByRole('button', { name: /^link$/i }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    expect(bleApi.executeBleCommand).not.toHaveBeenCalled()

    await userEvent.click(screen.getByRole('checkbox'))
    await userEvent.click(confirmButton(/^link$/i))

    await waitFor(() => expect(bleApi.executeBleCommand).toHaveBeenCalledWith('tx-1', {
      command: 'link', expectedMode: 'tx', confirmationToken: 'tok-1',
    }))
  })

  it('never claims a link was made', async () => {
    bleApi.fetchBleCapabilities.mockResolvedValue(WRITE_ON)
    bleApi.prepareBleCommand.mockResolvedValue({
      command: 'link', token: 'tok-1', ttlS: 60, deviceAlias: 'F12L - 2071',
      currentMode: 'tx', warning: 'warning copy',
    })
    bleApi.executeBleCommand.mockResolvedValue({
      command: 'link', attAcknowledged: true, verification: 'ack-only',
      mode: { decoded: 'tx' }, durationMs: 400,
    })
    await openTx()
    await userEvent.click(screen.getByRole('button', { name: /^link$/i }))
    await userEvent.click(screen.getByRole('checkbox'))
    await userEvent.click(confirmButton(/^link$/i))

    expect(await screen.findByText(/not confirmation/i)).toBeInTheDocument()
    expect(screen.queryByText(/^linked/i)).not.toBeInTheDocument()
  })

  it('reports an accepted-but-unverified mode change as neither success nor failure', async () => {
    bleApi.fetchBleCapabilities.mockResolvedValue(WRITE_ON)
    bleApi.prepareBleCommand.mockResolvedValue({
      command: 'set_mode_rx', token: 'tok-2', ttlS: 60,
      deviceAlias: 'F12L - 2071', currentMode: 'tx', warning: 'It will restart.',
    })
    bleApi.executeBleCommand.mockResolvedValue({
      command: 'set_mode_rx', attAcknowledged: true,
      verification: 'accepted-unverified', mode: { decoded: 'tx' }, durationMs: 31000,
    })
    await openTx()
    await userEvent.click(screen.getByRole('button', { name: /switch to rx/i }))
    await userEvent.click(screen.getByRole('checkbox'))
    await userEvent.click(confirmButton(/switch to rx/i))
    expect(await screen.findByText(/accepted, but not verified/i)).toBeInTheDocument()
  })

  it('shows the operator copy when the server refuses the write', async () => {
    bleApi.fetchBleCapabilities.mockResolvedValue(WRITE_ON)
    bleApi.prepareBleCommand.mockRejectedValue({
      code: 'wrong-mode', message: 'Link is a transmitter action; Unlink is a receiver action.',
    })
    await openTx()
    await userEvent.click(screen.getByRole('button', { name: /^link$/i }))
    expect(await screen.findByText(/transmitter action/i)).toBeInTheDocument()
  })
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd app && npm run test -- CintennaPanel`
Expected: FAIL — no Link/Unlink/switch controls exist yet.

- [ ] **Step 3: Add the Control section**

In `app/src/components/devices/CintennaPanel.jsx`, extend the imports:

```jsx
import { useEffect, useRef, useState } from 'react'
import {
  executeBleCommand,
  fetchBleCapabilities,
  fetchBleDevices,
  fetchBleSnapshot,
  prepareBleCommand,
  signalBars,
} from '../../lib/bleApi'
import BleActionDialog from './BleActionDialog'
import BleEvidenceBadge from './BleEvidenceBadge'
```

Add these helpers above the component:

```jsx
// Outcome copy. "Accepted, unverified" is a first-class result, not an error:
// the radio acknowledged the write and did not come back in the new mode.
// Saying "done" would be a lie and saying "failed" would be one too.
const OUTCOME = {
  'ack-only': {
    tone: 'text-online',
    text: (r) => `Write accepted by the radio. This is not confirmation that ` +
                 `a ${r.command === 'link' ? 'link' : 'change'} was made.`,
  },
  verified: {
    tone: 'text-online',
    text: () => 'Verified — the radio came back in the new mode.',
  },
  'accepted-unverified': {
    tone: 'text-warn',
    text: () => 'Accepted, but not verified. The radio answered in its previous ' +
                'mode. Read status to check.',
  },
  'device-did-not-return': {
    tone: 'text-brand-hi',
    text: () => 'The radio did not come back in time. It may still be ' +
                'restarting — wait for it to reappear, then read status.',
  },
}

const ACTION_LABEL = {
  link: 'Link',
  unlink: 'Unlink',
  set_mode_rx: 'Switch to RX',
  set_mode_tx: 'Switch to TX',
}
```

Add state inside the component, below the existing `useState` calls:

```jsx
  const [writeEnabled, setWriteEnabled] = useState(false)
  const [pending, setPending] = useState(null)     // {command, prep}
  const [working, setWorking] = useState(false)
  const [outcome, setOutcome] = useState(null)
  const [writeError, setWriteError] = useState(null)

  useEffect(() => {
    let alive = true
    fetchBleCapabilities().then((caps) => {
      if (alive) setWriteEnabled(Boolean(caps?.bleWriteEnabled))
    })
    return () => { alive = false }
  }, [])
```

Add the command handlers below `readStatus`:

```jsx
  // Step one: ask the server for the radio's real mode and a confirmation
  // bound to it. Nothing is written until the operator confirms.
  const startCommand = async (command) => {
    setWriteError(null)
    setOutcome(null)
    try {
      const prep = await prepareBleCommand(selected.osId, command)
      setPending({ command, prep })
    } catch (err) {
      setWriteError(err)
    }
  }

  const confirmCommand = async () => {
    const { command, prep } = pending
    setWorking(true)
    try {
      const result = await executeBleCommand(selected.osId, {
        command,
        expectedMode: prep.currentMode,
        confirmationToken: prep.token,
      })
      setOutcome(result)
      setPending(null)
      // Do NOT clear the snapshot: the Control section is only rendered when
      // one exists, so blanking it here would take the outcome message down
      // with it and the operator would never see what happened.
      //
      // Instead fold the post-write mode reading in, keeping its evidence
      // source honest. A mode we could not verify is left alone rather than
      // overwritten with a value we do not have.
      if (result.mode?.decoded) {
        setSnapshot((prev) => (prev ? {
          ...prev,
          fields: {
            ...prev.fields,
            mode: { ...prev.fields.mode, decoded: result.mode.decoded,
                    source: 'post-write-readback' },
          },
        } : prev))
      }
    } catch (err) {
      setWriteError(err)
      setPending(null)
    } finally {
      setWorking(false)
    }
  }
```

Insert the Control section inside the `{selected && ...}` card, directly after the `{snapshot && (...)}` block:

```jsx
          {/* Writes are a separate opt-in, and we must know the radio's real
              mode before offering anything. Absent, not disabled: a control
              that cannot be used is noise. */}
          {writeEnabled && snapshot && selectedNearby && fields.mode?.decoded && (
            <div className="mt-3 border-t border-[var(--color-surface-2)] pt-2 space-y-2">
              <div className="text-[8px] font-mono text-text-muted uppercase tracking-widest">
                control
              </div>

              <div className="flex items-center gap-2">
                <span className="text-[9px] font-mono text-text-muted">mode</span>
                {['rx', 'tx'].map((m) => (
                  <button
                    key={m}
                    type="button"
                    disabled={fields.mode.decoded === m}
                    aria-pressed={fields.mode.decoded === m}
                    onClick={() => startCommand(m === 'rx' ? 'set_mode_rx' : 'set_mode_tx')}
                    className={'text-[9px] font-mono px-2 py-1 rounded-sm border ' +
                      (fields.mode.decoded === m
                        ? 'border-brand bg-brand-dim/30 text-text'
                        : 'border-[var(--color-border)] hover:border-brand')}
                  >
                    {fields.mode.decoded === m ? m.toUpperCase() : `Switch to ${m.toUpperCase()}`}
                  </button>
                ))}
              </div>

              {/* Never both. Link is a transmitter action; Unlink is a
                  receiver action. The server re-checks this regardless. */}
              <div>
                {fields.mode.decoded === 'tx' && (
                  <button
                    type="button"
                    onClick={() => startCommand('link')}
                    className="text-[9px] font-mono px-3 py-1 border border-brand text-brand-hi rounded-sm hover:bg-brand/10"
                  >
                    Link
                  </button>
                )}
                {fields.mode.decoded === 'rx' && (
                  <button
                    type="button"
                    onClick={() => startCommand('unlink')}
                    className="text-[9px] font-mono px-3 py-1 border border-brand text-brand-hi rounded-sm hover:bg-brand/10"
                  >
                    Unlink
                  </button>
                )}
              </div>

              {outcome && (
                <div className={'text-[10px] font-mono leading-relaxed ' +
                  (OUTCOME[outcome.verification]?.tone || 'text-text-muted')}>
                  {OUTCOME[outcome.verification]?.text(outcome) || 'Done.'}
                </div>
              )}

              {writeError && (
                <div className="text-[10px] font-mono text-amber-400 leading-relaxed">
                  {writeError.message}
                </div>
              )}
            </div>
          )}
```

Add the dialog just before the closing `</div>` of the component's root, after the footer line:

```jsx
      {pending && (
        <BleActionDialog
          deviceAlias={pending.prep.deviceAlias || selected.localName}
          hardwareId={selected.hardwareId}
          warning={pending.prep.warning}
          actionLabel={ACTION_LABEL[pending.command]}
          busy={working}
          onConfirm={confirmCommand}
          onCancel={() => setPending(null)}
        />
      )}
```

Finally update the footer text at the bottom of the component:

```jsx
      <div className="text-[8px] text-text-muted font-mono border-t border-[var(--color-surface-2)] pt-2">
        passive BLE advertisement + connected GATT reads · writes are allowlisted,
        mode-gated and confirmed · an acknowledgement is not proof of RF association
      </div>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd app && npm run test -- CintennaPanel`
Expected: all pass, including the pre-existing read-only tests.

- [ ] **Step 5: Run the whole frontend suite and build**

Run: `cd app && npm run test`
Expected: all pass — the read-only phase ended at 20; expect roughly 45.

Run: `cd app && npm run build`
Expected: succeeds.

- [ ] **Step 6: Commit**

```bash
git add app/src/components/devices/CintennaPanel.jsx app/src/components/devices/CintennaPanel.test.jsx
git commit -m "feat(ble): add the mode toggle, Link and Unlink controls to the Cintenna panel"
```

---

## Task 13: Hardware acceptance checklist

Automated tests prove the plumbing. They cannot prove a radio does what the capture said it does.

**Files:**
- Create: `docs/architecture/cintenna-ble-write-acceptance.md`
- Modify: `docs/architecture/cintenna-ble-handoff.md`

- [ ] **Step 1: Verify the full suite is green before writing the checklist**

Run: `cd backend && python -m pytest -q`
Run: `cd app && npm run test`
Run: `cd app && npm run build`

Record the three actual numbers; they go in the document. If anything fails, stop and fix it — a checklist written over a red suite is worthless.

- [ ] **Step 2: Write the checklist**

Create `docs/architecture/cintenna-ble-write-acceptance.md`:

```markdown
# Cintenna BLE Write Phase — Hardware Acceptance

Run on the Windows 11 ThinkPad against the known Cintenna, firmware `1.0.7.2`.

Launch with both gates on:

    cd backend
    $env:FIVE12_BLE_TOOLS='1'; $env:FIVE12_BLE_WRITE='1'
    & 'C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe' -m flask run --port 5000

## Before you start — Link is hazardous

Link puts a transmitter into pairing mode. **Any unlinked receiver in range
will pair to it**, not only the one you intend. Either isolate the RF
environment or knowingly accept the risk to other CRMX gear present. Do not run
this step during a show.

## Gate behaviour

- [ ] With `FIVE12_BLE_WRITE` unset, the Cintenna panel shows no mode toggle,
      no Link, and no Unlink
- [ ] With it unset, `POST /api/ble/devices/x/commands` returns 404
- [ ] With both gates unset, Patch, Labels, Network and Devices all work

## Reads still work

- [ ] Passive scan finds the radio, Toolbox closed
- [ ] Read status returns battery, firmware and mode

## Unlink (receiver)

- [ ] On an RX radio, Unlink is offered and Link is not
- [ ] The dialog names the radio and warns that its fixture goes dark
- [ ] Confirm is disabled until the checkbox is ticked
- [ ] Pressing Enter in the dialog does nothing
- [ ] After confirming, the result says the write was accepted and does **not**
      claim anything about RF association
- [ ] The receiver has actually dropped its transmitter (verify on the fixture)

## Mode change — measure the timing

- [ ] Switch RX → TX. **Time how long** until the radio reappears and the mode
      reads back
- [ ] Record that figure here: ................ seconds
- [ ] If it exceeds `REBOOT_REDISCOVERY_TIMEOUT_S` (currently 30.0 in
      `command_service.py`), raise the constant and re-run
- [ ] The panel showed progress during the reboot rather than appearing frozen
- [ ] Outcome reported as "verified", not "accepted, unverified"
- [ ] Switch TX → RX and confirm the same

## Device identity across the reboot

- [ ] After a mode change, does the radio return with the **same** osId?
      Yes / No: ................
- [ ] If No, the panel must ask the operator to re-select it from the roster
      rather than silently acting on a stale selection. Confirm it does.

## Link (transmitter) — RF isolation required

- [ ] On a TX radio, Link is offered and Unlink is not
- [ ] The dialog warns that any unlinked receiver in range will pair
- [ ] After confirming, a receiver actually pairs
- [ ] The result copy does not say "linked"

## Refusals

- [ ] Open the dialog on a TX radio, change its mode from Toolbox or the panel
      in another window, then confirm — the write is refused as stale
- [ ] Leave a dialog open for over 60 seconds, then confirm — refused as an
      expired confirmation

## Toolbox conflict during a write

- [ ] Open CRMX Toolbox, connect it to the radio, then attempt a write
- [ ] The error names Toolbox and tells the operator to close it

  This is the known-fragile English-substring detection recorded in the
  handoff. If the message is the generic out-of-range one instead, record the
  exact error text here for the eventual HRESULT-based fix.
```

- [ ] **Step 3: Point the handoff at the new work**

In `docs/architecture/cintenna-ble-handoff.md`, under the "Next phase" section, append:

```markdown
Implementation plan:
[`../superpowers/plans/2026-07-27-cintenna-ble-write-phase.md`](../superpowers/plans/2026-07-27-cintenna-ble-write-phase.md).
Hardware acceptance for it:
[`cintenna-ble-write-acceptance.md`](cintenna-ble-write-acceptance.md).

The write phase keeps every release blocker from the read-only phase except
"no write path", which becomes "no write path outside the four-command
allowlist". The four guard tests were inverted rather than deleted — see the
plan's Tasks 2, 4, 9 and 12.
```

- [ ] **Step 4: Commit**

```bash
git add docs/architecture/cintenna-ble-write-acceptance.md docs/architecture/cintenna-ble-handoff.md
git commit -m "docs: add the write-phase hardware acceptance checklist"
```

---

## Definition of done

- `cd backend && python -m pytest -q` passes
- `cd app && npm run test` passes
- `cd app && npm run build` succeeds
- With `FIVE12_BLE_WRITE` unset, the app is byte-for-byte the read-only experience: no command routes in the URL map, no controls in the panel
- The only writable UUIDs are `MODE` and `LINK_ACTION`, both derived from the command table
- No field, string, or class named `linked` exists anywhere in the write path
- The hardware acceptance checklist has been run and its two measured values recorded
