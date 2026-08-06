from pathlib import Path

import pytest

from app import db
from app.models import NetworkDevice

FIXTURE = Path(__file__).parent / 'fixtures' / 'netgear_m4250_overview.html'
MAC = '28:94:01:84:3C:DE'


@pytest.fixture
def html():
    return FIXTURE.read_text(encoding='utf-8')


@pytest.fixture
def switch(db):
    device = NetworkDevice(mac_address=MAC, device_type='netgear', last_ip='172.16.3.73')
    db.session.add(device)
    db.session.commit()
    yield device
    db.session.delete(db.session.get(NetworkDevice, MAC))
    db.session.commit()


def test_import_writes_snapshot(client, switch, html):
    res = client.post('/api/network/snapshot', json={'html': html})
    assert res.status_code == 200
    assert res.json['macAddress'] == MAC
    assert res.json['profileCount'] == 5
    assert res.json['portCount'] == 12
    assert res.json['hostDataAvailable'] is True

    stored = db.session.get(NetworkDevice, MAC).vendor_data
    assert stored['serial'] == '70VG5C57A01E0'
    assert stored['source'] == 'html-snapshot'
    assert stored['snapshotAsOf'].endswith('Z')
    assert len(stored['netgearPorts']) == 12
    # Both neighbouring keys are owned by other features with other shapes.
    assert 'ports' not in stored, 'must never occupy the DMX node patch key'
    assert 'switchPorts' not in stored, 'must never occupy the GigaCore SNMP map key'


def test_import_preserves_operator_fields(client, switch, html):
    switch.label = 'FMB Switch 60'
    switch.notes = 'rack 3'
    db.session.commit()
    client.post('/api/network/snapshot', json={'html': html})
    fresh = db.session.get(NetworkDevice, MAC)
    assert fresh.label == 'FMB Switch 60'
    assert fresh.notes == 'rack 3'


def test_unknown_mac_is_refused_and_creates_nothing(client, db, html):
    before = db.session.query(NetworkDevice).count()
    res = client.post('/api/network/snapshot', json={'html': html})
    assert res.status_code == 404
    assert res.json['error'] == 'unknown_device'
    assert db.session.query(NetworkDevice).count() == before


def test_serial_conflict_is_refused(client, switch, html):
    switch.vendor_data = {'serial': 'SOMEOTHERSERIAL'}
    db.session.commit()
    res = client.post('/api/network/snapshot', json={'html': html})
    assert res.status_code == 409
    assert res.json['error'] == 'serial_conflict'
    assert db.session.get(NetworkDevice, MAC).vendor_data['serial'] == 'SOMEOTHERSERIAL'


def test_non_netgear_html_is_refused(client, db):
    res = client.post('/api/network/snapshot', json={'html': '<html><body>hello</body></html>'})
    assert res.status_code == 422
    assert res.json['error'] == 'unrecognised_page'


def test_missing_html_is_refused(client, db):
    res = client.post('/api/network/snapshot', json={})
    assert res.status_code == 422
    assert res.json['error'] == 'unrecognised_page'
