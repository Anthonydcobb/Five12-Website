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
