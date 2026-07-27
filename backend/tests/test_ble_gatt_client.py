"""Snapshot building. A single failed characteristic read must degrade to one
null field, never fail the whole device — a Cintenna missing one characteristic
is still worth showing battery and mode for."""

import asyncio

import pytest

from app.five12_ble import constants as c
from app.five12_ble.connection_manager import BleakClientAdapter
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


def test_production_client_adapter_offers_no_write_method():
    """The FakeClient check above only tests the test double. This is the
    class that actually wraps bleak in production — BleakClientAdapter — and
    it must be shaped the same way: no write_gatt_char, no write-shaped
    method of any name. "No write path" is the single most important
    property of this branch, so the real class must be gated, not just the
    fake one."""
    write_shaped = [
        name for name in dir(BleakClientAdapter)
        if 'write' in name.lower()
    ]
    assert write_shaped == []
