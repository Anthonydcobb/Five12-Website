from pathlib import Path

import pytest

from app.vendors.netgear_snapshot import parse_snapshot

FIXTURE = Path(__file__).parent / 'fixtures' / 'netgear_m4250_overview.html'


@pytest.fixture(scope='module')
def snapshot():
    return parse_snapshot(FIXTURE.read_text(encoding='utf-8'))


def test_identity_fields(snapshot):
    assert snapshot['serial'] == '70VG5C57A01E0'
    assert snapshot['baseMac'] == '28:94:01:84:3C:DE'
    assert snapshot['model'] == 'M4250-10G2F-PoE+'
    assert snapshot['systemName'] == 'FMB Switch 73'


def test_version_fields(snapshot):
    assert snapshot['firmware'] == '13.0.5.26'
    assert snapshot['bootVersion'] == '1.0.0.11'
    assert snapshot['avUiVersion'] == '2.2.15.16'


def test_network_and_health_fields(snapshot):
    assert snapshot['managementIp'] == '172.16.3.73'
    assert snapshot['uptime'] == '0 days, 11 hrs, 58 mins, 10 secs'
    assert snapshot['stpMode'] == 'Neutral mode(32768): 32768'
    assert snapshot['fanMode'] == 'Quiet'
    assert snapshot['tempC'] == 32
    assert snapshot['maxTempC'] == 53
    assert snapshot['cpuPercent'] == 39.06
    assert snapshot['memoryPercent'] == 33.43


def test_absent_field_is_absent_not_blank():
    """A page missing an element yields no key at all, never an empty string."""
    html = '<div id="device_serial">ABC123</div><div id="device_mac">AA:BB:CC:DD:EE:FF</div>'
    parsed = parse_snapshot(html)
    assert parsed['serial'] == 'ABC123'
    assert 'firmware' not in parsed
    assert 'tempC' not in parsed


def test_non_netgear_page_yields_no_identity():
    parsed = parse_snapshot('<html><body><h1>Some other device</h1></body></html>')
    assert 'serial' not in parsed
    assert 'baseMac' not in parsed


# --- Task 3: profiles -------------------------------------------------------

def test_profiles_all_rows_parsed(snapshot):
    """Five profiles, not one. Guards the duplicate-id trap: every row carries
    id="profile_name", so an id lookup would return only 'Default'."""
    names = [p['name'] for p in snapshot['profiles']]
    assert names == ['Default', 'FixtureNet', 'Comms', 'VidNet', 'HogNet']


def test_profile_fields(snapshot):
    by_name = {p['name']: p for p in snapshot['profiles']}

    assert by_name['FixtureNet']['template'] == 'Lighting'
    assert by_name['FixtureNet']['vlan'] == 300
    assert by_name['FixtureNet']['portCount'] == 8
    assert by_name['FixtureNet']['color'] == '#00ff00'

    assert by_name['Comms']['template'] == 'Audio AES67'
    assert by_name['Comms']['vlan'] == 400
    assert by_name['VidNet']['template'] == 'BirdDog AV Network'
    assert by_name['VidNet']['vlan'] == 500
    assert by_name['HogNet']['template'] == 'Data'
    assert by_name['HogNet']['vlan'] == 600
    assert by_name['HogNet']['color'] == '#ffa600'

    assert by_name['Default']['vlan'] == 1
    assert by_name['Default']['ip'] == '172.16.3.73'


def test_profiles_absent_when_table_missing():
    parsed = parse_snapshot('<div id="device_serial">X</div>')
    assert parsed.get('profiles', []) == []


# --- Task 4: port strip -----------------------------------------------------

def test_all_twelve_ports_in_order(snapshot):
    ports = snapshot['netgearPorts']
    assert [p['port'] for p in ports] == list(range(1, 13))
    assert snapshot['portCount'] == 12


def test_port_media_copper_and_fiber(snapshot):
    by_num = {p['port']: p for p in snapshot['netgearPorts']}
    assert by_num[1]['media'] == 'copper'
    assert by_num[11]['media'] == 'fiber'
    assert by_num[12]['media'] == 'fiber'


def test_port_link_state(snapshot):
    by_num = {p['port']: p for p in snapshot['netgearPorts']}
    assert by_num[1]['linkUp'] is True     # lan-disabled lan-connected
    assert by_num[4]['linkUp'] is True     # lan-connected
    assert by_num[3]['linkUp'] is False
    assert by_num[8]['linkUp'] is False
    assert snapshot['activePorts'] == 3


def test_powered_port_counts_as_up(snapshot):
    """Port 5 carries `lan-connected-powered`, not `lan-connected`.

    An exact class-list membership test for 'lan-connected' reports this port
    DOWN. It is up at 100T Full and delivering 6W to a Raspberry Pi, so
    reporting it down would send an operator to a rack to fix a working port.
    """
    by_num = {p['port']: p for p in snapshot['netgearPorts']}
    assert by_num[5]['linkUp'] is True
    assert by_num[5]['poe'] is True


def test_port_poe_and_trunk_badges(snapshot):
    by_num = {p['port']: p for p in snapshot['netgearPorts']}
    assert by_num[3]['poe'] is True
    assert by_num[9]['poe'] is False
    assert by_num[1]['trunk'] == 'auto'
    assert by_num[2]['trunk'] == 'manual'
    assert by_num[10]['trunk'] == 'manual'
    assert by_num[4]['trunk'] is None


def test_port_colour_matches_profile_swatch(snapshot):
    by_num = {p['port']: p for p in snapshot['netgearPorts']}
    assert by_num[3]['color'] == '#ffa600'   # HogNet
    assert by_num[8]['color'] == '#00fff7'   # Comms
    assert by_num[4]['color'] == '#00ff00'   # FixtureNet


def test_ports_absent_when_strip_missing():
    parsed = parse_snapshot('<div id="device_serial">X</div>')
    assert parsed.get('netgearPorts', []) == []


# --- Task 5: popover merge behind a count guard -----------------------------

def test_popover_alignment_holds(snapshot):
    """Cross-checks popover-sourced VLAN against each port's own colour, which
    is read structurally. If ordering ever drifts these disagree."""
    by_num = {p['port']: p for p in snapshot['netgearPorts']}
    assert snapshot['netgearPortHostsAvailable'] is True

    assert by_num[3]['profile'] == 'HogNet'
    assert by_num[3]['vlans'] == [600]
    assert by_num[8]['profile'] == 'Comms'
    assert by_num[8]['vlans'] == [400]
    assert by_num[4]['profile'] == 'FixtureNet'
    assert by_num[4]['template'] == 'Lighting'
    assert by_num[1]['vlans'] == [1, 300, 400, 500, 600]
    assert by_num[2]['vlans'] == [300, 400, 500, 600, 1]


def test_popover_connected_host_details(snapshot):
    by_num = {p['port']: p for p in snapshot['netgearPorts']}
    assert by_num[1]['host'] == 'FMB Switch 52'
    assert by_num[1]['mac'] == '28:94:01:84:47:02'
    assert by_num[1]['ip'] == '172.16.3.52'
    assert by_num[1]['linkSpeed'] == '1000 Full'
    assert by_num[4]['ip'] == '10.31.8.73'
    assert by_num[4]['mac'] == '28:36:38:C0:6D:51'
    assert by_num[4]['linkSpeed'] == '100T Full'
    assert by_num[5]['host'] == 'Raspberry Pi Trading Ltd'
    assert by_num[5]['ip'] == '10.0.5.5'
    assert by_num[5]['powerWatts'] == '6 Watts'


def test_unconnected_port_has_no_host_keys(snapshot):
    by_num = {p['port']: p for p in snapshot['netgearPorts']}
    assert by_num[3].get('host') is None
    assert by_num[3].get('ip') is None


def test_count_mismatch_drops_host_data_but_keeps_ports():
    """One popover renamed out of the selector -> 11 popovers for 12 ports ->
    alignment unprovable -> drop popover fields wholesale, keep everything read
    structurally.

    'sakura-port-popover"' matches only the real popovers; the interleaved
    child panels end 'sakura-child-port-popover"', so this removes exactly one.
    """
    html = FIXTURE.read_text(encoding='utf-8')
    degraded = html.replace('sakura-port-popover"', 'sakura-port-popover-x"', 1)
    assert degraded != html

    parsed = parse_snapshot(degraded)
    assert parsed['netgearPortHostsAvailable'] is False
    assert len(parsed['netgearPorts']) == 12
    assert parsed['netgearPorts'][2]['poe'] is True          # structural, kept
    assert parsed['netgearPorts'][2]['color'] == '#ffa600'   # structural, kept
    assert all('profile' not in p for p in parsed['netgearPorts'])
    assert all('ip' not in p for p in parsed['netgearPorts'])


def test_non_string_input_returns_empty_rather_than_raising():
    """The import route passes through whatever JSON supplied, so a non-str is
    reachable from outside. It must refuse, not raise."""
    for bad in (None, 5, {'html': 'x'}, ['<html>'], b'<html>'):
        assert parse_snapshot(bad) == {}
