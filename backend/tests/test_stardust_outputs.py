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


from app.integrations.stardust import _merge_outputs

TIMO = {
    'universe_nrs': [1, 2, 3, 4],
    'output_names': ['Front', 'Back', 'Spot', ''],
    'output_powers_mw': [100, 100, 30, 100],
    'rf_protocols': ['CRMX', 'CRMX', 'CRMX2_1_4', 'CRMX'],
    'enabled_universe_nrs': [1, 2, 3],
    'disabled_universe_nrs': [4],
}
# sACN map is {universe: [outputNrs]}; ArtNet map is {outputNr: addrInt}.
# JSON object keys arrive as strings; output C (3) is fed by ArtNet 0/1/5,
# output D (4) is present in the ArtNet map but null (i.e. not ArtNet).
SACN = {'universe_map': {'10': [1], '11': [2]}}
ARTNET = {'universe_map': {'3': (0 << 8) | (1 << 4) | 5, '4': None}}


def _by_output(*args):
    return {o['output']: o for o in _merge_outputs(*args)}


def test_merge_sacn_output():
    a = _by_output(TIMO, SACN, ARTNET)['A']
    assert a['source'] == 'sACN'
    assert a['universe'] == '10'
    assert a['name'] == 'Front'
    assert a['crmxType'] == 'CRMX Classic'
    assert a['powerMw'] == 100
    assert a['enabled'] is True


def test_merge_artnet_output_decodes_address():
    c = _by_output(TIMO, SACN, ARTNET)['C']
    assert c['source'] == 'ArtNet'
    assert c['universe'] == '0/1/5'
    # N = len(universe_nrs) = 4, so CRMX2_1_4 -> '1/2 CRMX²'
    assert c['crmxType'] == '1/2 CRMX²'


def test_merge_output_with_no_source_and_disabled():
    d = _by_output(TIMO, SACN, ARTNET)['D']
    assert d['source'] == 'None'
    assert d['universe'] is None
    assert d['enabled'] is False
    assert d['name'] == ''


def test_merge_sorted_by_output_letter():
    outs = _merge_outputs(TIMO, SACN, ARTNET)
    assert [o['output'] for o in outs] == ['A', 'B', 'C', 'D']
