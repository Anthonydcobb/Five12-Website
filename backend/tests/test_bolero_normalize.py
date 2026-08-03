"""Bolero adapter — normalization of the REAL REST payloads.

[VERIFIED 2026-07-22, PARTLY CORRECTED 2026-07-30] Field mapping captured from
the live unit at 192.168.1.11 (HAR): /rest/nodeStatus carries antennas and, under
the DECT MASTER node's `bp[]`, every connected pack with its battery block. The
2026-07-22 reading of "the packs attached to that antenna" was wrong -- see the
antenna-attribution section at the foot of this file;
/rest/nodeConfig maps nodeId -> antenna name; /rest/bp maps DECT id -> crew
name. These fixtures are trimmed real responses.
"""

import pytest

from app.integrations.bolero import BoleroAdapter


# --- trimmed real payloads -------------------------------------------------

NODE_CONFIG = {'nodeConfig': [
    {'nodeId': 132651929, 'name': 'MBS LM 2', 'isLocal': True,
     'ip': {'ip': '192.168.1.11'}},
    {'nodeId': 163060633, 'name': 'MBS LM 1', 'isLocal': False,
     'ip': {'ip': '192.168.1.12'}},
]}

NODE_STATUS = {'nodeStatus': [
    {'nodeId': 132651929, 'ip': '192.168.1.11', 'temperature': 43,
     'ptpStatus': {'lockState': 2},
     'bp': [
        {'id': 34, 'battery': {'status': 82, 'currentCharge': 3857,
                               'usbPower': 0, 'batteryTemperature': 30,
                               'batteryHealth': 100, 'maxCharge': 4800},
         'signalLevel': 0},
        {'id': 2, 'battery': {'status': 96, 'currentCharge': 4420,
                              'usbPower': 1, 'batteryTemperature': 29,
                              'batteryHealth': 96, 'maxCharge': 4800},
         'signalLevel': 0},
     ]},
    {'nodeId': 163060633, 'ip': '192.168.1.12', 'temperature': 46,
     'ptpStatus': {'lockState': 2}, 'bp': []},
]}

NAME_MAP = {34: 'Anthony', 2: 'TSB'}


@pytest.fixture
def adapter():
    return BoleroAdapter(sim=False)


def _norm(adapter):
    return adapter._normalize(NODE_STATUS, NODE_CONFIG, NAME_MAP)


def test_antennas_named_from_node_config(adapter):
    names = {a['name'] for a in _norm(adapter)['antennas']}
    assert names == {'MBS LM 1', 'MBS LM 2'}


def test_no_per_antenna_pack_count_is_claimed(adapter):
    """Was `test_pack_count_per_antenna`, asserting 2 on MBS LM 2 and 0 on
    MBS LM 1. Those numbers were real, but they meant "packs the DECT master
    enumerates", not "packs on this antenna" -- and they rendered as the latter.
    Probed live 2026-07-30: MBS LM 1 asked about itself also reports zero while
    the Bolero GUI showed five packs on it."""
    by_name = {a['name']: a for a in _norm(adapter)['antennas']}
    assert by_name['MBS LM 2']['packCount'] is None
    assert by_name['MBS LM 1']['packCount'] is None


def test_ptp_synced_from_lockstate(adapter):
    assert all(a['ptpSynced'] for a in _norm(adapter)['antennas'])


def test_beltpack_battery_fields_mapped(adapter):
    packs = {p['name']: p for p in _norm(adapter)['beltpacks']}
    a = packs['Anthony']
    assert a['batteryPct'] == 82
    assert a['mAh'] == 3857
    assert a['healthPct'] == 100
    assert a['tempC'] == 30
    assert a['charging'] is False          # usbPower 0
    # Not 'MBS LM 2'. That was the DECT master's name leaking in as if it
    # were this pack's antenna; the API does not carry attribution.
    assert a['antenna'] is None
    assert a['online'] is True             # present in a node's bp[]


def test_signal_quality_mapped_from_level(adapter):
    """Both real fixtures report signalLevel 0 -> EXCELLENT -> 4 bars, matching
    the Bolero GUI's getSignalIconClass/getSignalTooltip."""
    packs = {p['name']: p for p in _norm(adapter)['beltpacks']}
    assert packs['Anthony']['signalQuality'] == 4
    assert packs['Anthony']['signalLabel'] == 'Excellent'
    assert packs['TSB']['signalQuality'] == 4
    assert packs['TSB']['signalLabel'] == 'Excellent'


@pytest.mark.parametrize('level,bars,label', [
    (0, 4, 'Excellent'),        # BP_SIGNAL_LEVELS.EXCELLENT
    (1, 3, 'Good'),             # GOOD
    (2, 2, 'Medium'),           # MEDIUM
    (3, 1, 'Bad'),              # BAD
    (0xFF, 0, 'Not Connected'), # INVALID (255)
    (None, 0, 'Not Connected'), # field absent -> INVALID
    (7, 0, 'Not Connected'),    # any unknown level -> INVALID
])
def test_signal_level_enum_matches_riedel(adapter, level, bars, label):
    """The full signalLevel enum maps exactly as Riedel's app bundle does."""
    ns = {'nodeStatus': [
        {'nodeId': 132651929, 'ptpStatus': {'lockState': 2},
         'bp': [{'id': 34, 'battery': {'status': 50}, 'signalLevel': level}]},
    ]}
    p = adapter._normalize(ns, NODE_CONFIG, {34: 'X'})['beltpacks'][0]
    assert p['signalQuality'] == bars
    assert p['signalLabel'] == label


def test_charging_flag_from_usb_power(adapter):
    tsb = next(p for p in _norm(adapter)['beltpacks'] if p['name'] == 'TSB')
    assert tsb['charging'] is True         # usbPower 1


def test_pack_name_falls_back_when_unmapped(adapter):
    status = adapter._normalize(NODE_STATUS, NODE_CONFIG, {})  # empty name map
    names = {p['name'] for p in status['beltpacks']}
    assert 'Pack 34' in names and 'Pack 2' in names


def test_beltpacks_sorted_lowest_battery_first(adapter):
    packs = _norm(adapter)['beltpacks']
    assert packs[0]['name'] == 'Anthony'   # 82 < 96
    assert [p['batteryPct'] for p in packs] == sorted(p['batteryPct'] for p in packs)


def test_summary_fields(adapter):
    s = _norm(adapter)
    assert s['available'] is True
    assert s['source'] == 'rest'
    assert s['packsOnline'] == 2
    assert s['lowestBatteryPct'] == 82
    assert s['ptpSynced'] is True


def test_low_battery_alert_fires():
    """A pack under 20% must raise the crit alert via the shared rules."""
    ns = {'nodeStatus': [
        {'nodeId': 132651929, 'ptpStatus': {'lockState': 2},
         'bp': [{'id': 34, 'battery': {'status': 12, 'currentCharge': 500,
                                       'usbPower': 0, 'batteryTemperature': 30,
                                       'batteryHealth': 90, 'maxCharge': 4800}}]},
    ]}
    a = BoleroAdapter(sim=False)
    a.host = '192.168.1.11'   # _fetch_json is stubbed; host just has to be set
    a._fetch_json = lambda path: {'nodeConfig': [{'nodeId': 132651929, 'name': 'MBS LM 2'}]} if path.endswith('nodeConfig') else ns  # noqa: E501
    a._name_map = lambda: {34: 'Anthony'}
    status = a.get_status()
    assert any(al['level'] == 'crit' and '12' in al['message'] for al in status['alerts'])


def test_sim_still_produces_the_contract():
    """?sim=1 must expose the same new fields so the panel renders identically."""
    s = BoleroAdapter(sim=True).get_status()
    assert s['available'] and s['source'] == 'sim'
    for p in s['beltpacks']:
        assert 'healthPct' in p and 'charging' in p and 'batteryPct' in p
        assert 'signalQuality' in p and 'signalLabel' in p
        assert 0 <= p['signalQuality'] <= 4


# ── Antenna attribution is not in this API (2026-07-30) ──────────────────────
#
# Anthony saw all eight packs on MBS LM 2 while the Bolero GUI showed 5 on LM 1
# and 3 on LM 2. Probed live, read-only: /rest/nodeStatus hangs every connected
# pack off the node with isDectMaster=True, and MBS LM 1 asked about ITSELF
# reports bp: []. Nothing in a bp[] entry names a node. So the antenna a pack is
# radio-linked to is simply not in this payload, and the old code derived it
# from the containing node -- which is always the master.
#
# A confidently wrong antenna on a panel read under show pressure is worse than
# a blank one.

MASTER_NODE_CONFIG = {'nodeConfig': [
    {'nodeId': 132651929, 'name': 'MBS LM 2', 'isLocal': True,
     'ip': {'ip': '192.168.1.11'}},
    {'nodeId': 163060633, 'name': 'MBS LM 1', 'isLocal': False,
     'ip': {'ip': '192.168.1.12'}},
]}

MASTER_NODE_STATUS = {'nodeStatus': [
    # the DECT master carries every pack, whichever antenna they are really on
    {'nodeId': 132651929, 'ip': '192.168.1.11', 'isDectMaster': True,
     'ptpStatus': {'lockState': 2},
     'bp': [
        {'id': 34, 'battery': {'status': 82, 'currentCharge': 3857, 'usbPower': 0,
                               'batteryTemperature': 30, 'batteryHealth': 100},
         'signalLevel': 0},
        {'id': 2, 'battery': {'status': 96, 'currentCharge': 4420, 'usbPower': 1,
                              'batteryTemperature': 29, 'batteryHealth': 96},
         'signalLevel': 0},
     ]},
    {'nodeId': 163060633, 'ip': '192.168.1.12', 'isDectMaster': False,
     'ptpStatus': {'lockState': 2}, 'bp': []},
]}


def test_no_pack_claims_an_antenna(adapter):
    out = adapter._normalize(MASTER_NODE_STATUS, MASTER_NODE_CONFIG, NAME_MAP)
    assert [p['antenna'] for p in out['beltpacks']] == [None, None]


def test_no_antenna_claims_a_pack_count(adapter):
    out = adapter._normalize(MASTER_NODE_STATUS, MASTER_NODE_CONFIG, NAME_MAP)
    assert [a['packCount'] for a in out['antennas']] == [None, None]


def test_the_dect_master_is_identified(adapter):
    out = adapter._normalize(MASTER_NODE_STATUS, MASTER_NODE_CONFIG, NAME_MAP)
    by_name = {a['name']: a for a in out['antennas']}
    assert by_name['MBS LM 2']['isDectMaster'] is True
    assert by_name['MBS LM 1']['isDectMaster'] is False


def test_the_system_wide_total_is_still_reported(adapter):
    """packsOnline IS knowable -- the master lists them all."""
    out = adapter._normalize(MASTER_NODE_STATUS, MASTER_NODE_CONFIG, NAME_MAP)
    assert out['packsOnline'] == 2


# ── Antenna attribution, from /rest/audioPorts (2026-07-30, second pass) ─────
#
# The earlier conclusion that this API carries no attribution was WRONG. It
# does: GET /rest/audioPorts returns a complete snapshot mapping each beltpack
# to the node it is on. It was missed because the endpoint was inferred from a
# grep of the minified GUI bundle for quoted '/rest/...' strings -- a search that
# also failed to find the websocket URL, which was known to exist. The REST
# paths mirror the websocket message kinds; audioPorts is one of them.
#
# Real payload from the rig: 13 ports, id.type 1 = beltpack.

AUDIO_PORTS = {'audioPorts': [
    {'registered': True, 'id': {'type': 1, 'id': 34}, 'nodeId': 163060633},
    {'registered': True, 'id': {'type': 1, 'id': 2}, 'nodeId': 132651929},
    {'registered': True, 'id': {'type': 7, 'id': 99}, 'nodeId': 132651929},
    {'registered': False, 'id': {'type': 1, 'id': 55}, 'nodeId': 163060633},
]}


def _norm_with_ports(adapter, ports=None):
    return adapter._normalize(NODE_STATUS, NODE_CONFIG, NAME_MAP,
                              ports if ports is not None else AUDIO_PORTS)


def test_each_pack_reports_the_antenna_it_is_actually_on(adapter):
    packs = {p['name']: p for p in _norm_with_ports(adapter)['beltpacks']}
    assert packs['Anthony']['antenna'] == 'MBS LM 1'    # bp 34
    assert packs['TSB']['antenna'] == 'MBS LM 2'        # bp 2


def test_per_antenna_counts_come_from_the_attribution(adapter):
    by_name = {a['name']: a for a in _norm_with_ports(adapter)['antennas']}
    assert by_name['MBS LM 1']['packCount'] == 1
    assert by_name['MBS LM 2']['packCount'] == 1


def test_counts_sum_to_packs_online(adapter):
    out = _norm_with_ports(adapter)
    assert sum(a['packCount'] for a in out['antennas']) == out['packsOnline']


def test_non_beltpack_ports_do_not_inflate_a_count(adapter):
    """id.type 7 is some other port kind and must not be counted as a pack."""
    out = _norm_with_ports(adapter)
    assert sum(a['packCount'] for a in out['antennas']) == 2


def test_an_unregistered_port_is_not_attributed(adapter):
    packs = {p['id']: p for p in _norm_with_ports(adapter)['beltpacks']}
    assert 55 not in packs


def test_without_the_endpoint_it_still_refuses_to_guess(adapter):
    """If audioPorts is unavailable the old wrong answer must not come back."""
    out = adapter._normalize(NODE_STATUS, NODE_CONFIG, NAME_MAP, None)
    assert [p['antenna'] for p in out['beltpacks']] == [None, None]
    assert [a['packCount'] for a in out['antennas']] == [None, None]


def test_a_pack_absent_from_audio_ports_reports_no_antenna(adapter):
    """Better a blank than the DECT master's name, which is the bug that
    started all of this."""
    out = adapter._normalize(NODE_STATUS, NODE_CONFIG, NAME_MAP,
                             {'audioPorts': [
                                 {'registered': True, 'id': {'type': 1, 'id': 34},
                                  'nodeId': 163060633}]})
    packs = {p['name']: p for p in out['beltpacks']}
    assert packs['Anthony']['antenna'] == 'MBS LM 1'
    assert packs['TSB']['antenna'] is None
