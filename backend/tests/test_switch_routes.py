"""Switch port map and reverse lookup routes.

Both are strictly read-only toward the database: the scanner concurrently
updates these rows, and a live value disagreeing with the stored one is not
evidence the sweep was wrong.
"""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app.models import NetworkDevice


PORTS = [
    {'port': 5, 'name': 'Port 5', 'link': 'up',
     'macs': ['00:19:7C:02:E0:5B'], 'deviceCount': 1},
    {'port': 12, 'name': 'Port 12', 'link': 'up',
     'macs': ['00:19:7C:15:E4:97', '04:11:19:90:01:C0'], 'deviceCount': 2},
]


@pytest.fixture
def switch(db):
    row = NetworkDevice(
        mac_address='D0:69:9E:04:78:72',
        device_type='luminex',
        label='Luminex (CARL)',
        last_ip='172.16.1.21',
        last_seen=datetime.utcnow() - timedelta(seconds=30),
        vendor_data={'model': 'GigaCore12 GigaBit Ethernet Switch',
                     'switchPorts': PORTS,
                     'switchPortsAsOf': '2026-08-06T13:15:16.000000Z'},
    )
    db.session.add(row)
    db.session.commit()
    yield row
    db.session.delete(row)
    db.session.commit()


def test_a_reachable_switch_is_read_live(client, switch):
    fresh = [dict(PORTS[0], macs=['AA:BB:CC:00:00:01'])]
    with patch('app.vendors.read_switch_ports', return_value={'switchPorts': fresh}):
        res = client.get(f'/api/network/devices/{switch.mac_address}/switch-ports')

    body = res.get_json()
    assert body['live'] is True
    assert body['switchPorts'][0]['macs'] == ['AA:BB:CC:00:00:01']
    assert body['asOf'].endswith('Z')


def test_an_unreachable_switch_falls_back_to_the_stored_map(client, switch):
    with patch('app.vendors.read_switch_ports', return_value={}):
        res = client.get(f'/api/network/devices/{switch.mac_address}/switch-ports')

    body = res.get_json()
    assert body['live'] is False
    assert body['switchPorts'][0]['port'] == 5
    # The map's OWN timestamp, never last_seen: last_seen is the ICMP clock,
    # refreshed every 20s by a keep-alive that does not walk SNMP.
    assert body['asOf'] == '2026-08-06T13:15:16.000000Z'


def test_a_live_read_never_commits(client, db, switch):
    fresh = [dict(PORTS[0], macs=['AA:BB:CC:00:00:01'])]
    with patch('app.vendors.read_switch_ports', return_value={'switchPorts': fresh}), \
         patch.object(db.session, 'commit') as commit:
        client.get(f'/api/network/devices/{switch.mac_address}/switch-ports')
    commit.assert_not_called()


def test_a_switch_with_no_ip_is_not_probed(client, db):
    row = NetworkDevice(mac_address='D0:69:9E:00:00:01', device_type='luminex',
                        vendor_data={'switchPorts': PORTS})
    db.session.add(row); db.session.commit()
    try:
        with patch('app.vendors.read_switch_ports') as reader:
            res = client.get('/api/network/devices/D0:69:9E:00:00:01/switch-ports')
        reader.assert_not_called()
        assert res.get_json()['live'] is False
    finally:
        db.session.delete(row); db.session.commit()


def test_uplink_finds_a_directly_attached_device(client, db, switch):
    dev = NetworkDevice(mac_address='00:19:7C:02:E0:5B', device_type='bolero',
                        label='Bollero Antenna #1', last_ip='192.168.1.11')
    db.session.add(dev); db.session.commit()
    try:
        res = client.get('/api/network/devices/00:19:7C:02:E0:5B/uplink')
        body = res.get_json()
        assert body['found'] is True
        assert body['port'] == 5
        assert body['deviceCount'] == 1
        assert body['switchLabel'] == 'Luminex (CARL)'
    finally:
        db.session.delete(dev); db.session.commit()


def test_uplink_reports_the_count_for_a_device_seen_only_via_an_uplink(client, db, switch):
    """deviceCount 2 means the UI must say "behind", not "on"."""
    dev = NetworkDevice(mac_address='00:19:7C:15:E4:97', device_type='unknown')
    db.session.add(dev); db.session.commit()
    try:
        body = client.get('/api/network/devices/00:19:7C:15:E4:97/uplink').get_json()
        assert body['found'] is True
        assert body['deviceCount'] == 2
    finally:
        db.session.delete(dev); db.session.commit()


def test_uplink_reports_not_found_for_an_unseen_device(client, db, switch):
    dev = NetworkDevice(mac_address='11:22:33:44:55:66', device_type='unknown')
    db.session.add(dev); db.session.commit()
    try:
        assert client.get('/api/network/devices/11:22:33:44:55:66/uplink').get_json() == {'found': False}
    finally:
        db.session.delete(dev); db.session.commit()


def test_uplink_issues_no_snmp(client, db, switch):
    """It is pure computation over rows already in the database. Walking six
    switches on every device selection would put constant SNMP load on live
    show hardware."""
    dev = NetworkDevice(mac_address='00:19:7C:02:E0:5B', device_type='bolero')
    db.session.add(dev); db.session.commit()
    try:
        with patch('app.vendors.read_switch_ports') as reader:
            client.get('/api/network/devices/00:19:7C:02:E0:5B/uplink')
        reader.assert_not_called()
    finally:
        db.session.delete(dev); db.session.commit()


def test_both_routes_404_an_unknown_mac(client):
    assert client.get('/api/network/devices/FF:FF:FF:FF:FF:FF/switch-ports').status_code == 404
    assert client.get('/api/network/devices/FF:FF:FF:FF:FF:FF/uplink').status_code == 404
