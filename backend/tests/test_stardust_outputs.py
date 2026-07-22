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


import socket as _socket

from app.integrations.stardust import StardustAdapter


class _FakeSock:
    """Stand-in for the Art-Net TOD UDP socket: no real network, no fixtures."""
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def sendto(self, *args):
        pass

    def recvfrom(self, *args):
        raise _socket.timeout()

    def close(self):
        pass


def test_real_status_attaches_outputs_from_ws():
    a = StardustAdapter(sim=False)
    node = {'ip': '10.0.1.3', 'mac': 'AA:BB:CC:DD:EE:FF', 'shortName': 'Stardust',
            'longName': 'Stardust DTx8', 'firmware': '1.0', 'via': '', 'ports': []}
    a._discover_nodes = lambda: [node]
    a._open_socket = lambda *args, **kwargs: _FakeSock()
    a._ws_fetch_settings = lambda ip: (
        {'universe_nrs': [1], 'output_names': ['X'], 'output_powers_mw': [100],
         'rf_protocols': ['CRMX'], 'enabled_universe_nrs': [1]},
        {'universe_map': {'5': [1]}},
        {'universe_map': {}},
    )
    status = a._real_status()
    assert status['available'] is True
    assert status['outputs'][0]['output'] == 'A'
    assert status['outputs'][0]['source'] == 'sACN'
    assert status['outputs'][0]['universe'] == '5'
    assert status['outputs'][0]['crmxType'] == 'CRMX Classic'


def test_real_status_outputs_none_when_ws_fails():
    a = StardustAdapter(sim=False)
    node = {'ip': '10.0.1.3', 'mac': 'AA:BB:CC:DD:EE:FF', 'shortName': 'Stardust',
            'longName': 'Stardust DTx8', 'firmware': '1.0', 'via': '', 'ports': []}
    a._discover_nodes = lambda: [node]
    a._open_socket = lambda *args, **kwargs: _FakeSock()

    def _boom(ip):
        raise OSError('ws refused')

    a._ws_fetch_settings = _boom
    status = a._real_status()
    assert status['available'] is True   # Art-Net path unaffected
    assert status['outputs'] is None


def test_ws_fetch_throttled_by_ttl():
    """The slow /ws fetch must not run on every poll: within OUTPUTS_TTL the
    cached outputs are reused, and a later failed refetch keeps the last good
    list rather than blanking it."""
    a = StardustAdapter(sim=False)
    node = {'ip': '10.0.1.3', 'mac': 'AA:BB:CC:DD:EE:FF', 'shortName': 'Stardust',
            'longName': 'Stardust DTx8', 'firmware': '1.0', 'via': '', 'ports': []}
    a._discover_nodes = lambda: [node]
    a._open_socket = lambda *args, **kwargs: _FakeSock()

    calls = {'n': 0}

    def _fetch(ip):
        calls['n'] += 1
        return (
            {'universe_nrs': [1], 'output_names': ['X'], 'output_powers_mw': [100],
             'rf_protocols': ['CRMX'], 'enabled_universe_nrs': [1]},
            {'universe_map': {'5': [1]}}, {'universe_map': {}},
        )

    a._ws_fetch_settings = _fetch
    first = a._real_status()
    second = a._real_status()          # within TTL → served from cache
    assert calls['n'] == 1
    assert second['outputs'] == first['outputs']

    # Force staleness, then a failing refetch must keep the cached outputs.
    a._outputs_cache_at = 0.0
    a._ws_fetch_settings = lambda ip: (_ for _ in ()).throw(OSError('down'))
    third = a._real_status()
    assert third['outputs'] == first['outputs']


def test_sim_exposes_outputs():
    s = StardustAdapter(sim=True).get_status()
    assert s['available'] and s['source'] == 'sim'
    assert len(s['outputs']) == 8
    for o in s['outputs']:
        assert set(o) >= {'output', 'name', 'source', 'universe',
                          'crmxType', 'powerMw', 'enabled'}
    by_output = {o['output']: o for o in s['outputs']}
    assert by_output['C']['crmxType'] == '1/4 CRMX²'   # CRMX2_1_4 at N=8
    assert by_output['H']['enabled'] is False
