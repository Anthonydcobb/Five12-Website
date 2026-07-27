"""Passive advertisement decoding — pure, no I/O, no bleak.

Byte layout confirmed against LumenRadio's official example app:

    byte 0      present but not interpreted by the example app
    bytes 1-4   hardware ID
    bytes 5-6   embedded ESTA manufacturer ID
    bytes 7-8   model ID

Observed on a RatPac Cintenna: 03 F1 40 00 00 4C 55 F1 40

Every function here must tolerate arbitrary bytes. The scan loop sees every
BLE advertiser in the room, and one malformed neighbour must not stop it.
"""

from .constants import (
    ACCEPTED_COMPANY_IDS,
    ESTA_LUMENRADIO,
    MODEL_TIMOTWO,
    TIMOTWO_SERVICE_UUID,
)

PLATFORM_TIMOTWO = 'lumenradio-timotwo-compatible'


def is_timotwo_service(uuid):
    """bleak lowercases discovered UUIDs, but advertisement sources and manual
    fixtures may not — compare case-insensitively."""
    return isinstance(uuid, str) and uuid.lower() == TIMOTWO_SERVICE_UUID


def _slice_hex(payload, start, end):
    """Upper-case hex for payload[start:end], or None if the payload is too
    short. Never raises."""
    if len(payload) < end:
        return None
    return payload[start:end].hex().upper()


def decode_manufacturer_data(company_id, payload):
    """Decode a BLE manufacturer-data record.

    `platform` is claimed only when both the outer company key and the embedded
    ESTA/model IDs agree. `product` is ALWAYS None: the radio platform does not
    identify the enclosure, and calling a TimoTwo a "Cintenna 2" on this
    evidence is an overclaim.
    """
    payload = payload or b''
    hardware_id = _slice_hex(payload, 1, 5)
    esta_id = _slice_hex(payload, 5, 7)
    model_id = _slice_hex(payload, 7, 9)

    evidence = []
    if company_id in ACCEPTED_COMPANY_IDS:
        evidence.append('manufacturer-data')

    platform = None
    if evidence and esta_id == ESTA_LUMENRADIO and model_id == MODEL_TIMOTWO:
        platform = PLATFORM_TIMOTWO

    return {
        'platform': platform,
        'product': None,
        'hardwareId': hardware_id,
        'estaManufacturerId': esta_id,
        'modelId': model_id,
        'unknownByte0': _slice_hex(payload, 0, 1),
        'rawManufacturerData': payload.hex().upper(),
        'evidence': evidence if platform else [],
    }
