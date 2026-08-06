"""A snapshot must survive the sweep that follows it.

enrich_device returns {} for every M4250 without SNMP v2c configured -- six of
the seven on this rig -- and that happens every 300s. If the scanner ever goes
back to assigning vendor_data wholesale, an imported snapshot is erased within
seconds of being saved and the Network tab silently empties.
"""
from unittest.mock import patch

import pytest

from app import db
from app.models import NetworkDevice
from app.scanner import _process_discovered_device

MAC = '28:94:01:84:3A:02'
IP = '172.16.3.60'

SNAPSHOT = {
    'serial': '70VG5C5RA0129',
    'firmware': '13.0.5.26',
    'source': 'html-snapshot',
    'snapshotAsOf': '2026-08-06T12:00:00Z',
    'profiles': [{'name': 'FixtureNet', 'vlan': 300}],
    'netgearPorts': [{'port': 1, 'linkUp': True}],
}


@pytest.fixture
def switch(db):
    device = NetworkDevice(mac_address=MAC, device_type='netgear',
                           last_ip=IP, vendor_data=dict(SNAPSHOT))
    db.session.add(device)
    db.session.commit()
    yield device
    db.session.delete(db.session.get(NetworkDevice, MAC))
    db.session.commit()


def test_empty_snmp_read_leaves_snapshot_intact(app, switch):
    with patch('app.vendors.enrich_device', return_value={}):
        _process_discovered_device(IP, MAC, None, app)

    stored = db.session.get(NetworkDevice, MAC).vendor_data
    assert stored['profiles'] == SNAPSHOT['profiles']
    assert stored['netgearPorts'] == SNAPSHOT['netgearPorts']
    assert stored['snapshotAsOf'] == SNAPSHOT['snapshotAsOf']


def test_live_snmp_wins_for_its_own_fields_only(app, switch):
    live = {'firmware': '13.0.6.1', 'portCount': 12, 'activePorts': 3}
    with patch('app.vendors.enrich_device', return_value=live):
        _process_discovered_device(IP, MAC, None, app)

    stored = db.session.get(NetworkDevice, MAC).vendor_data
    assert stored['firmware'] == '13.0.6.1', 'SNMP is live; it wins'
    assert stored['portCount'] == 12
    assert stored['profiles'] == SNAPSHOT['profiles'], 'SNMP has no OID for these'
    assert stored['source'] == 'html-snapshot'
