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
    """A request must not be able to name a target device."""
    seen = {}
    monkeypatch.setattr(
        android_mirror.AndroidMirrorAdapter, 'send_input',
        lambda self, payload: (seen.update(payload), (True, ''))[1])
    client.post('/api/devices/astera/input',
                json={'action': 'tap', 'x': 1, 'y': 1, 'serial': 'SOMEONE_ELSE'})
    assert android_mirror._serial() == 'TESTSERIAL'
