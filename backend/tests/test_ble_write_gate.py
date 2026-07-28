"""The write gate is separate from the read gate on purpose: discovering
radios and changing them are different risks. Read-only must remain the
default even with Bluetooth fully enabled."""

import pytest

from app import create_app


def _app(**overrides):
    config = {
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'ENABLE_BLE_TOOLS': True,
    }
    config.update(overrides)
    return create_app(config)


@pytest.fixture(scope='module')
def read_only_app():
    return _app(ENABLE_BLE_WRITE=False)


@pytest.fixture(scope='module')
def write_app():
    return _app(ENABLE_BLE_WRITE=True)


def test_write_gate_defaults_off():
    """FIVE12_BLE_WRITE is unset in the test environment, so a config built
    without an explicit override must come back False."""
    from config import DevelopmentConfig
    assert DevelopmentConfig.ENABLE_BLE_WRITE is False


def test_capabilities_reports_write_disabled(read_only_app):
    body = read_only_app.test_client().get('/api/ble/capabilities?sim=1').get_json()
    assert body['bleToolsEnabled'] is True
    assert body['bleWriteEnabled'] is False


def test_capabilities_reports_write_enabled(write_app):
    body = write_app.test_client().get('/api/ble/capabilities?sim=1').get_json()
    assert body['bleWriteEnabled'] is True
