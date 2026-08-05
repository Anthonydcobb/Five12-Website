import threading

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


def test_screen_size_single_line_uses_the_physical_size(monkeypatch, enabled):
    monkeypatch.setattr(
        android_mirror, '_run_adb',
        lambda args, timeout, binary=False: (True, 'Physical size: 1080x2400\n', ''))
    assert android_mirror.AndroidMirrorAdapter().screen_size() == (1080, 2400)


def test_screen_size_prefers_the_override_line(monkeypatch, enabled):
    """`wm size` prints two lines once Settings -> Display -> Display size is
    touched, and `input tap` coordinates live in the OVERRIDE space. Taking
    the first match scales every coordinate wrong and gets taps near the
    right/bottom edge refused as out of bounds."""
    monkeypatch.setattr(
        android_mirror, '_run_adb',
        lambda args, timeout, binary=False:
            (True, 'Physical size: 1080x2400\nOverride size: 810x1800\n', ''))
    assert android_mirror.AndroidMirrorAdapter().screen_size() == (810, 1800)


def test_screen_size_ignores_a_trailing_unparseable_line(monkeypatch, enabled):
    """Last *valid* match, not last line."""
    monkeypatch.setattr(
        android_mirror, '_run_adb',
        lambda args, timeout, binary=False:
            (True, 'Physical size: 1080x2400\nOverride size: unknownxsize\n', ''))
    assert android_mirror.AndroidMirrorAdapter().screen_size() == (1080, 2400)


# --- Critical 1: the status path needs the protections the frame path has ---

def test_getprop_is_cached_for_process_life(monkeypatch, enabled):
    """ro.product.model and ro.build.version.release are immutable. Two extra
    spawns every 3s is ~28,800 over a six-hour show, per open tab."""
    calls = []

    def run(args, timeout, binary=False):
        calls.append(tuple(args))
        return {
            ('devices',): (True, 'List of devices attached\nTESTSERIAL\tdevice\n', ''),
            ('shell', 'wm', 'size'): (True, 'Physical size: 1080x2400\n', ''),
            ('shell', 'getprop', 'ro.product.model'): (True, 'SM-X200\n', ''),
            ('shell', 'getprop', 'ro.build.version.release'): (True, '14\n', ''),
        }[tuple(args)]

    monkeypatch.setattr(android_mirror, '_run_adb', run)
    clock = [0.0]
    monkeypatch.setattr(android_mirror.time, 'monotonic', lambda: clock[0])
    adapter = android_mirror.AndroidMirrorAdapter()

    for i in range(5):
        clock[0] = i * 60.0          # well past any status TTL
        assert adapter.get_status()['deviceModel'] == 'SM-X200'

    assert calls.count(('shell', 'getprop', 'ro.product.model')) == 1
    assert calls.count(('shell', 'getprop', 'ro.build.version.release')) == 1


def test_status_is_served_from_a_short_ttl_cache(monkeypatch, enabled):
    """One status call is detect() + wm size + 2x getprop, each its own
    ADB_TIMEOUT=6 subprocess. Bursts must collapse onto one probe or a wedged
    adbd takes the whole WSGI worker pool down mid-show."""
    calls = []

    def run(args, timeout, binary=False):
        calls.append(tuple(args))
        return {
            ('devices',): (True, 'List of devices attached\nTESTSERIAL\tdevice\n', ''),
            ('shell', 'wm', 'size'): (True, 'Physical size: 1080x2400\n', ''),
            ('shell', 'getprop', 'ro.product.model'): (True, 'SM-X200\n', ''),
            ('shell', 'getprop', 'ro.build.version.release'): (True, '14\n', ''),
        }[tuple(args)]

    monkeypatch.setattr(android_mirror, '_run_adb', run)
    clock = [0.0]
    monkeypatch.setattr(android_mirror.time, 'monotonic', lambda: clock[0])
    adapter = android_mirror.AndroidMirrorAdapter()

    for _ in range(8):
        assert adapter.get_status()['available'] is True
    assert calls.count(('devices',)) == 1, 'a burst must collapse onto one probe'

    # The TTL must be short enough that the panel's own 3s poll is never
    # served a cached answer.
    assert android_mirror.STATUS_TTL_SEC < 3.0
    clock[0] = 3.0
    adapter.get_status()
    assert calls.count(('devices',)) == 2, 'the cache must expire, not latch'


def test_status_cache_never_serves_a_stale_frame_age(monkeypatch, enabled):
    """The stale badge is load-bearing, so frame freshness is stamped at
    return time even when the rest of the status comes from the cache."""
    monkeypatch.setattr(android_mirror, '_run_adb', lambda args, timeout, binary=False: {
        ('devices',): (True, 'List of devices attached\nTESTSERIAL\tdevice\n', ''),
        ('shell', 'wm', 'size'): (True, 'Physical size: 1080x2400\n', ''),
        ('shell', 'getprop', 'ro.product.model'): (True, 'SM-X200\n', ''),
        ('shell', 'getprop', 'ro.build.version.release'): (True, '14\n', ''),
    }[tuple(args)])
    clock = [0.0]
    monkeypatch.setattr(android_mirror.time, 'monotonic', lambda: clock[0])
    adapter = android_mirror.AndroidMirrorAdapter()
    adapter._last_frame = b'PNG'
    adapter._last_frame_at = 0.0

    assert adapter.get_status()['lastFrameAgeSec'] == 0.0
    clock[0] = 1.0
    cached = adapter.get_status()
    assert cached['lastFrameAgeSec'] == 1.0, 'age must not be frozen in the cache'
    assert cached['mirrorRunning'] is True


def test_status_single_flight_returns_the_cache_instead_of_a_second_probe(
        monkeypatch, enabled):
    """A wedged tablet still listed as `device` answers `adb devices` but
    hangs on shell. Without single-flight, ~8 concurrent status requests each
    hold a WSGI worker and up to 4 adb children."""
    adapter = android_mirror.AndroidMirrorAdapter()
    started = threading.Event()
    release = threading.Event()
    calls = []

    def slow_run(args, timeout, binary=False):
        calls.append(tuple(args))
        started.set()
        release.wait(5)
        return {
            ('devices',): (True, 'List of devices attached\nTESTSERIAL\tdevice\n', ''),
            ('shell', 'wm', 'size'): (True, 'Physical size: 1080x2400\n', ''),
            ('shell', 'getprop', 'ro.product.model'): (True, 'SM-X200\n', ''),
            ('shell', 'getprop', 'ro.build.version.release'): (True, '14\n', ''),
        }[tuple(args)]

    monkeypatch.setattr(android_mirror, '_run_adb', slow_run)
    t = threading.Thread(target=adapter.get_status)
    t.start()
    started.wait(5)

    busy = adapter.get_status()
    assert busy['available'] is False
    assert 'in progress' in busy['reason']
    assert len(calls) == 1, 'a second probe must not be spawned'

    release.set()
    t.join(10)


def test_status_single_flight_prefers_the_previous_answer_over_a_refusal(
        monkeypatch, enabled):
    """Once there IS a cached answer, a busy call returns it rather than
    flipping the panel to offline for one tick."""
    monkeypatch.setattr(android_mirror, '_run_adb', lambda args, timeout, binary=False: {
        ('devices',): (True, 'List of devices attached\nTESTSERIAL\tdevice\n', ''),
        ('shell', 'wm', 'size'): (True, 'Physical size: 1080x2400\n', ''),
        ('shell', 'getprop', 'ro.product.model'): (True, 'SM-X200\n', ''),
        ('shell', 'getprop', 'ro.build.version.release'): (True, '14\n', ''),
    }[tuple(args)])
    clock = [0.0]
    monkeypatch.setattr(android_mirror.time, 'monotonic', lambda: clock[0])
    adapter = android_mirror.AndroidMirrorAdapter()
    assert adapter.get_status()['available'] is True

    clock[0] = 100.0                      # cache expired
    adapter._status_lock.acquire()        # pretend a probe is running
    try:
        busy = adapter.get_status()
    finally:
        adapter._status_lock.release()
    assert busy['available'] is True
    assert busy['deviceModel'] == 'SM-X200'


def test_status_gate_and_serial_checks_never_touch_the_cache(monkeypatch):
    """Turning the gate off must read as off immediately, not for up to a TTL
    after the last successful probe."""
    monkeypatch.setenv('FIVE12_MIRROR_TOOLS', '1')
    monkeypatch.setenv('FIVE12_MIRROR_SERIAL', 'TESTSERIAL')
    monkeypatch.setattr(android_mirror, '_run_adb', lambda args, timeout, binary=False: {
        ('devices',): (True, 'List of devices attached\nTESTSERIAL\tdevice\n', ''),
        ('shell', 'wm', 'size'): (True, 'Physical size: 1080x2400\n', ''),
        ('shell', 'getprop', 'ro.product.model'): (True, 'SM-X200\n', ''),
        ('shell', 'getprop', 'ro.build.version.release'): (True, '14\n', ''),
    }[tuple(args)])
    adapter = android_mirror.AndroidMirrorAdapter()
    assert adapter.get_status()['available'] is True

    monkeypatch.setenv('FIVE12_MIRROR_TOOLS', '0')
    assert adapter.get_status()['disabled'] is True


# --- Finding 4: available:true with null bounds eats every gesture ---

def test_unknown_screen_size_is_not_available(monkeypatch, enabled):
    """detect() can succeed while `wm size` is unreadable. Reporting
    available:true then renders the header as 'null x null', makes toDevice()
    return null, and every tap is silently swallowed with no request and no
    explanation."""
    monkeypatch.setattr(android_mirror, '_run_adb', lambda args, timeout, binary=False: {
        ('devices',): (True, 'List of devices attached\nTESTSERIAL\tdevice\n', ''),
        ('shell', 'wm', 'size'): (True, 'nonsense\n', ''),
        ('shell', 'getprop', 'ro.product.model'): (True, 'SM-X200\n', ''),
        ('shell', 'getprop', 'ro.build.version.release'): (True, '14\n', ''),
    }[tuple(args)])
    status = android_mirror.AndroidMirrorAdapter().get_status()
    assert status['available'] is False
    assert status['disabled'] is False
    assert 'screen size' in status['reason']
    assert status['screenW'] is None
    assert status['screenH'] is None


def test_unknown_screen_size_reason_matches_the_input_refusal(monkeypatch, enabled):
    """One sentence for one problem, on both the status and the input path."""
    monkeypatch.setattr(android_mirror, '_run_adb', lambda args, timeout, binary=False: {
        ('devices',): (True, 'List of devices attached\nTESTSERIAL\tdevice\n', ''),
        ('shell', 'wm', 'size'): (True, 'nonsense\n', ''),
    }[tuple(args)])
    adapter = android_mirror.AndroidMirrorAdapter()
    status = adapter.get_status()
    _ok, detail = adapter.send_input({'action': 'tap', 'x': 1, 'y': 1})
    assert status['reason'] == detail == android_mirror.UNKNOWN_SIZE_DETAIL
