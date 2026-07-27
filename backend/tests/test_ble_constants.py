"""Guards the verified protocol contract. Every UUID here was confirmed by
GATT capture against a RatPac Cintenna on firmware 1.0.7.2 — see the KB
reference timotwo-ble-discovery-and-gatt.md. A typo in a UUID fails silently
at runtime (characteristic simply not found), so it is asserted literally."""

from app.five12_ble import constants as c


def test_config_service_uuids_exact():
    assert c.TIMOTWO_SERVICE_UUID == '33b5376d-0942-1f91-379b-ac5af36b9efa'
    assert c.CONFIG_SERVICE == '33b5376d-0942-1f91-379b-ac5af36b9efa'
    assert c.DEVICE_NAME == '33b5376e-0942-1f91-379b-ac5af36b9efa'
    assert c.MODE == '33b5376f-0942-1f91-379b-ac5af36b9efa'
    assert c.OUTPUT_POWER == '33b53770-0942-1f91-379b-ac5af36b9efa'
    assert c.UNIVERSE_COLOR == '33b53773-0942-1f91-379b-ac5af36b9efa'
    assert c.DMX_HOLD == '33b53774-0942-1f91-379b-ac5af36b9efa'
    assert c.TX_PROTOCOL == '33b53776-0942-1f91-379b-ac5af36b9efa'


def test_other_service_uuids_exact():
    assert c.FIRMWARE_VERSION == '10351004-3555-4907-0431-2b27430c2642'
    assert c.BATTERY_LEVEL == '00002a19-0000-1000-8000-00805f9b34fb'
    assert c.MODE_MIRROR == '45a41001-2ccd-80a5-b844-095c73b6c7e3'
    assert c.COLOR_MIRROR == '45a41002-2ccd-80a5-b844-095c73b6c7e3'
    assert c.LINK_ACTION == '45a41003-2ccd-80a5-b844-095c73b6c7e3'


def test_all_uuids_lowercase_and_well_formed():
    """bleak normalises to lowercase; a mixed-case constant silently fails
    string comparison against a discovered characteristic."""
    for name, value in vars(c).items():
        if name.isupper() and isinstance(value, str) and value.count('-') == 4:
            assert value == value.lower(), f'{name} must be lowercase'
            assert len(value) == 36, f'{name} is not a 36-char UUID'


def test_enums_match_captured_values():
    assert c.Mode.RX == 0x00
    assert c.Mode.TX == 0x01
    assert c.TxProtocol.CRMX == 0x00
    assert c.TxProtocol.W_DMX_G3 == 0x01
    assert c.TxProtocol.W_DMX_G4S == 0x03
    assert c.OutputPower.MAX == 0x02
    assert c.OutputPower.MIN == 0x05


def test_accepted_company_ids():
    """0x09E9 is LumenRadio's production key; 0xFFFF is the development key the
    official example app also accepts. Both are evidence of the radio platform,
    neither proves the enclosure model."""
    assert c.ACCEPTED_COMPANY_IDS == frozenset({0x09E9, 0xFFFF})


def test_readable_allowlist_contains_only_verified_uuids():
    verified = {
        c.DEVICE_NAME, c.MODE, c.OUTPUT_POWER, c.UNIVERSE_COLOR, c.DMX_HOLD,
        c.TX_PROTOCOL, c.FIRMWARE_VERSION, c.BATTERY_LEVEL, c.MODE_MIRROR,
        c.COLOR_MIRROR, c.LINK_ACTION,
    }
    assert c.READABLE_UUIDS == frozenset(verified)


def test_no_write_allowlist_exists_in_this_phase():
    """RELEASE GATE. The read-only phase must ship no write capability at all.
    If a later phase adds writes, it adds them deliberately and this test is
    updated in the same commit that introduces the command policy."""
    assert not hasattr(c, 'WRITE_ALLOWLIST')
    assert not hasattr(c, 'LINK_COMMAND')
    assert not hasattr(c, 'UNLINK_COMMAND')


def test_opaque_blob_is_not_readable():
    """10351003 is a large opaque blob that changes between connections. It is
    not an identifier, not a version, and must never be read or stored."""
    assert '10351003-3555-4907-0431-2b27430c2642' not in c.READABLE_UUIDS
