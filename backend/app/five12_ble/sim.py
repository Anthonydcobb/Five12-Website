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
