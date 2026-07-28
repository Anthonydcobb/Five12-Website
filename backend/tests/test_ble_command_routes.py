"""The only two mutating routes in the app's Bluetooth surface. With the
write gate off they must not exist at all — a 404, not a 403."""

import pytest

from app import create_app
from app.five12_ble.sim import sim_reset


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
        assert status not in (200, 403)


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
