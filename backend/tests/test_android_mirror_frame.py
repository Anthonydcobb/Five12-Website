import threading

import pytest

from app.integrations import android_mirror

PNG = b'\x89PNG\r\n\x1a\nFAKEBODY'


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv('FIVE12_MIRROR_TOOLS', '1')
    monkeypatch.setenv('FIVE12_MIRROR_SERIAL', 'TESTSERIAL')


def test_gate_off_returns_no_frame_and_spawns_nothing(monkeypatch):
    monkeypatch.delenv('FIVE12_MIRROR_TOOLS', raising=False)

    def boom(*args, **kwargs):
        raise AssertionError('subprocess spawned with the gate off')

    monkeypatch.setattr(android_mirror.subprocess, 'run', boom)
    png, age, detail = android_mirror.AndroidMirrorAdapter().get_frame()
    assert png is None
    assert age is None
    assert 'FIVE12_MIRROR_TOOLS' in detail


def test_capture_returns_png_and_zero_age(monkeypatch, enabled):
    monkeypatch.setattr(
        android_mirror, '_run_adb',
        lambda args, timeout, binary=False: (True, PNG, ''))
    png, age, detail = android_mirror.AndroidMirrorAdapter().get_frame()
    assert png == PNG
    assert age == 0.0
    assert detail == ''


def test_capture_uses_exec_out_screencap(monkeypatch, enabled):
    seen = []

    def run(args, timeout, binary=False):
        seen.append((tuple(args), binary))
        return True, PNG, ''

    monkeypatch.setattr(android_mirror, '_run_adb', run)
    android_mirror.AndroidMirrorAdapter().get_frame()
    assert seen == [(('exec-out', 'screencap', '-p'), True)]


def test_failed_capture_keeps_last_frame_and_reports_age(monkeypatch, enabled):
    adapter = android_mirror.AndroidMirrorAdapter()
    monkeypatch.setattr(
        android_mirror, '_run_adb',
        lambda args, timeout, binary=False: (True, PNG, ''))
    adapter.get_frame()

    clock = [100.0]
    monkeypatch.setattr(android_mirror.time, 'monotonic', lambda: clock[0])
    adapter._last_frame_at = 100.0
    clock[0] = 103.5
    monkeypatch.setattr(
        android_mirror, '_run_adb',
        lambda args, timeout, binary=False: (False, b'', 'device offline'))

    png, age, detail = adapter.get_frame()
    assert png == PNG, 'a failed capture must not throw away the last good frame'
    assert age == 3.5
    assert detail == 'device offline'


def test_single_flight_returns_cache_instead_of_second_capture(monkeypatch, enabled):
    adapter = android_mirror.AndroidMirrorAdapter()
    started = threading.Event()
    release = threading.Event()
    calls = []

    def slow_run(args, timeout, binary=False):
        calls.append(args)
        started.set()
        release.wait(5)
        return True, PNG, ''

    monkeypatch.setattr(android_mirror, '_run_adb', slow_run)
    t = threading.Thread(target=adapter.get_frame)
    t.start()
    started.wait(5)

    png, _age, detail = adapter.get_frame()
    assert png is None, 'no frame cached yet, so the busy call returns nothing'
    assert detail == 'capture already in progress'
    release.set()
    t.join(5)
    assert len(calls) == 1, 'a second capture must not be spawned'


def test_empty_capture_output_is_a_failure_not_a_frame(monkeypatch, enabled):
    monkeypatch.setattr(
        android_mirror, '_run_adb',
        lambda args, timeout, binary=False: (True, b'', ''))
    png, _age, detail = android_mirror.AndroidMirrorAdapter().get_frame()
    assert png is None
    assert 'empty' in detail
