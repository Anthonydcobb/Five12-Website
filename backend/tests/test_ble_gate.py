"""The BLE gate defaults OFF. Unlike FIVE12_NETWORK_TOOLS (which defaults on
because probing your own LAN is expected), starting a radio scan without being
asked is not. When off, the routes must not exist at all."""

from app import create_app


def test_ble_disabled_by_default():
    app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
    assert app.config.get('ENABLE_BLE_TOOLS') is False


def test_capabilities_route_absent_when_disabled():
    app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
    resp = app.test_client().get('/api/ble/capabilities')
    assert resp.status_code == 404


def test_capabilities_route_present_when_enabled():
    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'ENABLE_BLE_TOOLS': True,
    })
    resp = app.test_client().get('/api/ble/capabilities')
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['bleToolsEnabled'] is True
    assert 'adapterAvailable' in body
    assert 'platformSupported' in body
