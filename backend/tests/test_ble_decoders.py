"""Decoders convert verified raw bytes to display values WITHOUT discarding the
evidence. Every result keeps its raw hex so the UI can show what was actually
on the wire. Unknown values decode to None — never an exception, because a
firmware revision we have not seen must degrade, not crash."""

from app.five12_ble import decoders as d


def test_firmware_byte_order_is_reversed():
    """Toolbox displayed 1.0.7.2 while the wire carried 02 07 00 01. This
    reversal is the single easiest thing in the module to silently regress."""
    out = d.decode_firmware(bytes.fromhex('02070001'))
    assert out['decoded'] == '1.0.7.2'
    assert out['raw'] == '02070001'


def test_firmware_wrong_length_is_none():
    assert d.decode_firmware(b'\x02\x07')['decoded'] is None


def test_mode():
    assert d.decode_mode(b'\x00')['decoded'] == 'rx'
    assert d.decode_mode(b'\x01')['decoded'] == 'tx'
    assert d.decode_mode(b'\x7f')['decoded'] is None


def test_dmx_hold():
    assert d.decode_dmx_hold(b'\x00')['decoded'] is False
    assert d.decode_dmx_hold(b'\x01')['decoded'] is True
    assert d.decode_dmx_hold(b'\x09')['decoded'] is None


def test_output_power_keeps_three_separate_labels():
    """Raw enum, official module figure, and Toolbox's product label disagree.
    Keep all three rather than manufacturing a single false number."""
    out = d.decode_output_power(b'\x02')
    assert out['decoded'] == 'max'
    assert out['rawEnum'] == 2
    assert out['moduleFigure'] == '20 dBm / ~100 mW'
    assert out['toolboxLabel'] == '>100 mW'


def test_output_power_min():
    out = d.decode_output_power(b'\x05')
    assert out['decoded'] == 'min'
    assert out['toolboxLabel'] == '5 mW'


def test_output_power_rx_baseline_is_not_applicable_not_error():
    out = d.decode_output_power(b'\x80')
    assert out['decoded'] is None
    assert out['notApplicable'] is True


def test_tx_protocol():
    assert d.decode_tx_protocol(b'\x00')['decoded'] == 'crmx'
    assert d.decode_tx_protocol(b'\x01')['decoded'] == 'w-dmx-g3'
    assert d.decode_tx_protocol(b'\x03')['decoded'] == 'w-dmx-g4s'


def test_tx_protocol_rx_baseline_is_not_applicable():
    out = d.decode_tx_protocol(b'\xff')
    assert out['decoded'] is None
    assert out['notApplicable'] is True


def test_universe_color_rgb():
    out = d.decode_universe_color(bytes.fromhex('00FF00'))
    assert out['decoded'] == '#00FF00'
    assert out['rgb'] == [0, 255, 0]


def test_universe_color_wrong_length_is_none():
    assert d.decode_universe_color(b'\x00\xff')['decoded'] is None


def test_battery_percent():
    assert d.decode_battery(b'\x41')['decoded'] == 65


def test_battery_out_of_range_is_none():
    assert d.decode_battery(b'\xc8')['decoded'] is None    # 200%


def test_name_is_null_padded_utf8():
    raw = b'F12L - 1946' + b'\x00' * 5
    assert d.decode_name(raw)['decoded'] == 'F12L - 1946'


def test_name_invalid_utf8_is_none():
    assert d.decode_name(b'\xff\xfe\xfd')['decoded'] is None


def test_link_status_is_status_not_link_state():
    """LINK_ACTION reads 01 in RX and 03 in TX. These are baseline status
    values, NOT proof of receiver association. The decoder must not return
    anything resembling a linked boolean."""
    out = d.decode_link_status(b'\x01')
    assert out['raw'] == '01'
    assert 'linked' not in out


def test_all_decoders_tolerate_empty_bytes():
    for fn in (d.decode_name, d.decode_battery, d.decode_firmware, d.decode_mode,
               d.decode_dmx_hold, d.decode_output_power, d.decode_universe_color,
               d.decode_tx_protocol, d.decode_link_status):
        out = fn(b'')
        assert out['decoded'] is None, fn.__name__
