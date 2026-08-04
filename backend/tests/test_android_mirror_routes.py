import pytest

from app.integrations import android_mirror

PNG = b'\x89PNG\r\n\x1a\nFAKEBODY'


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv('FIVE12_MIRROR_TOOLS', '1')
    monkeypatch.setenv('FIVE12_MIRROR_SERIAL', 'TESTSERIAL')


def test_astera_is_registered():
    from app.integrations import ALL_DEVICE_IDS, get_adapter
    assert 'astera' in ALL_DEVICE_IDS
    assert isinstance(get_adapter('astera', False),
                      android_mirror.AndroidMirrorAdapter)


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
