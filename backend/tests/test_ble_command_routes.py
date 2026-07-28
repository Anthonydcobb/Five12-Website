"""The only two mutating routes in the app's Bluetooth surface. With the
write gate off they must not exist at all: no route is registered, so a
request lands on a 404 or (via the SPA catch-all's GET-only rule, see below)
a 405 — never a 403."""

import pytest

from app import create_app
from app.five12_ble.sim import sim_reset
from app.five12_ble.scanner import get_scan_service

# Reused rather than reimplemented: same fixture pattern the read routes'
# regression tests already established for exercising the non-sim path
# hermetically (a real loop on a background thread standing in for the scan
# service's, since bleak is not installed on this interpreter).
from tests.test_ble_routes import _spin_background_loop, _stop_background_loop


def _app(write_enabled):
    return create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'ENABLE_BLE_TOOLS': True,
        'ENABLE_BLE_WRITE': write_enabled,
    })


@pytest.fixture(scope='module')
def read_only_client():
    return _app(False).test_client()


@pytest.fixture(scope='module')
def write_client():
    return _app(True).test_client()


@pytest.fixture(autouse=True)
def clean_sim_state():
    """This module writes real sim state through the command routes (a 'link'
    execution flips LINK_ACTION). sim.py's _GATT dict is a module-global that
    outlives any one test, so without a reset here those writes leak into
    unrelated files collected later in the same run — e.g. test_ble_sim.py's
    fixture-baseline assertions. Same pattern as test_ble_sim_writes.py."""
    sim_reset()
    yield
    sim_reset()


def test_no_mutating_route_is_registered_with_the_write_gate_off():
    """STRUCTURAL, and the real test — mirrors
    test_exactly_two_mutating_routes_exist_with_the_gate_on below, so the pair
    reads as a matched set. With ENABLE_BLE_WRITE off, no rule under
    /api/ble may accept POST/PUT/PATCH/DELETE at all."""
    app = _app(False)
    mutating = [
        str(rule) for rule in app.url_map.iter_rules()
        if str(rule).startswith('/api/ble')
        and rule.methods & {'POST', 'PUT', 'PATCH', 'DELETE'}
    ]
    assert mutating == []


def test_command_routes_are_unreachable_with_the_write_gate_off(read_only_client):
    """END-TO-END SANITY, secondary to the structural test above. A request
    cannot reach a handler at either path.

    Status is 404 OR 405, never 200 and never 403: a SPA catch-all in
    backend/app/routes.py registers '/<path:path>' for GET/HEAD/OPTIONS only
    (`@bp.route('/', defaults={'path': ''})` / `@bp.route('/<path:path>')`,
    `def serve_frontend(path)`), so a POST to ANY unregistered path in this
    app — not just these two, and unrelated to Bluetooth — is matched by
    that GET-only rule and yields 405 Method Not Allowed rather than Flask's
    plain 404. Do not "fix" this back to a bare 404 assertion; it would just
    make the test wrong again the moment someone reruns it against the real
    app. Either status proves the same property: no POST handler exists at
    this path."""
    for path in ('/api/ble/devices/sim-cintenna-tx/commands',
                 '/api/ble/devices/sim-cintenna-tx/commands/prepare'):
        status = read_only_client.post(path, json={'command': 'link'}).status_code
        assert status in (404, 405)


def test_exactly_two_mutating_routes_exist_with_the_gate_on():
    """RELEASE GATE, inverted from the read-only phase."""
    app = _app(True)
    mutating = sorted(
        str(rule) for rule in app.url_map.iter_rules()
        if str(rule).startswith('/api/ble')
        and rule.methods & {'POST', 'PUT', 'PATCH', 'DELETE'}
    )
    assert mutating == [
        '/api/ble/devices/<os_id>/commands',
        '/api/ble/devices/<os_id>/commands/prepare',
    ]


def test_prepare_then_execute_a_link_in_sim(write_client):
    prep = write_client.post(
        '/api/ble/devices/sim-cintenna-tx/commands/prepare?sim=1',
        json={'command': 'link'}).get_json()
    assert prep['currentMode'] == 'tx'
    assert 'range' in prep['warning'].lower()

    resp = write_client.post(
        '/api/ble/devices/sim-cintenna-tx/commands?sim=1',
        json={'command': 'link', 'expectedMode': 'tx',
              'confirmationToken': prep['token']})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['attAcknowledged'] is True
    assert body['verification'] == 'ack-only'
    assert 'linked' not in body


def test_link_on_a_receiver_is_refused_with_operator_copy(write_client):
    prep = write_client.post(
        '/api/ble/devices/sim-cintenna-rx/commands/prepare?sim=1',
        json={'command': 'link'}).get_json()
    resp = write_client.post(
        '/api/ble/devices/sim-cintenna-rx/commands?sim=1',
        json={'command': 'link', 'expectedMode': 'rx',
              'confirmationToken': prep['token']})
    assert resp.status_code == 409
    assert resp.get_json()['code'] == 'wrong-mode'
    assert 'message' in resp.get_json()


def test_execute_without_a_confirmation_is_refused(write_client):
    resp = write_client.post(
        '/api/ble/devices/sim-cintenna-tx/commands?sim=1',
        json={'command': 'link', 'expectedMode': 'tx'})
    assert resp.status_code == 409
    assert resp.get_json()['code'] == 'confirmation-invalid'


def test_unknown_command_is_refused(write_client):
    resp = write_client.post(
        '/api/ble/devices/sim-cintenna-tx/commands/prepare?sim=1',
        json={'command': 'set_output_power'})
    assert resp.status_code == 409
    assert resp.get_json()['code'] == 'unknown-command'


def test_the_client_cannot_name_a_uuid_or_a_payload(write_client):
    """The request body has no field that could carry either. Anything extra
    is ignored, not honoured."""
    prep = write_client.post(
        '/api/ble/devices/sim-cintenna-tx/commands/prepare?sim=1',
        json={'command': 'link'}).get_json()
    resp = write_client.post(
        '/api/ble/devices/sim-cintenna-tx/commands?sim=1',
        json={'command': 'link', 'expectedMode': 'tx',
              'confirmationToken': prep['token'],
              'uuid': '33b53770-0942-1f91-379b-ac5af36b9efa',
              'payload': 'FF'})
    assert resp.status_code == 200
    # The write that landed is the one the TABLE specifies, not the one the
    # client tried to smuggle in.
    from app.five12_ble import constants as c
    from app.five12_ble.sim import sim_gatt_values
    assert sim_gatt_values('sim-cintenna-tx')[c.LINK_ACTION] == b'\x05'
    assert sim_gatt_values('sim-cintenna-tx')[c.OUTPUT_POWER] == b'\x02'


def test_unknown_device_404s(write_client):
    resp = write_client.post('/api/ble/devices/ghost/commands/prepare?sim=1',
                             json={'command': 'link'})
    assert resp.status_code == 404
    assert resp.get_json()['code'] == 'device-not-found'


def test_sim_unexpected_exception_returns_typed_error_not_500(write_client, monkeypatch):
    """REGRESSION — FIX 1. Before the fix, `_run`'s sim branch returned
    `jsonify(asyncio.run(...))` with no exception translation of its own, and
    _catch_sim_errors (formerly _sim_or_404) only catches DeviceNotFound/
    BleError -- so anything else (e.g. the RuntimeError asyncio.run raises
    when the request thread already has a running event loop, the documented
    non-sync-worker caveat in ble_routes.py) escaped untranslated.

    Against the pre-fix code this test does not merely fail an assertion: the
    RuntimeError climbs out of both _run and _catch_sim_errors uncaught, and
    under TESTING Flask's PROPAGATE_EXCEPTIONS default re-raises it straight
    through the test client instead of yielding any HTTP response at all --
    exactly the raw-500/traceback failure mode Fix 1 closes.
    """
    from app import ble_command_routes

    secret = 'boom: nested event loop (should never reach the client)'

    async def _boom(os_id, command_name, registry, sim=False):
        raise RuntimeError(secret)

    monkeypatch.setattr(ble_command_routes, 'prepare_command', _boom)

    resp = write_client.post(
        '/api/ble/devices/sim-cintenna-tx/commands/prepare?sim=1',
        json={'command': 'link'})

    assert resp.status_code != 500
    body = resp.get_json()
    assert body['code'] == 'unexpected-ble-failure'
    assert 'message' in body
    raw = resp.get_data(as_text=True)
    assert secret not in raw
    assert 'Traceback' not in raw
    assert 'RuntimeError' not in raw


def test_no_scan_loop_returns_typed_error_on_non_sim_path(write_client):
    """REGRESSION — FIX 2 (no-loop case). Under TESTING no scan thread is
    ever started, so the non-sim scan service's loop is always None here. A
    non-sim command must report that honestly via ScanLoopUnavailable rather
    than silently opening a fresh event loop on the request thread -- the
    exact two-loops-one-adapter hazard the READ route's fix (test_ble_routes)
    removes and this write route must not reintroduce.

    Before Fix 2 there was no test exercising this branch of `_run` at all:
    every existing test in this module passes ?sim=1 and returns before this
    code runs, so someone could collapse `_run` to a single `asyncio.run` for
    both branches and the whole suite would stay green. This test pins the
    contract: with `service.loop` verified None, the response's `code` must
    be `scan-loop-unavailable`. If a future change made the non-sim branch
    fall back to `asyncio.run` (or any loop it opens itself) instead of
    checking `service.loop`, this device would be reachable and prepare_command
    would run for real (and likely raise a different, untyped error trying to
    connect to a nonexistent radio) -- the code would not be
    'scan-loop-unavailable' and this assertion would fail.
    """
    service = get_scan_service(False)
    assert service.loop is None, 'test bug: a real scan loop is running'
    service.registry.upsert('no-loop-dev', 'F12L - test', -55, {})
    try:
        resp = write_client.post(
            '/api/ble/devices/no-loop-dev/commands/prepare',
            json={'command': 'link'})
        assert resp.status_code == 409
        body = resp.get_json()
        assert body['code'] == 'scan-loop-unavailable'
        assert 'message' in body
    finally:
        service.registry.clear()


def test_non_sim_unexpected_exception_returns_typed_error_not_500(write_client, monkeypatch):
    """REGRESSION — FIX 2 (unexpected-exception case). An exception the
    command service never translates (a WinRT oddity, a bare RuntimeError,
    ...) must still come back as the typed {code, message} shape at a
    non-500 status, with no exception text or traceback leaked into the
    body -- mirrors test_snapshot_unexpected_exception_returns_typed_error_not_500
    in test_ble_routes.py for the read route's equivalent path.

    Against code that dropped the `except Exception` clause from `_run`'s
    real-path handling (e.g. someone "simplifying" it to only catch
    BleError/FutureTimeoutError), this RuntimeError would climb out of the
    submitted future uncaught by `_run`, then out of _catch_sim_errors
    (which only catches BleError), and under TESTING's PROPAGATE_EXCEPTIONS
    default would re-raise straight through the test client rather than
    returning any response -- proving this test fails loudly if that
    handler is ever removed.
    """
    from app import ble_command_routes

    service = get_scan_service(False)
    service.registry.upsert('boom-dev', 'F12L - test', -55, {})
    loop, thread = _spin_background_loop()
    secret = 'winrt 0x8007048f: radio powered off (should never reach the client)'

    async def _boom(os_id, command_name, registry, sim=False):
        raise RuntimeError(secret)

    monkeypatch.setattr(ble_command_routes, 'prepare_command', _boom)
    service._loop = loop
    try:
        resp = write_client.post(
            '/api/ble/devices/boom-dev/commands/prepare',
            json={'command': 'link'})
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


def test_non_sim_unknown_device_404s(write_client):
    """REGRESSION — FIX 2 (registry pre-check). The real path's 404 comes
    solely from `_run`'s registry pre-check, which runs before the loop is
    even consulted -- so this must 404 with no scan loop running at all,
    proving the pre-check (not ScanLoopUnavailable) is what fires for an
    absent device. Before Fix 2 nothing exercised this branch: every
    existing device-not-found test in this module passes ?sim=1, which 404s
    via the sim registry / _catch_sim_errors instead.
    """
    service = get_scan_service(False)
    assert service.registry.get('never-registered-device') is None
    resp = write_client.post(
        '/api/ble/devices/never-registered-device/commands/prepare',
        json={'command': 'link'})
    assert resp.status_code == 404
    assert resp.get_json()['code'] == 'device-not-found'
