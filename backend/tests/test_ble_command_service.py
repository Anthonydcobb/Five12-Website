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
