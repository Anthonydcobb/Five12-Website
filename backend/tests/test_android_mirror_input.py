import pytest

from app.integrations import android_mirror


@pytest.fixture
def adapter(monkeypatch):
    monkeypatch.setenv('FIVE12_MIRROR_TOOLS', '1')
    monkeypatch.setenv('FIVE12_MIRROR_SERIAL', 'TESTSERIAL')
    a = android_mirror.AndroidMirrorAdapter()
    a._screen = (1080, 2400)
    return a


@pytest.fixture
def sent(monkeypatch):
    calls = []

    def fake_run_adb(args, timeout, binary=False):
        calls.append(tuple(args))
        return True, '', ''

    monkeypatch.setattr(android_mirror, '_run_adb', fake_run_adb)
    return calls


def test_tap_sends_input_tap(adapter, sent):
    ok, detail = adapter.send_input({'action': 'tap', 'x': 100, 'y': 200})
    assert ok is True
    assert detail == ''
    assert sent == [('shell', 'input', 'tap', '100', '200')]


def test_swipe_sends_input_swipe(adapter, sent):
    ok, _detail = adapter.send_input(
        {'action': 'swipe', 'x': 10, 'y': 20, 'x2': 30, 'y2': 40, 'durationMs': 250})
    assert ok is True
    assert sent == [('shell', 'input', 'swipe', '10', '20', '30', '40', '250')]


def test_key_sends_allowed_keycode(adapter, sent):
    ok, _detail = adapter.send_input({'action': 'key', 'keycode': 'BACK'})
    assert ok is True
    assert sent == [('shell', 'input', 'keyevent', 'KEYCODE_BACK')]


@pytest.mark.parametrize('payload', [
    {'action': 'shell', 'cmd': 'rm -rf /'},
    {'action': 'text', 'text': 'hello'},
    {'action': ''},
    {},
])
def test_unknown_actions_are_refused(adapter, sent, payload):
    ok, detail = adapter.send_input(payload)
    assert ok is False
    assert 'action' in detail
    assert sent == [], 'a refused action must not reach adb'


@pytest.mark.parametrize('payload', [
    {'action': 'tap', 'x': -1, 'y': 10},
    {'action': 'tap', 'x': 10, 'y': -1},
    {'action': 'tap', 'x': 1080, 'y': 10},
    {'action': 'tap', 'x': 10, 'y': 2400},
    {'action': 'tap', 'x': '10', 'y': 10},
    {'action': 'tap', 'x': 10.5, 'y': 10},
    {'action': 'tap', 'x': True, 'y': 10},
    {'action': 'tap', 'y': 10},
])
def test_bad_coordinates_are_refused(adapter, sent, payload):
    ok, detail = adapter.send_input(payload)
    assert ok is False
    assert 'coordinate' in detail
    assert sent == []


def test_unknown_keycode_is_refused(adapter, sent):
    ok, detail = adapter.send_input({'action': 'key', 'keycode': 'POWER'})
    assert ok is False
    assert 'keycode' in detail
    assert sent == []


def test_input_refused_when_screen_size_unknown(monkeypatch, sent):
    monkeypatch.setenv('FIVE12_MIRROR_TOOLS', '1')
    monkeypatch.setenv('FIVE12_MIRROR_SERIAL', 'TESTSERIAL')
    a = android_mirror.AndroidMirrorAdapter()
    monkeypatch.setattr(a, 'screen_size', lambda: None)
    ok, detail = a.send_input({'action': 'tap', 'x': 1, 'y': 1})
    assert ok is False
    assert 'screen size' in detail
    assert sent == []


def test_gate_off_refuses_input_and_spawns_nothing(monkeypatch):
    monkeypatch.delenv('FIVE12_MIRROR_TOOLS', raising=False)

    def boom(*args, **kwargs):
        raise AssertionError('subprocess spawned with the gate off')

    monkeypatch.setattr(android_mirror.subprocess, 'run', boom)
    ok, detail = android_mirror.AndroidMirrorAdapter().send_input(
        {'action': 'tap', 'x': 1, 'y': 1})
    assert ok is False
    assert 'FIVE12_MIRROR_TOOLS' in detail


def test_rate_limit_trips(monkeypatch, adapter, sent):
    clock = [0.0]
    monkeypatch.setattr(android_mirror.time, 'monotonic', lambda: clock[0])
    for _ in range(android_mirror.MAX_TAPS_PER_SECOND):
        ok, _detail = adapter.send_input({'action': 'tap', 'x': 1, 'y': 1})
        assert ok is True
    ok, detail = adapter.send_input({'action': 'tap', 'x': 1, 'y': 1})
    assert ok is False
    assert 'rate' in detail
    assert len(sent) == android_mirror.MAX_TAPS_PER_SECOND

    clock[0] = 1.5
    ok, _detail = adapter.send_input({'action': 'tap', 'x': 1, 'y': 1})
    assert ok is True, 'the window must slide, not latch'
