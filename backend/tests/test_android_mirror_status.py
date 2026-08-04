import pytest

from app.integrations import android_mirror


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv('FIVE12_MIRROR_TOOLS', '1')
    monkeypatch.setenv('FIVE12_MIRROR_SERIAL', 'TESTSERIAL')


def _adb(responses):
    """responses: dict mapping the first arg tuple to (ok, out, detail)."""
    def run(args, timeout, binary=False):
        return responses[tuple(args)]
    return run


def test_status_disabled_is_a_state_not_an_error(monkeypatch):
    monkeypatch.delenv('FIVE12_MIRROR_TOOLS', raising=False)
    status = android_mirror.AndroidMirrorAdapter().get_status()
    assert status['available'] is False
    assert status['alerts'] == []
    assert status['disabled'] is True
    assert 'FIVE12_MIRROR_TOOLS' in status['reason']


def test_status_online_reports_device_facts(monkeypatch, enabled):
    monkeypatch.setattr(android_mirror, '_run_adb', _adb({
        ('devices',): (True, 'List of devices attached\nTESTSERIAL\tdevice\n', ''),
        ('shell', 'wm', 'size'): (True, 'Physical size: 1080x2400\n', ''),
        ('shell', 'getprop', 'ro.product.model'): (True, 'SM-X200\n', ''),
        ('shell', 'getprop', 'ro.build.version.release'): (True, '14\n', ''),
    }))
    status = android_mirror.AndroidMirrorAdapter().get_status()
    assert status['available'] is True
    assert status['disabled'] is False
    assert status['deviceModel'] == 'SM-X200'
    assert status['androidVersion'] == '14'
    assert status['screenW'] == 1080
    assert status['screenH'] == 2400
    assert status['mirrorRunning'] is False
    assert status['lastFrameAgeSec'] is None
    assert status['alerts'] == []


def test_status_offline_is_available_false_without_disabled(monkeypatch, enabled):
    monkeypatch.setattr(android_mirror, '_run_adb', _adb({
        ('devices',): (True, 'List of devices attached\nTESTSERIAL\toffline\n', ''),
    }))
    status = android_mirror.AndroidMirrorAdapter().get_status()
    assert status['available'] is False
    assert status['disabled'] is False
    assert 'offline' in status['reason']


def test_screen_size_is_cached(monkeypatch, enabled):
    calls = []

    def run(args, timeout, binary=False):
        calls.append(tuple(args))
        return True, 'Physical size: 800x1280\n', ''

    monkeypatch.setattr(android_mirror, '_run_adb', run)
    adapter = android_mirror.AndroidMirrorAdapter()
    assert adapter.screen_size() == (800, 1280)
    assert adapter.screen_size() == (800, 1280)
    assert calls.count(('shell', 'wm', 'size')) == 1


def test_screen_size_unparseable_returns_none(monkeypatch, enabled):
    monkeypatch.setattr(
        android_mirror, '_run_adb',
        lambda args, timeout, binary=False: (True, 'nonsense\n', ''))
    assert android_mirror.AndroidMirrorAdapter().screen_size() is None
