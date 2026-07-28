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
       from its reboot. `client.writes` is how we tell them apart.
    2. _verify_after_reboot polls against a real deadline, so a no-op sleep
       would spin for the full 30s of wall clock. The injected sleep advances
       a virtual clock that time.monotonic reads, making every outcome
       deterministic and instant.

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
