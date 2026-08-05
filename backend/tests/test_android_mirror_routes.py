import pytest

from app.integrations import android_mirror

PNG = b'\x89PNG\r\n\x1a\nFAKEBODY'


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv('FIVE12_MIRROR_TOOLS', '1')
    monkeypatch.setenv('FIVE12_MIRROR_SERIAL', 'TESTSERIAL')


def _drop_astera_from_registry():
    from app.integrations import _registry, _registry_lock
    with _registry_lock:
        for key in [k for k in _registry if k[0] == 'astera']:
            del _registry[key]


@pytest.fixture
def fresh_astera():
    """The adapter registry is process-wide, so the status TTL cache and the
    getprop cache would otherwise leak between route tests."""
    _drop_astera_from_registry()
    yield
    _drop_astera_from_registry()


def test_astera_is_registered():
    from app.integrations import ALL_DEVICE_IDS, get_adapter
    assert 'astera' in ALL_DEVICE_IDS
    assert isinstance(get_adapter('astera', False),
                      android_mirror.AndroidMirrorAdapter)


def test_sim_query_does_not_mint_a_second_astera_adapter(fresh_astera):
    """`_tap_times`, `_capture_lock` and the status cache are all
    per-instance. If ?sim=1 minted a second instance, a client alternating
    between the two would get 2x the rate limit and two concurrent
    screencaps — exactly the stacking single-flight exists to prevent."""
    from app.integrations import get_adapter
    assert get_adapter('astera', True) is get_adapter('astera', False)
    assert get_adapter('astera', True).sim is False


def test_sim_capable_adapters_still_get_their_own_sim_instance():
    """The normalisation must be driven by the adapter declaring it, not by
    a special case — no sibling adapter's behaviour may change."""
    from app.integrations import get_adapter
    for device_id in ('starlink', 'bolero', 'stardust', 'cintenna'):
        real = get_adapter(device_id, False)
        simulated = get_adapter(device_id, True)
        assert real is not simulated, f'{device_id} lost its separate sim instance'
        assert simulated.sim is True
        assert real.sim is False


def test_status_route_key_set_is_the_declared_contract(client, monkeypatch,
                                                       enabled, fresh_astera):
    """Backend tests assert adapter dicts and frontend tests assert against a
    hand-written fixture, so a rename in the adapter can silently break the
    stale badge with every test still green. This pins the wire contract.

    If this fails because you added a key on purpose: add it to
    android_mirror.STATUS_KEYS and to the statusOf() fixture in
    app/src/components/devices/AsteraMirrorPanel.test.jsx."""
    monkeypatch.setattr(android_mirror, '_run_adb', lambda args, timeout, binary=False: {
        ('devices',): (True, 'List of devices attached\nTESTSERIAL\tdevice\n', ''),
        ('shell', 'wm', 'size'): (True, 'Physical size: 1080x2400\n', ''),
        ('shell', 'getprop', 'ro.product.model'): (True, 'SM-X200\n', ''),
        ('shell', 'getprop', 'ro.build.version.release'): (True, '14\n', ''),
    }[tuple(args)])

    resp = client.get('/api/devices/astera/status')
    assert resp.status_code == 200
    assert set(resp.get_json()) == set(android_mirror.WIRE_STATUS_KEYS)


def test_status_route_shape_is_the_same_when_unavailable(client, monkeypatch,
                                                         enabled, fresh_astera):
    """One shape for every state, so 'is this key missing or is it null?'
    never becomes a question the panel has to answer."""
    monkeypatch.setattr(android_mirror, '_run_adb',
                        lambda args, timeout, binary=False: (True, '', 'no device'))
    resp = client.get('/api/devices/astera/status')
    assert set(resp.get_json()) == set(android_mirror.WIRE_STATUS_KEYS)


def test_status_route_reports_that_sim_was_requested_and_not_honoured(
        client, monkeypatch, enabled, fresh_astera):
    """FIVE12_DEVICE_SIM=1 is the documented way to demo the Devices page
    without hardware. This adapter has no sim mode by deliberate design, so
    with sim on it drives the REAL tablet while every sibling panel
    fabricates. The operator has to be able to see that."""
    monkeypatch.setattr(android_mirror, '_run_adb',
                        lambda args, timeout, binary=False: (True, '', 'no device'))

    plain = client.get('/api/devices/astera/status').get_json()
    assert plain['simIgnored'] is False

    _drop_astera_from_registry()
    asked = client.get('/api/devices/astera/status?sim=1').get_json()
    assert asked['simIgnored'] is True


def test_sibling_status_routes_gain_no_sim_ignored_key(client):
    """Only adapters that decline sim carry the flag, so nothing else on the
    Devices page changes shape."""
    resp = client.get('/api/devices/starlink/status?sim=1')
    assert resp.status_code == 200
    assert 'simIgnored' not in resp.get_json()


def test_frame_route_returns_png(client, monkeypatch, enabled):
    monkeypatch.setattr(
        android_mirror.AndroidMirrorAdapter, 'get_frame',
        lambda self: (PNG, 0.0, ''))
    resp = client.get('/api/devices/astera/frame')
    assert resp.status_code == 200
    assert resp.headers['Content-Type'] == 'image/png'
    assert resp.headers['X-Frame-Age-Ms'] == '0'
    assert resp.data == PNG


def test_frame_route_503s_with_a_reason_when_there_is_no_frame(client, monkeypatch):
    monkeypatch.setattr(
        android_mirror.AndroidMirrorAdapter, 'get_frame',
        lambda self: (None, None, android_mirror.DISABLED_DETAIL))
    resp = client.get('/api/devices/astera/frame')
    assert resp.status_code == 503
    assert 'FIVE12_MIRROR_TOOLS' in resp.get_json()['reason']


def test_input_route_forwards_payload(client, monkeypatch, enabled):
    seen = {}

    def fake_send(self, payload):
        seen.update(payload)
        return True, ''

    monkeypatch.setattr(android_mirror.AndroidMirrorAdapter, 'send_input', fake_send)
    resp = client.post('/api/devices/astera/input',
                       json={'action': 'tap', 'x': 5, 'y': 6})
    assert resp.status_code == 200
    assert resp.get_json()['ok'] is True
    assert seen == {'action': 'tap', 'x': 5, 'y': 6}


def test_input_route_400s_on_refusal(client, monkeypatch, enabled):
    monkeypatch.setattr(
        android_mirror.AndroidMirrorAdapter, 'send_input',
        lambda self, payload: (False, 'unknown action'))
    resp = client.post('/api/devices/astera/input', json={'action': 'shell'})
    assert resp.status_code == 400
    assert resp.get_json()['detail'] == 'unknown action'


def test_input_route_ignores_any_serial_in_the_body(client, monkeypatch, enabled):
    """A request must not be able to name a target device.

    The real protection is that device_routes.py passes the hardcoded
    literal 'astera' to get_adapter — never anything from the request body.
    This spies on get_adapter (patched where device_routes.py imported it,
    not where it is defined) to prove that invariant: even a body stuffed
    with plausible-looking device-selecting fields must still resolve to
    the 'astera' adapter and reach it, unchanged.
    """
    calls = []

    class StubAdapter:
        def __init__(self):
            self.seen = None

        def send_input(self, payload):
            self.seen = payload
            return True, ''

    stub = StubAdapter()

    def fake_get_adapter(device_id, sim):
        calls.append(device_id)
        return stub

    monkeypatch.setattr('app.device_routes.get_adapter', fake_get_adapter)

    hostile_body = {'action': 'tap', 'x': 1, 'y': 1,
                     'serial': 'SOMEONE_ELSE', 'device_id': 'starlink',
                     'device': 'bolero'}
    resp = client.post('/api/devices/astera/input', json=hostile_body)

    assert calls == ['astera']
    assert resp.status_code == 200
    assert resp.get_json()['ok'] is True
    assert stub.seen == hostile_body
    # Supporting check: the serial itself only ever comes from configuration.
    assert android_mirror._serial() == 'TESTSERIAL'


def test_devices_route_includes_astera(client):
    """GET /api/devices must return an astera entry — mirrors
    test_devices_route_includes_cintenna in test_ble_adapter.py. The astera
    adapter has no sim behaviour, so with the gate off detect() reports
    not-found; this asserts presence/id only, not `found`."""
    resp = client.get('/api/devices?sim=1')
    assert resp.status_code == 200
    ids = [d['id'] for d in resp.get_json()]
    assert 'astera' in ids
