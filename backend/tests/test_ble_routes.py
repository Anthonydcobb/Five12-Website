"""BLE read endpoints. Every route in this module is read-only; there is no
POST anywhere in this phase."""

import pytest

from app import create_app


@pytest.fixture(scope='module')
def ble_app():
    return create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'ENABLE_BLE_TOOLS': True,
    })


@pytest.fixture
def ble_client(ble_app):
    return ble_app.test_client()


def test_capabilities_reports_sim_adapter_available(ble_client):
    body = ble_client.get('/api/ble/capabilities?sim=1').get_json()
    assert body['bleToolsEnabled'] is True
    assert body['adapterAvailable'] is True


def test_devices_lists_simulated_radios(ble_client):
    body = ble_client.get('/api/ble/devices?sim=1').get_json()
    assert body['deviceCount'] == 2
    assert {d['localName'] for d in body['devices']} == {'F12L - 1946', 'F12L - 2071'}


def test_devices_are_advertisement_only(ble_client):
    body = ble_client.get('/api/ble/devices?sim=1').get_json()
    for dev in body['devices']:
        assert dev['platform'] == 'lumenradio-timotwo-compatible'
        assert dev['product'] is None
        assert 'battery' not in dev


def test_snapshot_returns_decoded_fields(ble_client):
    body = ble_client.get('/api/ble/devices/sim-cintenna-tx/snapshot?sim=1').get_json()
    assert body['fields']['mode']['decoded'] == 'tx'
    assert body['fields']['firmware']['decoded'] == '1.0.7.2'
    assert body['fields']['outputPower']['toolboxLabel'] == '>100 mW'


def test_snapshot_unknown_device_404s(ble_client):
    resp = ble_client.get('/api/ble/devices/nope/snapshot?sim=1')
    assert resp.status_code == 404
    assert resp.get_json()['code'] == 'device-not-found'


def test_status_reports_scan_state(ble_client):
    body = ble_client.get('/api/ble/status?sim=1').get_json()
    assert 'running' in body
    assert body['sim'] is True


def test_no_post_routes_exist_in_this_phase(ble_app):
    """RELEASE GATE. The read-only phase must expose no mutating endpoint."""
    for rule in ble_app.url_map.iter_rules():
        if str(rule).startswith('/api/ble'):
            assert rule.methods & {'POST', 'PUT', 'PATCH', 'DELETE'} == set(), str(rule)
