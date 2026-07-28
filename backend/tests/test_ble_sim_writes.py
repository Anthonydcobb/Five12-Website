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
