"""Import route tests.

Identity is the MANAGEMENT IP, not the base MAC the page prints.

[VERIFIED 2026-08-06 on the rig] the two are different addresses: the page's
"Base MAC Address" is the chassis MAC, while the scanner's row carries the MAC
the management interface ARPs with. `PAGE_BASE_MAC` and `SCANNER_MAC` below are
both real values for the same physical switch, and the gap between them is the
whole point of this file -- an earlier version of this route matched on the
base MAC and refused every switch on the rig, while its tests passed because
they fabricated the device row from the page's own base MAC.
"""
from pathlib import Path

import pytest

from app import db
from app.models import NetworkDevice

FIXTURE = Path(__file__).parent / 'fixtures' / 'netgear_m4250_overview.html'

# What the Overview page prints as "Base MAC Address".
PAGE_BASE_MAC = '28:94:01:84:3C:DE'
# What the scanner actually sees at 172.16.3.73. Deliberately NOT the above.
SCANNER_MAC = '28:94:01:84:3C:E1'
MGMT_IP = '172.16.3.73'


@pytest.fixture
def html():
    return FIXTURE.read_text(encoding='utf-8')


@pytest.fixture
def switch(db):
    device = NetworkDevice(mac_address=SCANNER_MAC, device_type='netgear',
                           last_ip=MGMT_IP)
    db.session.add(device)
    db.session.commit()
    yield device
    for row in db.session.query(NetworkDevice).all():
        db.session.delete(row)
    db.session.commit()


def test_import_matches_on_management_ip_not_base_mac(client, switch, html):
    """The regression that rig verification caught.

    The stored row's MAC is not the MAC the page reports. Matching on base MAC
    refuses; matching on management IP succeeds. Assert both halves so a
    revert to MAC-matching cannot pass.
    """
    assert switch.mac_address != PAGE_BASE_MAC, 'fixture must encode the real gap'

    res = client.post('/api/network/snapshot', json={'html': html})
    assert res.status_code == 200, res.get_json()
    assert res.json['macAddress'] == SCANNER_MAC
    assert res.json['managementIp'] == MGMT_IP
    assert res.json['profileCount'] == 5
    assert res.json['portCount'] == 12
    assert res.json['hostDataAvailable'] is True

    stored = db.session.get(NetworkDevice, SCANNER_MAC).vendor_data
    assert stored['serial'] == '70VG5C57A01E0'
    assert stored['source'] == 'html-snapshot'
    assert stored['snapshotAsOf'].endswith('Z')
    assert len(stored['netgearPorts']) == 12
    # The chassis MAC is kept for reference even though it is not the matcher.
    assert stored['baseMac'] == PAGE_BASE_MAC
    # Both neighbouring keys are owned by other features with other shapes.
    assert 'ports' not in stored, 'must never occupy the DMX node patch key'
    assert 'switchPorts' not in stored, 'must never occupy the GigaCore SNMP map key'


def test_import_preserves_operator_fields(client, switch, html):
    switch.label = 'FMB Switch 73'
    switch.notes = 'rack 3'
    db.session.commit()
    client.post('/api/network/snapshot', json={'html': html})
    fresh = db.session.get(NetworkDevice, SCANNER_MAC)
    assert fresh.label == 'FMB Switch 73'
    assert fresh.notes == 'rack 3'


def test_import_preserves_live_snmp_fields(client, switch, html):
    """A snapshot must not erase what SNMP already learned."""
    switch.vendor_data = {'firmware': '13.0.9.9', 'clientCount': 7}
    db.session.commit()
    client.post('/api/network/snapshot', json={'html': html})
    stored = db.session.get(NetworkDevice, SCANNER_MAC).vendor_data
    assert stored['clientCount'] == 7, 'key the parse never supplies must survive'
    assert stored['profiles'], 'snapshot data still landed'


def test_unknown_ip_is_refused_and_creates_nothing(client, db, html):
    before = db.session.query(NetworkDevice).count()
    res = client.post('/api/network/snapshot', json={'html': html})
    assert res.status_code == 404
    assert res.json['error'] == 'unknown_device'
    assert MGMT_IP in res.json['detail']
    assert db.session.query(NetworkDevice).count() == before


def test_duplicate_ip_is_refused_rather_than_guessed(client, switch, db, html):
    """Two rows claiming one IP. Picking either would be a coin toss."""
    twin = NetworkDevice(mac_address='AA:BB:CC:DD:EE:FF', device_type='netgear',
                         last_ip=MGMT_IP)
    db.session.add(twin)
    db.session.commit()

    res = client.post('/api/network/snapshot', json={'html': html})
    assert res.status_code == 409
    assert res.json['error'] == 'ambiguous_device'
    assert db.session.get(NetworkDevice, SCANNER_MAC).vendor_data is None
    assert db.session.get(NetworkDevice, 'AA:BB:CC:DD:EE:FF').vendor_data is None


def test_serial_conflict_is_refused(client, switch, html):
    switch.vendor_data = {'serial': 'SOMEOTHERSERIAL'}
    db.session.commit()
    res = client.post('/api/network/snapshot', json={'html': html})
    assert res.status_code == 409
    assert res.json['error'] == 'serial_conflict'
    assert db.session.get(NetworkDevice, SCANNER_MAC).vendor_data['serial'] == 'SOMEOTHERSERIAL'


def test_non_netgear_html_is_refused(client, db):
    res = client.post('/api/network/snapshot',
                      json={'html': '<html><body>hello</body></html>'})
    assert res.status_code == 422
    assert res.json['error'] == 'unrecognised_page'


def test_missing_html_is_refused(client, db):
    res = client.post('/api/network/snapshot', json={})
    assert res.status_code == 422
    assert res.json['error'] == 'unrecognised_page'


def test_non_string_html_is_refused_not_a_500(client, db):
    """The body is whatever JSON the client sent."""
    res = client.post('/api/network/snapshot', json={'html': {'not': 'a string'}})
    assert res.status_code == 422
    assert res.json['error'] == 'unrecognised_page'
