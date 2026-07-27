"""connect() locking, cleanup, and error translation.

bleak is deliberately NOT installed on the test interpreter (connection_manager
imports it lazily, inside connect(), so the pure modules stay importable
without it). To exercise connect() at all we inject a fake `bleak` package
into sys.modules for the duration of each test via monkeypatch, then undo it
automatically when the test ends. Nothing here installs bleak or changes the
lazy import.
"""

import asyncio
import sys
import time
import types

import pytest

from app.five12_ble import connection_manager as cm
from app.five12_ble.errors import (
    DeviceBusy,
    DeviceNotFound,
    OperationTimeout,
    ToolboxHoldingConnection,
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class FakeCharacteristic:
    def __init__(self, uuid):
        self.uuid = uuid


class FakeService:
    def __init__(self, uuids):
        self.characteristics = [FakeCharacteristic(u) for u in uuids]


class FakeBleakClient:
    """Stands in for a bleak BleakClient. Every knob a test needs is a
    constructor argument so each test can describe exactly the radio
    behaviour it wants without subclassing."""

    def __init__(
        self,
        address,
        timeout=None,
        *,
        connect_error=None,
        disconnect_side_effects=None,
        char_uuids=(),
        read_values=None,
    ):
        self.address = address
        self.timeout = timeout
        self._connect_error = connect_error
        # One entry consumed per disconnect() call, so a test can make the
        # first disconnect misbehave and a later one succeed normally.
        self._disconnect_side_effects = list(disconnect_side_effects or [])
        self.services = [FakeService(char_uuids)] if char_uuids else []
        self.disconnect_calls = 0
        self._read_values = read_values or {}

    async def connect(self):
        if self._connect_error is not None:
            raise self._connect_error

    async def disconnect(self):
        self.disconnect_calls += 1
        if self._disconnect_side_effects:
            effect = self._disconnect_side_effects.pop(0)
            if effect is not None:
                await effect()

    async def read_gatt_char(self, uuid):
        return self._read_values.get(uuid, b'')


def install_fake_bleak(monkeypatch, clients_by_address):
    """Injects a fake `bleak` module (and `bleak.exc`) into sys.modules and
    returns the fake BleakError class so tests can raise it from a fake
    client's connect().

    `clients_by_address` maps an os_id to either a single FakeBleakClient
    (reused for every connect() call against that address) or a list of
    FakeBleakClient instances, popped one per connect() call — needed for
    tests that connect to the same device twice and want different behaviour
    each time. monkeypatch un-registers the fake module automatically when
    the test ends, so bleak is never actually installed.
    """

    class BleakError(Exception):
        pass

    def bleak_client_factory(address, timeout=None):
        entry = clients_by_address[address]
        if isinstance(entry, list):
            return entry.pop(0)
        return entry

    bleak_module = types.ModuleType('bleak')
    bleak_module.BleakClient = bleak_client_factory

    bleak_exc_module = types.ModuleType('bleak.exc')
    bleak_exc_module.BleakError = BleakError

    monkeypatch.setitem(sys.modules, 'bleak', bleak_module)
    monkeypatch.setitem(sys.modules, 'bleak.exc', bleak_exc_module)
    return BleakError


# ---------------------------------------------------------------------------
# Happy path / cleanup guarantees
# ---------------------------------------------------------------------------


def test_successful_connect_yields_adapter_and_disconnects_on_the_way_out(monkeypatch):
    fake = FakeBleakClient('AA:BB', char_uuids=['1234'])
    install_fake_bleak(monkeypatch, {'AA:BB': fake})

    async def scenario():
        async with cm.connect('AA:BB') as client:
            assert client.has_characteristic('1234')
        assert fake.disconnect_calls == 1

    _run(scenario())


def test_disconnect_is_still_called_when_the_body_raises(monkeypatch):
    fake = FakeBleakClient('AA:BB', char_uuids=['1234'])
    install_fake_bleak(monkeypatch, {'AA:BB': fake})

    async def scenario():
        with pytest.raises(RuntimeError):
            async with cm.connect('AA:BB'):
                raise RuntimeError('caller blew up')
        assert fake.disconnect_calls == 1

    _run(scenario())


def test_lock_is_released_after_normal_exit_so_a_second_connect_succeeds(monkeypatch):
    first = FakeBleakClient('AA:BB')
    second = FakeBleakClient('AA:BB')
    install_fake_bleak(monkeypatch, {'AA:BB': [first, second]})

    async def scenario():
        async with cm.connect('AA:BB'):
            pass
        # Second connect for the same device must not raise DeviceBusy —
        # the first one released the lock on its way out.
        async with cm.connect('AA:BB'):
            pass

    _run(scenario())


def test_lock_is_released_when_client_connect_raises(monkeypatch):
    # BleakError only exists once the fake bleak.exc module is installed, so
    # install first (with a placeholder client dict), then build the real
    # clients using the class it returned, then point the dict at them.
    clients_by_address = {}
    BleakError = install_fake_bleak(monkeypatch, clients_by_address)
    clients_by_address['AA:BB'] = [
        FakeBleakClient('AA:BB', connect_error=BleakError('nope')),
        FakeBleakClient('AA:BB'),
    ]

    async def scenario():
        with pytest.raises(DeviceNotFound):
            async with cm.connect('AA:BB'):
                pass
        # The device must not be permanently poisoned by a failed connect.
        async with cm.connect('AA:BB'):
            pass

    _run(scenario())


# ---------------------------------------------------------------------------
# Regression test — Finding 1: CancelledError out of disconnect() must not
# skip lock.release(). Before the fix, contextlib.suppress(Exception) let a
# CancelledError from client.disconnect() escape the finally block before
# lock.release() ran, permanently wedging the device.
# ---------------------------------------------------------------------------


def test_cancelled_disconnect_still_releases_the_lock_and_still_propagates(monkeypatch):
    poisoned_disconnect_count = 0

    async def raise_cancelled():
        raise asyncio.CancelledError()

    first = FakeBleakClient('AA:BB', disconnect_side_effects=[raise_cancelled])
    second = FakeBleakClient('AA:BB')
    install_fake_bleak(monkeypatch, {'AA:BB': [first, second]})

    async def scenario():
        # CancelledError must still reach the caller — it must never be
        # swallowed, only the lock release must be guaranteed ahead of it.
        with pytest.raises(asyncio.CancelledError):
            async with cm.connect('AA:BB'):
                pass

        # THE regression check: the device must be usable again immediately,
        # not wedged in DeviceBusy forever.
        async with cm.connect('AA:BB'):
            pass

    _run(scenario())
    assert first.disconnect_calls == 1
    assert second.disconnect_calls == 1


# ---------------------------------------------------------------------------
# Regression test — Finding 2: an unbounded disconnect() must not hang
# cleanup forever. DISCONNECT_TIMEOUT is patched down to a couple hundredths
# of a second so this stays fast even though the fake disconnect "hangs" for
# a couple of real seconds if nothing bounds it.
# ---------------------------------------------------------------------------


def test_hung_disconnect_is_bounded_by_the_timeout(monkeypatch):
    monkeypatch.setattr(cm, 'DISCONNECT_TIMEOUT', 0.05, raising=False)

    async def hang_forever_ish():
        # Long relative to the patched timeout. If disconnect() is bounded,
        # wait_for cuts this off almost immediately; if it isn't, the test
        # actually waits out the sleep and the elapsed-time assertion fails.
        await asyncio.sleep(2.0)

    fake = FakeBleakClient('AA:BB', disconnect_side_effects=[hang_forever_ish])
    install_fake_bleak(monkeypatch, {'AA:BB': fake})

    async def scenario():
        start = time.monotonic()
        # A disconnect that times out must not raise out of the context
        # manager — it must not mask whatever the caller's body was doing.
        async with cm.connect('AA:BB'):
            pass
        return time.monotonic() - start

    elapsed = _run(scenario())
    assert elapsed < 1.0, f'disconnect was not bounded, took {elapsed:.2f}s'


# ---------------------------------------------------------------------------
# Locking semantics
# ---------------------------------------------------------------------------


def test_concurrent_connect_to_same_device_raises_device_busy(monkeypatch):
    fake = FakeBleakClient('AA:BB')
    install_fake_bleak(monkeypatch, {'AA:BB': fake})

    async def scenario():
        async with cm.connect('AA:BB'):
            with pytest.raises(DeviceBusy):
                async with cm.connect('AA:BB'):
                    pass

    _run(scenario())


def test_two_different_devices_can_be_connected_at_the_same_time(monkeypatch):
    fake_a = FakeBleakClient('AA:BB')
    fake_b = FakeBleakClient('CC:DD')
    install_fake_bleak(monkeypatch, {'AA:BB': fake_a, 'CC:DD': fake_b})

    async def scenario():
        async with cm.connect('AA:BB'):
            async with cm.connect('CC:DD'):
                pass  # both open at once — the lock is per device, not global

    _run(scenario())


# ---------------------------------------------------------------------------
# Error translation
# ---------------------------------------------------------------------------


def test_in_use_bleak_error_becomes_toolbox_holding_connection(monkeypatch):
    clients_by_address = {}
    BleakError = install_fake_bleak(monkeypatch, clients_by_address)
    clients_by_address['AA:BB'] = FakeBleakClient(
        'AA:BB', connect_error=BleakError('GATT error: device in use by another process')
    )

    async def scenario():
        with pytest.raises(ToolboxHoldingConnection):
            async with cm.connect('AA:BB'):
                pass

    _run(scenario())


def test_timeout_becomes_operation_timeout(monkeypatch):
    clients_by_address = {}
    install_fake_bleak(monkeypatch, clients_by_address)
    clients_by_address['AA:BB'] = FakeBleakClient('AA:BB', connect_error=asyncio.TimeoutError())

    async def scenario():
        with pytest.raises(OperationTimeout):
            async with cm.connect('AA:BB'):
                pass

    _run(scenario())


def test_generic_bleak_error_becomes_device_not_found(monkeypatch):
    clients_by_address = {}
    BleakError = install_fake_bleak(monkeypatch, clients_by_address)
    clients_by_address['AA:BB'] = FakeBleakClient(
        'AA:BB', connect_error=BleakError('unknown failure 0x8007')
    )

    async def scenario():
        with pytest.raises(DeviceNotFound):
            async with cm.connect('AA:BB'):
                pass

    _run(scenario())
