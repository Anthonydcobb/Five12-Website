"""Portconfig import route tests.

The Port Configuration page carries NO identity fields at all -- no management
IP, name, model or serial. Worse, the only IP readable as TEXT on it is the
LLDP neighbour's (172.16.3.52, "FMB Switch 52"), while the switch's own
(172.16.3.73) appears solely inside attributes and scripts. So identity here is
an explicit operator choice, and these tests exist to prove the route never
infers it from the page.
"""
from pathlib import Path

import pytest

from app import db as _db
from app.models import NetworkDevice

FIXTURES = Path(__file__).parent / 'fixtures'
PORTCONFIG = FIXTURES / 'netgear_m4250_portconfig.html'

SCANNER_MAC = '28:94:01:84:3C:E1'
MGMT_IP = '172.16.3.73'
# The LLDP neighbour that appears as visible text on the page. No request may
# ever be filed against this device.
NEIGHBOUR_MAC = '28:94:01:84:47:05'
NEIGHBOUR_IP = '172.16.3.52'


@pytest.fixture
def portconfig_html():
    return PORTCONFIG.read_text(encoding='utf-8')


@pytest.fixture
def switch(db):
    """A switch that already holds an Overview snapshot, plus the neighbour."""
    device = NetworkDevice(mac_address=SCANNER_MAC, device_type='netgear',
                           last_ip=MGMT_IP)
    device.vendor_data = {
        'serial': 'ABC123',
        # The fixture page claims to be "FMB Switch 73". Matching stored name
        # means the page and the operator's selection agree.
        'systemName': 'FMB Switch 73',
        'netgearPorts': [
            {'port': 1, 'profile': 'Default', 'template': 'Default', 'linkUp': True},
            {'port': 3, 'profile': 'WRONG', 'template': 'Data', 'linkUp': False},
            {'port': 12, 'profile': 'VidNet', 'template': 'Video', 'linkUp': True},
        ],
    }
    neighbour = NetworkDevice(mac_address=NEIGHBOUR_MAC, device_type='netgear',
                              last_ip=NEIGHBOUR_IP)
    db.session.add_all([device, neighbour])
    db.session.commit()
    yield device
    for row in db.session.query(NetworkDevice).all():
        db.session.delete(row)
    db.session.commit()


def test_refuses_a_portconfig_page_with_no_device(client, switch, portconfig_html):
    res = client.post('/api/network/snapshot', json={'html': portconfig_html})
    assert res.status_code == 400
    assert res.get_json()['error'] == 'device_required'


def test_refuses_an_unknown_mac(client, switch, portconfig_html):
    res = client.post('/api/network/snapshot',
                      json={'html': portconfig_html, 'macAddress': 'AA:BB:CC:DD:EE:FF'})
    assert res.status_code == 404
    assert res.get_json()['error'] == 'unknown_device'


def test_refuses_a_device_with_no_base_snapshot(client, switch, portconfig_html):
    res = client.post('/api/network/snapshot',
                      json={'html': portconfig_html, 'macAddress': NEIGHBOUR_MAC})
    assert res.status_code == 409
    assert res.get_json()['error'] == 'no_base_snapshot'


def test_never_files_against_the_neighbour_named_on_the_page(client, switch, portconfig_html):
    """The page names 172.16.3.52 as text. Importing for the real switch must
    leave that device completely untouched."""
    client.post('/api/network/snapshot',
                json={'html': portconfig_html, 'macAddress': SCANNER_MAC})
    neighbour = (_db.session.query(NetworkDevice)
                 .filter_by(mac_address=NEIGHBOUR_MAC).one())
    assert not (neighbour.vendor_data or {}).get('netgearPortConfig')


def test_stores_profiles_under_its_own_key(client, switch, portconfig_html):
    res = client.post('/api/network/snapshot',
                      json={'html': portconfig_html, 'macAddress': SCANNER_MAC})
    assert res.status_code == 200
    device = _db.session.query(NetworkDevice).filter_by(mac_address=SCANNER_MAC).one()
    rows = {r['port']: r for r in device.vendor_data['netgearPortConfig']}
    assert rows[3]['profile'] == 'HogNet'
    # netgearPorts is NOT rewritten -- the two sources stay distinguishable.
    ports = {p['port']: p for p in device.vendor_data['netgearPorts']}
    assert ports[3]['profile'] == 'WRONG'


def test_leaves_an_uncaptured_port_alone(client, switch, portconfig_html):
    """Port 12 is not in the capture (virtual scroller). It must survive."""
    client.post('/api/network/snapshot',
                json={'html': portconfig_html, 'macAddress': SCANNER_MAC})
    device = _db.session.query(NetworkDevice).filter_by(mac_address=SCANNER_MAC).one()
    ports = {p['port']: p for p in device.vendor_data['netgearPorts']}
    assert ports[12]['profile'] == 'VidNet'


def test_reports_a_profile_disagreement_without_failing(client, switch, portconfig_html):
    """Port 3's stored popover-derived profile is 'WRONG'; the row says
    'HogNet'. That disagreement is the evidence the popover association
    misattributed, and it is reported, not fatal."""
    res = client.post('/api/network/snapshot',
                      json={'html': portconfig_html, 'macAddress': SCANNER_MAC})
    assert res.status_code == 200
    body = res.get_json()
    ports = [d['port'] for d in body['disagreements']]
    assert 3 in ports
    assert 1 not in ports


def test_reports_captured_ports_absent_from_the_base(client, switch, portconfig_html):
    res = client.post('/api/network/snapshot',
                      json={'html': portconfig_html, 'macAddress': SCANNER_MAC})
    # The base holds ports 1, 3, 12. The capture holds 1..10.
    assert res.get_json()['portsInCaptureNotInBase'] == [2, 4, 5, 6, 7, 8, 9, 10]


def test_refuses_when_the_page_names_a_different_switch(client, switch, portconfig_html):
    """The gap the explicit-MAC design cannot close on its own: an operator
    looking at switch 69 who pastes switch 73's page. The page says which
    switch it came from, and disagreeing with the selection is a refusal --
    filing one switch's profiles against another is the worst outcome here."""
    device = _db.session.query(NetworkDevice).filter_by(mac_address=SCANNER_MAC).one()
    device.vendor_data = {**device.vendor_data, 'systemName': 'FMB Switch 69'}
    _db.session.commit()

    res = client.post('/api/network/snapshot',
                      json={'html': portconfig_html, 'macAddress': SCANNER_MAC})
    assert res.status_code == 409
    body = res.get_json()
    assert body['error'] == 'device_mismatch'
    # Both names appear, so the operator can see which way round it is.
    assert 'FMB Switch 69' in body['detail']
    assert 'FMB Switch 73' in body['detail']
    # Nothing was written.
    after = _db.session.query(NetworkDevice).filter_by(mac_address=SCANNER_MAC).one()
    assert 'netgearPortConfig' not in (after.vendor_data or {})


def test_imports_when_the_names_agree(client, switch, portconfig_html):
    res = client.post('/api/network/snapshot',
                      json={'html': portconfig_html, 'macAddress': SCANNER_MAC})
    assert res.status_code == 200
    assert res.get_json()['confirmedName'] == 'FMB Switch 73'


def test_proceeds_when_no_stored_name_exists_to_compare(client, switch, portconfig_html):
    """Absence of evidence is not evidence of mismatch. A switch imported
    before systemName was stored must still accept a portconfig page, and the
    response says the check did not run."""
    device = _db.session.query(NetworkDevice).filter_by(mac_address=SCANNER_MAC).one()
    vd = dict(device.vendor_data)
    vd.pop('systemName', None)
    device.vendor_data = vd
    _db.session.commit()

    res = client.post('/api/network/snapshot',
                      json={'html': portconfig_html, 'macAddress': SCANNER_MAC})
    assert res.status_code == 200
    assert res.get_json()['confirmedName'] is None


def test_an_overview_page_still_imports_unchanged(client, db):
    """Regression: dispatch must not break the existing path.

    Cleans up in a finally. This suite's database persists across tests, so a
    row left behind here collides on the unique MAC in the next module -- which
    is exactly what it did before the finally was added.
    """
    overview = (FIXTURES / 'netgear_m4250_overview.html').read_text(encoding='utf-8')
    device = NetworkDevice(mac_address=SCANNER_MAC, device_type='netgear', last_ip=MGMT_IP)
    db.session.add(device)
    db.session.commit()
    try:
        res = client.post('/api/network/snapshot', json={'html': overview})
        assert res.status_code == 200
        assert res.get_json()['portCount'] == 12
    finally:
        for row in db.session.query(NetworkDevice).all():
            db.session.delete(row)
        db.session.commit()
