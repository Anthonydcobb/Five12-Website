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


import json
import socket as _socket

import pytest

from app.integrations import stardust
from app.integrations.stardust import StardustAdapter

_STARDUST_NODE = {
    'ip': '10.0.1.3', 'mac': 'AA:BB:CC:DD:EE:FF', 'shortName': 'Stardust',
    'longName': 'Stardust DTx8', 'firmware': '1.0', 'via': '', 'ports': [],
}
_STARDUST_NODE_B = {
    'ip': '10.0.1.4', 'mac': '11:22:33:44:55:66', 'shortName': 'Stardust',
    'longName': 'Stardust DTx8 B', 'firmware': '1.0', 'via': '', 'ports': [],
}


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


# ── the empty grid must always say WHY ──────────────────────────────────────
# These exist because a blanket `except Exception` once made a missing Python
# package and an unreachable fixture produce identical, invisible results: an
# empty grid with no error anywhere. Diagnosing that took far longer than it
# should have. Each failure class now has to name itself.

def _adapter_with_node():
    a = StardustAdapter(sim=False)
    node = {'ip': '10.0.1.3', 'mac': 'AA:BB:CC:DD:EE:FF', 'shortName': 'Stardust',
            'longName': 'Stardust DTx8', 'firmware': '1.0', 'via': '', 'ports': []}
    a._discover_nodes = lambda: [node]
    a._open_socket = lambda *args, **kwargs: _FakeSock()
    return a


def test_missing_dependency_names_the_package_not_the_device():
    """A broken server install must not read as a flaky fixture. It will never
    fix itself by retrying, and the operator can act on it only if told."""
    a = _adapter_with_node()

    def _no_lib(ip):
        raise ImportError("No module named 'websocket'")

    a._ws_fetch_settings = _no_lib
    status = a._real_status()
    assert status['outputs'] is None
    err = status['outputsError']
    assert 'websocket-client' in err
    assert 'requirements.txt' in err
    # Must NOT blame the radio — that is the wrong thing to go and check.
    assert '10.0.1.3' not in err


def test_unreachable_unit_names_the_unit():
    a = _adapter_with_node()

    def _boom(ip):
        raise OSError('ws refused')

    a._ws_fetch_settings = _boom
    status = a._real_status()
    assert status['outputs'] is None
    err = status['outputsError']
    assert '10.0.1.3' in err
    assert 'websocket-client' not in err   # not a dependency problem


def test_unit_answering_with_nothing_is_distinct_from_not_answering():
    a = _adapter_with_node()
    a._ws_fetch_settings = lambda ip: ({}, {}, {})
    status = a._real_status()
    assert status['outputs'] is None
    assert 'responded' in status['outputsError']


def test_success_clears_a_previous_error():
    """A recovered unit must not keep showing yesterday's failure."""
    a = _adapter_with_node()

    def _boom(ip):
        raise OSError('ws refused')

    a._ws_fetch_settings = _boom
    assert a._real_status()['outputsError'] is not None

    a._outputs_cache_at = 0.0     # force a refetch past the TTL
    a._ws_fetch_settings = lambda ip: (
        {'universe_nrs': [1], 'output_names': ['X'], 'output_powers_mw': [100],
         'rf_protocols': ['CRMX'], 'enabled_universe_nrs': [1]},
        {'universe_map': {'5': [1]}},
        {'universe_map': {}},
    )
    status = a._real_status()
    assert status['outputs'][0]['output'] == 'A'
    assert status['outputsError'] is None


def test_sim_status_carries_the_key_too():
    """Shape parity: the panel reads status.outputsError unconditionally."""
    assert 'outputsError' in StardustAdapter(sim=True)._sim_status()


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


def test_discovery_shared_across_callers_within_ttl():
    """Overlapping status/units/detect polls must share one serialized
    discovery (not compete for the single ArtPollReply); a poll this fresh is
    reused, and forcing staleness triggers exactly one more real poll."""
    a = StardustAdapter(sim=False)
    node = {'ip': '10.0.1.3', 'mac': 'AA:BB:CC:DD:EE:FF', 'shortName': 'Stardust',
            'longName': 'Stardust DTx8', 'firmware': '1.0', 'via': '', 'ports': []}
    calls = {'n': 0}

    def _poll():
        calls['n'] += 1
        return [node]

    a._discover_nodes = _poll
    first = a._discover_nodes_cached()
    a._discover_nodes_cached()
    a._discover_nodes_cached()
    assert calls['n'] == 1          # three callers, one real poll
    assert first == [node]

    a._nodes_cache_at = 0.0         # force staleness
    a._discover_nodes_cached()
    assert calls['n'] == 2


def test_status_sticky_holds_available_through_a_brief_miss():
    """A single poll that fails to hear the Stardust must not flip the panel to
    'unavailable': if the unit was seen moments ago, hold it available (flagged
    stale) so the UI stops flapping RECONNECTING on every dropped ArtPollReply."""
    a = StardustAdapter(sim=False)
    a._open_socket = lambda *args, **kwargs: _FakeSock()
    a._ws_fetch_settings = lambda ip: ({}, {}, {})
    seq = [[_STARDUST_NODE], []]          # poll 1 sees it; poll 2 misses it
    a._discover_nodes_cached = lambda: seq.pop(0)

    first = a._real_status()
    assert first['available'] is True
    assert not first.get('stale')

    second = a._real_status()             # missed this poll, but just seen
    assert second['available'] is True    # sticky: no flap to unavailable
    assert second['stale'] is True
    assert second['node'] == 'Stardust DTx8'


def test_status_goes_unavailable_after_sticky_window_expires():
    """Stickiness is a brief bridge, not a permanent lie: once the last sighting
    ages past the window, a missing unit is reported unavailable as before."""
    a = StardustAdapter(sim=False)
    a._open_socket = lambda *args, **kwargs: _FakeSock()
    a._ws_fetch_settings = lambda ip: ({}, {}, {})
    a._discover_nodes_cached = lambda: [_STARDUST_NODE]
    a._real_status()                      # seeds the last-seen sighting

    a._last_seen.clear()                  # pretend the sighting has aged out
    a._discover_nodes_cached = lambda: []  # unit now truly gone
    status = a._real_status()
    assert status['available'] is False
    assert 'none LumenRadio' in status['reason']


def test_discover_resends_artpoll_within_the_window(monkeypatch):
    """A dropped ArtPoll must not doom the whole poll: the broadcast is repeated
    within POLL_TIMEOUT so a lost datagram has more chances to reach the unit."""
    a = StardustAdapter(sim=False)
    sends = {'n': 0}

    class _SilentUDP:
        def sendto(self, *args):
            sends['n'] += 1

        def recvfrom(self, *args):
            raise _socket.timeout()

        def close(self):
            pass

    monkeypatch.setattr(stardust, '_local_ipv4s', lambda: [''])
    monkeypatch.setattr(a, '_open_socket', lambda *args, **kwargs: _SilentUDP())
    monkeypatch.setattr(stardust.select, 'select', lambda r, w, x, t: ([], [], []))
    monkeypatch.setattr(stardust, 'POLL_TIMEOUT', 0.25)
    monkeypatch.setattr(stardust, 'POLL_RESEND_SEC', 0.1)

    nodes = a._discover_nodes()
    assert nodes == []
    assert sends['n'] >= 2                 # resent, not a single fire-and-forget


def test_merge_outputs_includes_output_number():
    """Each output carries its 1-based output number so the UI can address it —
    the LinkCommand is keyed by that number (output E == 5)."""
    by = _by_output(TIMO, SACN, ARTNET)
    assert by['A']['outputNr'] == 1
    assert by['C']['outputNr'] == 3


class _FakeWS:
    """Records what was sent and replays canned frames on recv()."""
    def __init__(self, replies=()):
        self.sent = []
        self._replies = list(replies)

    def send(self, s):
        self.sent.append(s)

    def recv(self):
        import websocket
        if self._replies:
            return self._replies.pop(0)
        raise websocket.WebSocketTimeoutException()

    def close(self):
        pass


def test_status_filters_by_mac():
    """With two Stardusts on the wire, a status poll pinned to a MAC returns that
    unit — not just whichever was discovered first."""
    a = StardustAdapter(sim=False)
    a._open_socket = lambda *args, **kwargs: _FakeSock()
    a._ws_fetch_settings = lambda ip: ({}, {}, {})
    a._discover_nodes_cached = lambda: [_STARDUST_NODE, _STARDUST_NODE_B]

    status = a._real_status(mac='11:22:33:44:55:66')
    assert status['available'] is True
    assert status['mac'] == '11:22:33:44:55:66'
    assert status['node'] == 'Stardust DTx8 B'


def test_status_unknown_mac_is_unavailable():
    a = StardustAdapter(sim=False)
    a._open_socket = lambda *args, **kwargs: _FakeSock()
    a._ws_fetch_settings = lambda ip: ({}, {}, {})
    a._discover_nodes_cached = lambda: [_STARDUST_NODE]

    status = a._real_status(mac='99:99:99:99:99:99')
    assert status['available'] is False
    assert '99:99:99:99:99:99' in status['reason']


def test_link_output_targets_unit_by_mac():
    """Linking must reach the SELECTED unit's IP, not hits[0]."""
    a = StardustAdapter(sim=False)
    a._discover_nodes_cached = lambda: [_STARDUST_NODE, _STARDUST_NODE_B]
    captured = {}

    def _open(ip):
        captured['ip'] = ip
        return _FakeWS(['{"universe_nrs":[2],"_type_":"dmx_sink.timo_sink.LinkingStarted"}'])

    a._ws_open = _open
    result = a.link_output(2, mac='11:22:33:44:55:66')
    assert result['ok'] is True
    assert captured['ip'] == '10.0.1.4'   # unit B, not the first-discovered unit


def test_link_output_sends_link_command_and_confirms():
    a = StardustAdapter(sim=False)
    a._stardust_ip = lambda mac=None: '10.0.1.3'
    fake = _FakeWS(['{"universe_nrs":[5],"_type_":"dmx_sink.timo_sink.LinkingStarted"}'])
    a._ws_open = lambda ip: fake

    result = a.link_output(5)

    assert result['ok'] is True
    assert result['outputNr'] == 5
    assert result['output'] == 'E'
    assert json.loads(fake.sent[0]) == {
        'universe_nrs': [5], '_type_': 'dmx_sink.timo_sink.LinkCommand'}


def test_link_output_rejects_out_of_range():
    a = StardustAdapter(sim=False)
    for bad in (0, 9, -1):
        with pytest.raises(ValueError):
            a.link_output(bad)


def test_link_output_sim_is_a_noop_success():
    a = StardustAdapter(sim=True)
    touched = {'ws': False}
    a._ws_open = lambda ip: touched.__setitem__('ws', True)

    result = a.link_output(3)

    assert result['ok'] is True and result.get('sim') is True
    assert touched['ws'] is False   # sim never contacts hardware


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
