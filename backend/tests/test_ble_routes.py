"""BLE read endpoints. Every route in this module is read-only; there is no
POST anywhere in this phase."""

import asyncio
import threading

import pytest

from app import create_app
from app.five12_ble import scanner as scanner_mod
from app.five12_ble.scanner import get_scan_service


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


def test_sim_snapshot_never_touches_the_scan_loop(ble_client, monkeypatch):
    """Sim snapshots (build_sim_snapshot) are fully synchronous and must never
    go anywhere near BleScanService.loop / asyncio.run_coroutine_threadsafe.
    Making the accessor itself explode is a strong assertion: if the sim path
    were ever wired through the loop dispatch (even by accident), this fails
    loudly instead of silently working by coincidence."""
    def _boom(self):
        raise AssertionError('sim snapshot must not touch the BLE loop accessor')

    monkeypatch.setattr(scanner_mod.BleScanService, 'loop', property(_boom))

    body = ble_client.get('/api/ble/devices/sim-cintenna-tx/snapshot?sim=1').get_json()
    assert body['fields']['mode']['decoded'] == 'tx'


def test_snapshot_no_scan_loop_returns_typed_error(ble_app):
    """REGRESSION — FINDING 1. Under TESTING, no scan thread is ever started
    (see app/__init__.py's factory guard), so the non-sim scan service's loop
    is always None here. The route must report that honestly with a typed
    error rather than silently opening a brand-new event loop on the request
    thread — the exact two-loops-one-adapter hazard the fix removes.

    Against the pre-fix route (plain `asyncio.run(_read_snapshot(os_id))`),
    this fails: bleak isn't installed on this interpreter, so the fallback
    loop's coroutine raises ImportError -> AdapterUnavailable, giving code
    'adapter-unavailable' at 409 instead of 'scan-loop-unavailable' — proof
    the old code took the fallback path this test forbids.
    """
    service = get_scan_service(False)
    assert service.loop is None, 'test bug: a real scan loop is running'
    service.registry.upsert('no-loop-dev', 'F12L - test', -55, {})
    try:
        resp = ble_app.test_client().get('/api/ble/devices/no-loop-dev/snapshot')
        assert resp.status_code == 409
        body = resp.get_json()
        assert body['code'] == 'scan-loop-unavailable'
        assert 'message' in body
    finally:
        service.registry.clear()


def _spin_background_loop():
    """A real asyncio loop on its own thread, standing in for the scan
    service's loop without actually starting scanning (bleak is not
    installed on this interpreter, so a real scan thread can't run here)."""
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    return loop, thread


def _stop_background_loop(loop, thread):
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)
    loop.close()


def test_snapshot_unexpected_exception_returns_typed_error_not_500(ble_app, monkeypatch):
    """REGRESSION — FINDING 2. An exception the connect path never translates
    (WinRT oddities, a bare RuntimeError, ...) must still come back as the
    typed {code, message} shape, at a non-500 status, with no exception text
    or traceback leaked into the body.

    Against the pre-fix route (`except BleError` only), this exception is not
    caught at all: under TESTING, Flask's PROPAGATE_EXCEPTIONS default means
    it re-raises straight through the test client as a bare RuntimeError
    instead of coming back as any HTTP response — i.e. the pre-fix code
    doesn't even reach the point of picking a (wrong) status code.
    """
    from app import ble_routes

    service = get_scan_service(False)
    service.registry.upsert('boom-dev', 'F12L - test', -55, {})
    loop, thread = _spin_background_loop()
    secret = 'winrt 0x8007048f: radio powered off (should never reach the client)'

    async def _boom(os_id):
        raise RuntimeError(secret)

    monkeypatch.setattr(ble_routes, '_read_snapshot', _boom)
    service._loop = loop
    try:
        resp = ble_app.test_client().get('/api/ble/devices/boom-dev/snapshot')
        assert resp.status_code == 409
        body = resp.get_json()
        assert body['code'] == 'unexpected-ble-failure'
        assert 'message' in body
        raw = resp.get_data(as_text=True)
        assert secret not in raw
        assert 'Traceback' not in raw
        assert 'RuntimeError' not in raw
    finally:
        service._loop = None
        service.registry.clear()
        _stop_background_loop(loop, thread)


def test_status_reports_scan_state(ble_client):
    body = ble_client.get('/api/ble/status?sim=1').get_json()
    assert 'running' in body
    assert body['sim'] is True


def test_read_only_app_still_exposes_no_mutating_route(ble_app):
    """RELEASE GATE, carried forward. `ble_app` is built without
    ENABLE_BLE_WRITE, so it is the read-only build — and that build must
    still have no way to change a radio. The write build's routes are
    asserted separately in test_ble_command_routes.py."""
    for rule in ble_app.url_map.iter_rules():
        if str(rule).startswith('/api/ble'):
            assert rule.methods & {'POST', 'PUT', 'PATCH', 'DELETE'} == set(), str(rule)
