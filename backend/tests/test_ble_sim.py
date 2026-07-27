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
