"""CintennaAdapter is the bridge between the BLE service and the existing
Devices page. Adding it to ALL_DEVICE_IDS is what makes the tab render."""

from app.integrations import ALL_DEVICE_IDS, get_adapter
from app.integrations.cintenna import CintennaAdapter


def test_cintenna_is_a_known_device_id():
    assert 'cintenna' in ALL_DEVICE_IDS


def test_get_adapter_returns_cintenna():
    adapter = get_adapter('cintenna', sim=True)
    assert isinstance(adapter, CintennaAdapter)
    assert adapter.id == 'cintenna'


def test_adapter_is_cached_per_sim_flag():
    assert get_adapter('cintenna', sim=True) is get_adapter('cintenna', sim=True)
    assert get_adapter('cintenna', sim=True) is not get_adapter('cintenna', sim=False)


def test_detect_reports_found_in_sim_with_device_count():
    adapter = get_adapter('cintenna', sim=True)
    adapter.service.poll_sim()
    det = adapter.detect()
    assert det['found'] is True
    assert '2' in det['detail']


def test_status_lists_devices_and_is_camel_case():
    adapter = get_adapter('cintenna', sim=True)
    adapter.service.poll_sim()
    status = adapter.get_status()
    assert status['available'] is True
    assert 'alerts' in status
    assert len(status['devices']) == 2
    assert 'osId' in status['devices'][0]


def test_status_devices_carry_no_gatt_fields():
    """The roster is advertisement-only. Nearby is not connected."""
    adapter = get_adapter('cintenna', sim=True)
    adapter.service.poll_sim()
    for dev in adapter.get_status()['devices']:
        for forbidden in ('battery', 'firmware', 'mode', 'linked'):
            assert forbidden not in dev


def test_devices_route_includes_cintenna(client):
    """The whole point: GET /api/devices must return a cintenna entry, because
    Devices.jsx renders its tab strip from that response."""
    resp = client.get('/api/devices?sim=1')
    assert resp.status_code == 200
    ids = [d['id'] for d in resp.get_json()]
    assert 'cintenna' in ids


def test_devices_route_cintenna_entry_shape(client):
    entry = next(d for d in client.get('/api/devices?sim=1').get_json()
                 if d['id'] == 'cintenna')
    assert entry['name']
    assert 'found' in entry
    assert 'detail' in entry
