"""Stardust /ws outputs mapping — pure helpers and the settings join.

[VERIFIED 2026-07-22] Field names and the CRMX label table were mapped from the
LumenRadio GUI bundle main.7bc0d075.chunk.js in a captured HAR. The device
drives its whole UI over ws://<ip>/ws with JSON _type_ frames.
"""

from app.integrations.stardust import _output_letter, _artnet_addr, _crmx_label


def test_output_letter_maps_1_to_8():
    assert [_output_letter(n) for n in range(1, 9)] == list('ABCDEFGH')


def test_output_letter_out_of_range_is_blank():
    assert _output_letter(0) == ' '
    assert _output_letter(9) == ' '


def test_artnet_addr_decodes_net_sub_uni():
    # net=1, sub=2, uni=3 -> (1<<8)|(2<<4)|3
    assert _artnet_addr((1 << 8) | (2 << 4) | 3) == '1/2/3'
    assert _artnet_addr(0) == '0/0/0'


def test_crmx_label_full_enum_n8():
    expected = {
        'CRMX': 'CRMX Classic', 'CRMX2_1_4': '1/4 CRMX²',
        'CRMX2_2_4': '2/4 CRMX²', 'CRMX2_3_4': '3/4 CRMX²',
        'CRMX2': 'CRMX²', 'WDMX_G3': 'W-DMX G3', 'WDMX_G4S': 'W-DMX G4S',
    }
    for raw, label in expected.items():
        assert _crmx_label(raw, 8) == label


def test_crmx_label_split_varies_by_output_count():
    assert _crmx_label('CRMX2_1_4', 2) == 'CRMX²'
    assert _crmx_label('CRMX2_1_4', 4) == '1/2 CRMX²'
    assert _crmx_label('CRMX2_1_4', 6) == '1/3 CRMX²'


def test_crmx_label_unknown_falls_back():
    assert _crmx_label('CRMX', 7) == 'CRMX Classic'   # unknown N -> N=8 table
    assert _crmx_label('MYSTERY', 8) == 'MYSTERY'      # unknown raw -> verbatim
