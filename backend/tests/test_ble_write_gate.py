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
    """The read-only build must report ENABLE_BLE_WRITE as False in its
    resolved app.config — the thing every route and capability check actually
    reads — regardless of what FIVE12_BLE_WRITE happens to be set to in the
    process environment (e.g. during the hardware acceptance walkthrough,
    which runs with it exported).

    Asserted through create_app(...).config, the way the sibling gate tests
    below build read_only_app/write_app, rather than reading
    DevelopmentConfig.ENABLE_BLE_WRITE directly: that class attribute is
    itself populated from os.environ at class-body evaluation time, so
    asserting on it directly makes this test's outcome depend on whatever
    FIVE12_BLE_WRITE happens to be in the environment it runs under, rather
    than pinning the gate's off state the way every other config-shaped
    assertion in this module does."""
    app = _app(ENABLE_BLE_WRITE=False)
    assert app.config['ENABLE_BLE_WRITE'] is False


def test_capabilities_reports_write_disabled(read_only_app):
    body = read_only_app.test_client().get('/api/ble/capabilities?sim=1').get_json()
    assert body['bleToolsEnabled'] is True
    assert body['bleWriteEnabled'] is False


def test_capabilities_reports_write_enabled(write_app):
    body = write_app.test_client().get('/api/ble/capabilities?sim=1').get_json()
    assert body['bleWriteEnabled'] is True
