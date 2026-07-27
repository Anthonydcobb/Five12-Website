"""Advertisement decoding is pure and must never raise — a malformed payload
from unrelated BLE gear in the room cannot be allowed to kill the scan loop."""

from app.five12_ble.advertisement import decode_manufacturer_data, is_timotwo_service

OBSERVED = bytes.fromhex('03F14000004C55F140')   # captured from F12L - 1946


def test_decodes_observed_cintenna_payload():
    out = decode_manufacturer_data(0xFFFF, OBSERVED)
    assert out['hardwareId'] == 'F1400000'
    assert out['estaManufacturerId'] == '4C55'
    assert out['modelId'] == 'F140'
    assert out['platform'] == 'lumenradio-timotwo-compatible'
    assert out['rawManufacturerData'] == '03F14000004C55F140'


def test_product_is_never_inferred():
    """A TimoTwo radio is inside many enclosures. Claiming "Cintenna 2" from
    the radio platform alone is exactly the overclaim the reference warns of."""
    out = decode_manufacturer_data(0xFFFF, OBSERVED)
    assert out['product'] is None


def test_unknown_byte_zero_preserved_raw():
    out = decode_manufacturer_data(0xFFFF, OBSERVED)
    assert out['unknownByte0'] == '03'


def test_production_company_id_accepted():
    out = decode_manufacturer_data(0x09E9, OBSERVED)
    assert 'manufacturer-data' in out['evidence']
    assert out['platform'] == 'lumenradio-timotwo-compatible'


def test_unrecognised_company_id_yields_no_platform_claim():
    out = decode_manufacturer_data(0x004C, OBSERVED)   # Apple
    assert out['platform'] is None
    assert out['evidence'] == []


def test_short_payload_does_not_raise():
    out = decode_manufacturer_data(0xFFFF, b'\x03\xf1')
    assert out['hardwareId'] is None
    assert out['modelId'] is None
    assert out['rawManufacturerData'] == '03F1'


def test_empty_payload_does_not_raise():
    out = decode_manufacturer_data(0xFFFF, b'')
    assert out['hardwareId'] is None
    assert out['rawManufacturerData'] == ''


def test_wrong_esta_id_still_decodes_but_makes_no_platform_claim():
    payload = bytes.fromhex('03F1400000FFFFF140')
    out = decode_manufacturer_data(0xFFFF, payload)
    assert out['estaManufacturerId'] == 'FFFF'
    assert out['platform'] is None


def test_service_match_is_case_insensitive():
    assert is_timotwo_service('33B5376D-0942-1F91-379B-AC5AF36B9EFA')
    assert is_timotwo_service('33b5376d-0942-1f91-379b-ac5af36b9efa')
    assert not is_timotwo_service('0000180f-0000-1000-8000-00805f9b34fb')
