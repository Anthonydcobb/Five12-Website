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
