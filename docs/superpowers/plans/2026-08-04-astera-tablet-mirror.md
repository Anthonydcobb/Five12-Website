# Astera Tablet Mirror Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a dedicated Android tablet's screen inside the Five12 Devices tab and let the operator tap and drag it from the PC.

**Architecture:** A new `AndroidMirrorAdapter` implements the existing synchronous `DeviceAdapter` interface, so the tab appears automatically from `ALL_DEVICE_IDS` with one `PANELS` entry on the frontend. Frames come from polling `adb exec-out screencap -p`; input goes out through a closed allowlist of `adb shell input` commands. Every subprocess call in the feature funnels through one function, which is the only thing tests need to poison.

**Tech Stack:** Python 3.12, Flask 3 (WSGI, synchronous), `subprocess` from the standard library, React 19, Vite, Vitest + Testing Library, axios.

**Spec:** `docs/superpowers/specs/2026-08-04-astera-tablet-mirror-design.md`

## Global Constraints

- **Gate:** `FIVE12_MIRROR_TOOLS`, default **off**, in **both** config classes in `backend/config.py`. Gate off means **no subprocess is spawned at all**.
- **The device serial comes from `FIVE12_MIRROR_SERIAL`, never from request input.** A request must not be able to name a target. This mirrors the invariant `backend/app/device_routes.py` states in its own docstring.
- **Closed adb command allowlist:** exactly `screencap`, `input tap`, `input swipe`, `input keyevent`. No path to arbitrary `adb shell`.
- Coordinates validated as **integers within the cached screen bounds**.
- `get_status()` returns a **camelCase** dict and must include `available` and `alerts`.
- This is **not** the removed ART7 telemetry adapter. The module docstring must point at `docs/hardware-tests/astera-art7-stage-a.md` so no future reader concludes the falsified hypothesis was revived.
- **Do not touch** Astera *fixture inventory* in `backend/app/fixture_seed.py`, `backend/seed_fixtures.py`, `backend/app/integrations/stardust.py`. Those are DMX fixtures (Titan, Hyperion, AX-series), unrelated to this work.
- Backend tests run on the app interpreter: `C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe`. Not whatever `python` is on `PATH` — they are different installs with different packages.
- Panel copy must state that **live video and smooth dragging are coming**, so 2–3 fps reads as a known stage rather than a defect.

---

## File Structure

| Path | Responsibility |
|---|---|
| `backend/app/integrations/android_mirror.py` | **New.** The whole adb boundary: gate, serial, the single `_run_adb` chokepoint, `AndroidMirrorAdapter` with detect/status/frame/input. |
| `backend/app/integrations/__init__.py` | **Modify.** Two lines: class map entry and `ALL_DEVICE_IDS`. |
| `backend/app/device_routes.py` | **Modify.** Two device-specific routes, siblings of the existing `/stardust/*` ones. |
| `backend/config.py` | **Modify.** `ENABLE_MIRROR_TOOLS` in both config classes. |
| `app/src/components/devices/AsteraMirrorPanel.jsx` | **New.** Self-contained panel — its own polling, its own primitives. `Dot`, `Tile`, `useDevice` in `Devices.jsx` are module-scope and **not exported**; do not try to import them. |
| `app/src/pages/Devices.jsx` | **Modify.** Two lines: import and `PANELS` entry. |
| `backend/tests/test_android_mirror_gate.py` | **New.** Gate and serial contract. |
| `backend/tests/test_android_mirror_status.py` | **New.** detect/get_status shapes. |
| `backend/tests/test_android_mirror_frame.py` | **New.** Capture, single-flight, staleness. |
| `backend/tests/test_android_mirror_input.py` | **New.** Allowlist, coordinate validation, rate limit. |
| `app/src/components/devices/AsteraMirrorPanel.test.jsx` | **New.** State rendering and click math. |

---

### Task 1: adb boundary, gate, and detect()

**Files:**
- Create: `backend/app/integrations/android_mirror.py`
- Modify: `backend/config.py` (both config classes)
- Test: `backend/tests/test_android_mirror_gate.py`

**Interfaces:**
- Consumes: `DeviceAdapter`, `HistoryRing` from `backend/app/integrations/__init__.py`. Base `__init__` sets `self.history`; subclasses are constructed as `cls(sim=bool(sim))`, so `__init__` must accept `sim` and call `super().__init__()`.
- Produces: `AndroidMirrorAdapter`, `_run_adb(args, timeout, binary=False) -> (ok, stdout, detail)`, `_tools_enabled() -> bool`, `_serial() -> str|None`, `DISABLED_DETAIL`, `NO_SERIAL_DETAIL`, `ADB_TIMEOUT`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_android_mirror_gate.py`:

```python
"""The gate is the load-bearing safety property: with FIVE12_MIRROR_TOOLS
unset, this feature must not spawn a process. subprocess.run is poisoned so a
single call fails the suite."""
import pytest

from app.integrations import android_mirror


@pytest.fixture
def poisoned(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError('subprocess was spawned with the gate off')
    monkeypatch.setattr(android_mirror.subprocess, 'run', boom)


def test_gate_off_detect_spawns_nothing(monkeypatch, poisoned):
    monkeypatch.delenv('FIVE12_MIRROR_TOOLS', raising=False)
    monkeypatch.setenv('FIVE12_MIRROR_SERIAL', 'TESTSERIAL')
    result = android_mirror.AndroidMirrorAdapter().detect()
    assert result['found'] is False
    assert result['address'] is None
    assert 'FIVE12_MIRROR_TOOLS' in result['detail']


def test_gate_explicitly_zero_spawns_nothing(monkeypatch, poisoned):
    monkeypatch.setenv('FIVE12_MIRROR_TOOLS', '0')
    monkeypatch.setenv('FIVE12_MIRROR_SERIAL', 'TESTSERIAL')
    assert android_mirror.AndroidMirrorAdapter().detect()['found'] is False


def test_gate_on_without_serial_spawns_nothing(monkeypatch, poisoned):
    monkeypatch.setenv('FIVE12_MIRROR_TOOLS', '1')
    monkeypatch.delenv('FIVE12_MIRROR_SERIAL', raising=False)
    result = android_mirror.AndroidMirrorAdapter().detect()
    assert result['found'] is False
    assert 'FIVE12_MIRROR_SERIAL' in result['detail']


def test_serial_is_never_read_from_a_caller(monkeypatch):
    """The adapter exposes no way to pass a serial in. If this ever fails,
    a request could name a target — the exact thing the security model forbids."""
    import inspect
    monkeypatch.setenv('FIVE12_MIRROR_SERIAL', 'FROMCONFIG')
    sig = inspect.signature(android_mirror.AndroidMirrorAdapter.__init__)
    assert set(sig.parameters) <= {'self', 'sim'}
    assert android_mirror._serial() == 'FROMCONFIG'


def test_detect_reports_online_device(monkeypatch):
    monkeypatch.setenv('FIVE12_MIRROR_TOOLS', '1')
    monkeypatch.setenv('FIVE12_MIRROR_SERIAL', 'TESTSERIAL')
    calls = []

    def fake_run(args, timeout, binary=False):
        calls.append(args)
        return True, 'List of devices attached\nTESTSERIAL\tdevice\n', ''

    monkeypatch.setattr(android_mirror, '_run_adb', fake_run)
    result = android_mirror.AndroidMirrorAdapter().detect()
    assert result['found'] is True
    assert result['address'] == 'TESTSERIAL'
    assert calls == [['devices']]


def test_detect_reports_offline_device(monkeypatch):
    monkeypatch.setenv('FIVE12_MIRROR_TOOLS', '1')
    monkeypatch.setenv('FIVE12_MIRROR_SERIAL', 'TESTSERIAL')
    monkeypatch.setattr(
        android_mirror, '_run_adb',
        lambda args, timeout, binary=False: (True, 'List of devices attached\nTESTSERIAL\toffline\n', ''))
    result = android_mirror.AndroidMirrorAdapter().detect()
    assert result['found'] is False
    assert 'offline' in result['detail']
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
'C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe' -m pytest backend/tests/test_android_mirror_gate.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'app.integrations.android_mirror'`

- [ ] **Step 3: Write the implementation**

Create `backend/app/integrations/android_mirror.py`:

```python
"""Android tablet mirror — screen capture and input injection over adb.

This is NOT the removed ART7 telemetry adapter. That one asserted facts about
an AsteraNext HTTP server which does not exist; see
docs/hardware-tests/astera-art7-stage-a.md for the bench record that killed it.
This adapter reports the state of a link we own and can verify: whether the
configured tablet is paired, online, and serving frames.

Security contract:
  * FIVE12_MIRROR_TOOLS unset/0 (default): NO subprocess is spawned. Ever.
  * The device serial comes from FIVE12_MIRROR_SERIAL and is never taken from
    request input, so a request cannot name a target. Same invariant as
    device_routes.py states in its own docstring.
  * Exactly four adb invocations are reachable: `devices`, `exec-out screencap`,
    `shell wm size`, and `shell input <tap|swipe|keyevent>`. There is no path to
    arbitrary `adb shell`.

Environment:
  FIVE12_MIRROR_TOOLS=1      master switch, default off
  FIVE12_MIRROR_SERIAL=...   adb serial of the tablet (`adb devices`)
  FIVE12_ADB_PATH=...        adb binary, default 'adb' from PATH
"""

import os
import subprocess
import threading
import time
from collections import deque

from . import DeviceAdapter

ADB_TIMEOUT = 6
CAPTURE_TIMEOUT = 3   # was 8; see the frame-rate note above
MAX_TAPS_PER_SECOND = 8

DISABLED_DETAIL = 'tablet mirror disabled — set FIVE12_MIRROR_TOOLS=1 to enable'
NO_SERIAL_DETAIL = ('set FIVE12_MIRROR_SERIAL to the adb serial of the tablet '
                    '(see `adb devices`)')
NO_ADB_DETAIL = 'adb binary not found — set FIVE12_ADB_PATH'


def _tools_enabled():
    return os.getenv('FIVE12_MIRROR_TOOLS', '0') == '1'


def _serial():
    return os.getenv('FIVE12_MIRROR_SERIAL', '').strip() or None


def _adb_path():
    return os.getenv('FIVE12_ADB_PATH', 'adb')


def _run_adb(args, timeout, binary=False):
    """The ONLY place this module spawns a process. `args` is built by this
    module from constants and validated integers — never from request input.

    -> (ok: bool, stdout: str|bytes, detail: str)
    """
    serial = _serial()
    cmd = [_adb_path()]
    if serial:
        cmd += ['-s', serial]
    cmd += list(args)
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except FileNotFoundError:
        return False, b'' if binary else '', NO_ADB_DETAIL
    except subprocess.TimeoutExpired:
        return False, b'' if binary else '', f'adb timed out after {timeout}s'
    if proc.returncode != 0:
        err = (proc.stderr or b'').decode('utf-8', 'replace').strip()
        return False, b'' if binary else '', err or f'adb exited {proc.returncode}'
    if binary:
        return True, proc.stdout, ''
    return True, (proc.stdout or b'').decode('utf-8', 'replace'), ''


class AndroidMirrorAdapter(DeviceAdapter):
    id = 'astera'
    name = 'Astera (tablet mirror)'

    def __init__(self, sim=False):
        super().__init__()
        self.sim = bool(sim)
        self._screen = None
        self._last_frame = None
        self._last_frame_at = None
        self._last_reason = None
        self._capture_lock = threading.Lock()
        self._tap_times = deque()

    def detect(self):
        if not _tools_enabled():
            return {'found': False, 'address': None, 'detail': DISABLED_DETAIL}
        serial = _serial()
        if not serial:
            return {'found': False, 'address': None, 'detail': NO_SERIAL_DETAIL}
        ok, out, detail = _run_adb(['devices'], ADB_TIMEOUT)
        if not ok:
            return {'found': False, 'address': serial, 'detail': detail}
        state = None
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[0] == serial:
                state = parts[1]
                break
        if state == 'device':
            return {'found': True, 'address': serial, 'detail': 'tablet online'}
        if state is None:
            return {'found': False, 'address': serial,
                    'detail': 'tablet not in `adb devices` — is Wireless debugging on?'}
        return {'found': False, 'address': serial, 'detail': f'tablet {state}'}
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
'C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe' -m pytest backend/tests/test_android_mirror_gate.py -v
```
Expected: PASS, 6 tests.

- [ ] **Step 5: Add the config gate**

In `backend/config.py`, add to **both** `DevelopmentConfig` and `DesktopConfig`, immediately after each class's `ENABLE_BLE_WRITE` line:

```python
    # Gates the Android tablet mirror. OFF by default: this feature executes
    # processes, so it stays dark on machines that do not need it. With this
    # unset/0 no subprocess is spawned at all -- see
    # app/integrations/android_mirror.py. Set FIVE12_MIRROR_TOOLS=1.
    ENABLE_MIRROR_TOOLS = os.getenv("FIVE12_MIRROR_TOOLS", "0") == "1"
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/integrations/android_mirror.py backend/tests/test_android_mirror_gate.py backend/config.py
git commit -m "feat(mirror): adb boundary, gate, and device detection"
```

---

### Task 2: get_status() and screen size

**Files:**
- Modify: `backend/app/integrations/android_mirror.py`
- Test: `backend/tests/test_android_mirror_status.py`

**Interfaces:**
- Consumes: `AndroidMirrorAdapter`, `_run_adb`, `ADB_TIMEOUT` from Task 1.
- Produces: `AndroidMirrorAdapter.get_status() -> dict`, `AndroidMirrorAdapter.screen_size() -> tuple[int,int]|None`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_android_mirror_status.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
'C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe' -m pytest backend/tests/test_android_mirror_status.py -v
```
Expected: FAIL — `AttributeError: 'AndroidMirrorAdapter' object has no attribute 'screen_size'`

- [ ] **Step 3: Write the implementation**

Add to `backend/app/integrations/android_mirror.py`, inside `AndroidMirrorAdapter`:

```python
    def screen_size(self):
        """(width, height) in device pixels, read once and cached. Coordinate
        validation depends on this, so an unparseable answer must read as
        unknown rather than as a guess."""
        if self._screen is not None:
            return self._screen
        ok, out, _detail = _run_adb(['shell', 'wm', 'size'], ADB_TIMEOUT)
        if not ok:
            return None
        for token in out.split():
            if 'x' in token:
                w, _sep, h = token.partition('x')
                if w.isdigit() and h.isdigit():
                    self._screen = (int(w), int(h))
                    return self._screen
        return None

    def _getprop(self, prop):
        ok, out, _detail = _run_adb(['shell', 'getprop', prop], ADB_TIMEOUT)
        return out.strip() if ok and out.strip() else None

    def get_status(self):
        if not _tools_enabled():
            return {'available': False, 'disabled': True, 'alerts': [],
                    'reason': DISABLED_DETAIL}
        if not _serial():
            return {'available': False, 'disabled': False, 'alerts': [],
                    'reason': NO_SERIAL_DETAIL}
        found = self.detect()
        if not found['found']:
            self.history.record({'online': 0})
            return {'available': False, 'disabled': False, 'alerts': [],
                    'reason': found['detail']}
        size = self.screen_size()
        age = None
        if self._last_frame_at is not None:
            age = round(time.monotonic() - self._last_frame_at, 1)
        self.history.record({'online': 1})
        return {
            'available': True,
            'disabled': False,
            'alerts': [],
            'deviceModel': self._getprop('ro.product.model'),
            'androidVersion': self._getprop('ro.build.version.release'),
            'screenW': size[0] if size else None,
            'screenH': size[1] if size else None,
            'mirrorRunning': self._last_frame is not None,
            'lastFrameAgeSec': age,
        }
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
'C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe' -m pytest backend/tests/test_android_mirror_status.py -v
```
Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/integrations/android_mirror.py backend/tests/test_android_mirror_status.py
git commit -m "feat(mirror): status contract and cached screen size"
```

---

### Task 3: frame capture, single-flight, staleness

**Files:**
- Modify: `backend/app/integrations/android_mirror.py`
- Test: `backend/tests/test_android_mirror_frame.py`

**Interfaces:**
- Consumes: everything from Tasks 1–2.
- Produces: `AndroidMirrorAdapter.get_frame() -> (png: bytes|None, age_sec: float|None, detail: str)`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_android_mirror_frame.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
'C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe' -m pytest backend/tests/test_android_mirror_frame.py -v
```
Expected: FAIL — `AttributeError: 'AndroidMirrorAdapter' object has no attribute 'get_frame'`

- [ ] **Step 3: Write the implementation**

Add to `AndroidMirrorAdapter`:

```python
    def _age(self):
        if self._last_frame_at is None:
            return None
        return round(time.monotonic() - self._last_frame_at, 1)

    def get_frame(self):
        """-> (png bytes|None, age in seconds|None, detail).

        Single-flight: a capture already running returns the cached frame
        rather than spawning another. Without this a slow tablet plus a ~350ms
        poll interval stacks subprocesses until something falls over.

        A failed capture never discards the last good frame — it ages it, so
        the panel can show a stale badge instead of going blank.
        """
        if not _tools_enabled():
            return None, None, DISABLED_DETAIL
        if not _serial():
            return None, None, NO_SERIAL_DETAIL

        if not self._capture_lock.acquire(blocking=False):
            return self._last_frame, self._age(), 'capture already in progress'
        try:
            ok, out, detail = _run_adb(
                ['exec-out', 'screencap', '-p'], CAPTURE_TIMEOUT, binary=True)
            if not ok:
                self._last_reason = detail
                return self._last_frame, self._age(), detail
            if not out:
                self._last_reason = 'screencap returned an empty image'
                return self._last_frame, self._age(), self._last_reason
            self._last_frame = out
            self._last_frame_at = time.monotonic()
            self._last_reason = None
            return self._last_frame, 0.0, ''
        finally:
            self._capture_lock.release()
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
'C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe' -m pytest backend/tests/test_android_mirror_frame.py -v
```
Expected: PASS, 6 tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/integrations/android_mirror.py backend/tests/test_android_mirror_frame.py
git commit -m "feat(mirror): frame capture with single-flight and staleness"
```

---

### Task 4: input allowlist, coordinate validation, rate limit

**Files:**
- Modify: `backend/app/integrations/android_mirror.py`
- Test: `backend/tests/test_android_mirror_input.py`

**Interfaces:**
- Consumes: everything from Tasks 1–3.
- Produces: `AndroidMirrorAdapter.send_input(payload: dict) -> (ok: bool, detail: str)`. Accepted payload shapes: `{'action': 'tap', 'x': int, 'y': int}`, `{'action': 'swipe', 'x': int, 'y': int, 'x2': int, 'y2': int, 'durationMs': int}`, `{'action': 'key', 'keycode': str}` where keycode is one of `BACK`, `HOME`, `APP_SWITCH`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_android_mirror_input.py`:

```python
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
    monkeypatch.setattr(
        android_mirror, '_run_adb',
        lambda args, timeout, binary=False: (calls.append(tuple(args)), (True, '', ''))[1])
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
'C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe' -m pytest backend/tests/test_android_mirror_input.py -v
```
Expected: FAIL — `AttributeError: 'AndroidMirrorAdapter' object has no attribute 'send_input'`

- [ ] **Step 3: Write the implementation**

Add near the top of `android_mirror.py`, after `MAX_TAPS_PER_SECOND`:

```python
# The COMPLETE set of key events this module may send. Anything not here is
# unreachable by construction, including POWER and anything text-related.
ALLOWED_KEYCODES = {'BACK': 'KEYCODE_BACK',
                    'HOME': 'KEYCODE_HOME',
                    'APP_SWITCH': 'KEYCODE_APP_SWITCH'}

MAX_SWIPE_MS = 5000
```

Add to `AndroidMirrorAdapter`:

```python
    def _rate_ok(self):
        now = time.monotonic()
        while self._tap_times and now - self._tap_times[0] >= 1.0:
            self._tap_times.popleft()
        if len(self._tap_times) >= MAX_TAPS_PER_SECOND:
            return False
        self._tap_times.append(now)
        return True

    def _valid_point(self, payload, xk, yk, bounds):
        w, h = bounds
        x, y = payload.get(xk), payload.get(yk)
        for value, limit in ((x, w), (y, h)):
            if not isinstance(value, int) or isinstance(value, bool):
                return None
            if value < 0 or value >= limit:
                return None
        return x, y

    def send_input(self, payload):
        """-> (ok, detail). `payload` is request-supplied and therefore
        untrusted: the action is matched against a closed set, coordinates must
        be integers inside the cached screen bounds, and no field of it ever
        becomes part of an adb argument without passing one of those checks.
        The device serial is not read from it at all."""
        if not _tools_enabled():
            return False, DISABLED_DETAIL
        if not _serial():
            return False, NO_SERIAL_DETAIL
        if not isinstance(payload, dict):
            return False, 'unknown action'

        action = payload.get('action')
        if action not in ('tap', 'swipe', 'key'):
            return False, f'unknown action {action!r}'

        if action == 'key':
            keycode = ALLOWED_KEYCODES.get(payload.get('keycode'))
            if keycode is None:
                return False, f'keycode {payload.get("keycode")!r} not allowed'
            if not self._rate_ok():
                return False, 'rate limit exceeded'
            ok, _out, detail = _run_adb(
                ['shell', 'input', 'keyevent', keycode], ADB_TIMEOUT)
            return ok, detail

        bounds = self.screen_size()
        if bounds is None:
            return False, 'screen size unknown — cannot validate coordinates'

        start = self._valid_point(payload, 'x', 'y', bounds)
        if start is None:
            return False, 'coordinate out of bounds or not an integer'

        if action == 'tap':
            if not self._rate_ok():
                return False, 'rate limit exceeded'
            ok, _out, detail = _run_adb(
                ['shell', 'input', 'tap', str(start[0]), str(start[1])], ADB_TIMEOUT)
            return ok, detail

        end = self._valid_point(payload, 'x2', 'y2', bounds)
        if end is None:
            return False, 'coordinate out of bounds or not an integer'
        duration = payload.get('durationMs', 200)
        if not isinstance(duration, int) or isinstance(duration, bool):
            return False, 'coordinate out of bounds or not an integer'
        duration = max(1, min(duration, MAX_SWIPE_MS))
        if not self._rate_ok():
            return False, 'rate limit exceeded'
        ok, _out, detail = _run_adb(
            ['shell', 'input', 'swipe', str(start[0]), str(start[1]),
             str(end[0]), str(end[1]), str(duration)], ADB_TIMEOUT)
        return ok, detail
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
'C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe' -m pytest backend/tests/test_android_mirror_input.py -v
```
Expected: PASS, 21 tests (parametrized cases counted individually).

- [ ] **Step 5: Commit**

```bash
git add backend/app/integrations/android_mirror.py backend/tests/test_android_mirror_input.py
git commit -m "feat(mirror): input allowlist, coordinate validation, rate limit"
```

---

### Task 5: registry and routes

**Files:**
- Modify: `backend/app/integrations/__init__.py:129-149`
- Modify: `backend/app/device_routes.py`
- Test: `backend/tests/test_android_mirror_routes.py`

**Interfaces:**
- Consumes: `AndroidMirrorAdapter` from Tasks 1–4.
- Produces: `GET /api/devices/astera/frame` → `image/png` with header `X-Frame-Age-Ms`, or `503` with JSON `{'reason': str}`. `POST /api/devices/astera/input` → `{'ok': bool, 'detail': str}`, `400` when refused.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_android_mirror_routes.py`:

```python
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
```

Note: `client` is the existing fixture at `backend/tests/conftest.py:15` (it depends on the `app` fixture at line 6). Verified — do not add a competing fixture.

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
'C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe' -m pytest backend/tests/test_android_mirror_routes.py -v
```
Expected: FAIL — `assert 'astera' in ALL_DEVICE_IDS`

- [ ] **Step 3: Wire the registry**

In `backend/app/integrations/__init__.py`, inside `get_adapter`, add the import and map entry after the Cintenna lines:

```python
    from .android_mirror import AndroidMirrorAdapter
```

```python
        'cintenna': CintennaAdapter,
        'astera': AndroidMirrorAdapter,
    }
```

And extend the tuple:

```python
ALL_DEVICE_IDS = ('starlink', 'bolero', 'stardust', 'cintenna', 'astera')
```

- [ ] **Step 4: Add the routes**

In `backend/app/device_routes.py`, change the import line to add `make_response`:

```python
from flask import Blueprint, jsonify, make_response, request
```

Append these routes at the end of the file:

```python
@devices.get('/astera/frame')
def astera_frame():
    """One PNG of the tablet screen. The device is chosen by configuration,
    never by the request — see integrations/android_mirror.py."""
    adapter = get_adapter('astera', sim_enabled(request.args))
    png, age, detail = adapter.get_frame()
    if png is None:
        return jsonify({'reason': detail}), 503
    resp = make_response(png)
    resp.headers['Content-Type'] = 'image/png'
    resp.headers['Cache-Control'] = 'no-store'
    resp.headers['X-Frame-Age-Ms'] = str(int((age or 0) * 1000))
    return resp


@devices.post('/astera/input')
def astera_input():
    """Tap / swipe / key on the configured tablet. The body is untrusted: the
    adapter matches the action against a closed set and validates coordinates
    against the cached screen bounds. No field of it selects a device."""
    adapter = get_adapter('astera', sim_enabled(request.args))
    ok, detail = adapter.send_input(request.get_json(silent=True) or {})
    return jsonify({'ok': ok, 'detail': detail}), (200 if ok else 400)
```

- [ ] **Step 5: Run the test to verify it passes**

Run:
```bash
'C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe' -m pytest backend/tests/test_android_mirror_routes.py -v
```
Expected: PASS, 6 tests.

- [ ] **Step 6: Run the whole backend suite**

Run:
```bash
'C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe' -m pytest -q backend/tests
```
Expected: all pass. Baseline before this feature was **565 passed, 7 skipped**; the 7 skips are pre-existing BLE adapter-lock tests and are not caused by this work.

- [ ] **Step 7: Commit**

```bash
git add backend/app/integrations/__init__.py backend/app/device_routes.py backend/tests/test_android_mirror_routes.py
git commit -m "feat(mirror): register the adapter and add frame/input routes"
```

---

### Task 6: the panel — states before pixels

**Files:**
- Create: `app/src/components/devices/AsteraMirrorPanel.jsx`
- Modify: `app/src/pages/Devices.jsx:11-12` (import), `app/src/pages/Devices.jsx:496-501` (`PANELS`)
- Test: `app/src/components/devices/AsteraMirrorPanel.test.jsx`

**Interfaces:**
- Consumes: `GET /api/devices/astera/status` returning the Task 2 shape.
- Produces: default-exported `AsteraMirrorPanel` React component taking no props, matching how `PANELS[tab]` renders it as `<Panel />`.

**Important:** `Dot`, `Tile`, `AlertChips`, `Sparkline` and `useDevice` are module-scope in `Devices.jsx` and **not exported**. This panel is self-contained and imports none of them.

- [ ] **Step 1: Write the failing test**

Create `app/src/components/devices/AsteraMirrorPanel.test.jsx`:

```jsx
import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import axios from 'axios';
import AsteraMirrorPanel from './AsteraMirrorPanel';

vi.mock('axios');

function statusOf(overrides) {
  return { data: { available: true, disabled: false, alerts: [], deviceModel: 'SM-X200',
                   androidVersion: '14', screenW: 1080, screenH: 2400,
                   mirrorRunning: true, lastFrameAgeSec: 0.2, ...overrides } };
}

beforeEach(() => {
  global.URL.createObjectURL = vi.fn(() => 'blob:fake');
  global.URL.revokeObjectURL = vi.fn();
  axios.post.mockResolvedValue({ data: { ok: true, detail: '' } });
});

afterEach(() => { vi.clearAllMocks(); });

describe('AsteraMirrorPanel', () => {
  it('names the env var when the gate is off', async () => {
    axios.get.mockResolvedValue(statusOf({ available: false, disabled: true,
                                           reason: 'tablet mirror disabled — set FIVE12_MIRROR_TOOLS=1 to enable' }));
    render(<AsteraMirrorPanel />);
    expect(await screen.findByText(/FIVE12_MIRROR_TOOLS/)).toBeInTheDocument();
  });

  it('distinguishes disabled from offline', async () => {
    axios.get.mockResolvedValue(statusOf({ available: false, disabled: false,
                                           reason: 'tablet offline' }));
    render(<AsteraMirrorPanel />);
    expect(await screen.findByText(/tablet offline/i)).toBeInTheDocument();
    expect(screen.queryByText(/FIVE12_MIRROR_TOOLS/)).not.toBeInTheDocument();
  });

  it('offers reconnect when offline and not when disabled', async () => {
    axios.get.mockResolvedValue(statusOf({ available: false, disabled: false,
                                           reason: 'tablet offline' }));
    const { unmount } = render(<AsteraMirrorPanel />);
    expect(await screen.findByRole('button', { name: /reconnect/i })).toBeInTheDocument();
    unmount();

    axios.get.mockResolvedValue(statusOf({ available: false, disabled: true,
                                           reason: 'disabled — set FIVE12_MIRROR_TOOLS=1' }));
    render(<AsteraMirrorPanel />);
    await screen.findByText(/FIVE12_MIRROR_TOOLS/);
    expect(screen.queryByRole('button', { name: /reconnect/i })).not.toBeInTheDocument();
  });

  it('shows the device facts when available', async () => {
    axios.get.mockResolvedValue(statusOf({}));
    render(<AsteraMirrorPanel />);
    expect(await screen.findByText(/SM-X200/)).toBeInTheDocument();
    expect(screen.getByText(/1080\s*×\s*2400/)).toBeInTheDocument();
  });

  it('states that live video is coming', async () => {
    axios.get.mockResolvedValue(statusOf({}));
    render(<AsteraMirrorPanel />);
    expect(await screen.findByText(/coming soon/i)).toBeInTheDocument();
  });

  it('marks a stale frame with its age', async () => {
    axios.get.mockResolvedValue(statusOf({ lastFrameAgeSec: 12.4 }));
    render(<AsteraMirrorPanel />);
    await waitFor(() => expect(screen.getByText(/stale/i)).toBeInTheDocument());
    expect(screen.getByText(/12\.4s/)).toBeInTheDocument();
  });

  it('does not mark a fresh frame stale', async () => {
    axios.get.mockResolvedValue(statusOf({ lastFrameAgeSec: 0.3 }));
    render(<AsteraMirrorPanel />);
    await screen.findByText(/SM-X200/);
    expect(screen.queryByText(/stale/i)).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cd app && npx vitest run src/components/devices/AsteraMirrorPanel.test.jsx
```
Expected: FAIL — cannot resolve `./AsteraMirrorPanel`.

- [ ] **Step 3: Write the panel**

Create `app/src/components/devices/AsteraMirrorPanel.jsx`:

```jsx
import React, { useState, useEffect, useRef, useCallback } from 'react';
import axios from 'axios';

const STATUS_MS = 3000;
const FRAME_MS = 400;
const STALE_AFTER_SEC = 3;

export default function AsteraMirrorPanel() {
  const [status, setStatus] = useState(null);
  const [frameUrl, setFrameUrl] = useState(null);
  const [frameError, setFrameError] = useState(null);
  const urlRef = useRef(null);

  const pollStatus = useCallback(async () => {
    try {
      const { data } = await axios.get('/api/devices/astera/status');
      setStatus(data);
    } catch {
      setStatus({ available: false, disabled: false, reason: 'backend unreachable' });
    }
  }, []);

  useEffect(() => {
    let alive = true;
    const tick = async () => { if (alive) await pollStatus(); };
    tick();
    const i = setInterval(tick, STATUS_MS);
    return () => { alive = false; clearInterval(i); };
  }, [pollStatus]);

  const live = status?.available === true;

  useEffect(() => {
    if (!live) return undefined;
    let alive = true;
    const grab = async () => {
      try {
        const resp = await axios.get('/api/devices/astera/frame',
                                     { responseType: 'blob' });
        if (!alive) return;
        const next = URL.createObjectURL(resp.data);
        if (urlRef.current) URL.revokeObjectURL(urlRef.current);
        urlRef.current = next;
        setFrameUrl(next);
        setFrameError(null);
      } catch (err) {
        if (alive) setFrameError(err?.response?.data?.reason || 'frame unavailable');
      }
    };
    grab();
    const i = setInterval(grab, FRAME_MS);
    return () => {
      alive = false;
      clearInterval(i);
      if (urlRef.current) { URL.revokeObjectURL(urlRef.current); urlRef.current = null; }
    };
  }, [live]);

  const reconnect = async () => { await pollStatus(); };

  if (!status) {
    return <div className="text-[10px] font-mono text-text-muted py-6 px-2">connecting…</div>;
  }

  if (!status.available) {
    return (
      <div className="text-[10px] font-mono text-text-muted py-6 px-2 space-y-2">
        <div>{status.reason || 'tablet unavailable'}</div>
        {!status.disabled && (
          <button onClick={reconnect}
            className="px-2 py-1 border border-[var(--color-border)] rounded-sm hover:border-brand">
            Reconnect
          </button>
        )}
      </div>
    );
  }

  const age = status.lastFrameAgeSec;
  const stale = typeof age === 'number' && age > STALE_AFTER_SEC;

  return (
    <div className="px-2 py-3 space-y-2">
      <div className="text-[10px] font-mono text-text-muted flex gap-3 flex-wrap items-center">
        <span>{status.deviceModel || 'tablet'}</span>
        <span>Android {status.androidVersion || '?'}</span>
        <span>{status.screenW} × {status.screenH}</span>
        {stale && (
          <span className="text-warn">stale — last frame {age}s ago</span>
        )}
      </div>

      <div className="text-[9px] font-mono text-text-muted">
        still frames at 2–3 fps · live video and smooth dragging coming soon
      </div>

      {frameError && (
        <div className="text-[10px] font-mono text-text-muted">{frameError}</div>
      )}

      {frameUrl && (
        <img src={frameUrl} alt="tablet screen"
             className={'border border-[var(--color-border)] max-h-[70vh] w-auto ' +
                        (stale ? 'opacity-60' : '')} />
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
cd app && npx vitest run src/components/devices/AsteraMirrorPanel.test.jsx
```
Expected: PASS, 7 tests.

- [ ] **Step 5: Wire it into Devices.jsx**

Add the import after the `CintennaPanel` import (line 11):

```jsx
import AsteraMirrorPanel from '../components/devices/AsteraMirrorPanel'
```

Add the `PANELS` entry:

```jsx
  cintenna: CintennaPanel,
  astera: AsteraMirrorPanel,
};
```

- [ ] **Step 6: Commit**

```bash
git add app/src/components/devices/AsteraMirrorPanel.jsx app/src/components/devices/AsteraMirrorPanel.test.jsx app/src/pages/Devices.jsx
git commit -m "feat(mirror): Astera tab panel with honest connection states"
```

---

### Task 7: click and drag control

**Files:**
- Modify: `app/src/components/devices/AsteraMirrorPanel.jsx`
- Test: `app/src/components/devices/AsteraMirrorPanel.test.jsx`

**Interfaces:**
- Consumes: `POST /api/devices/astera/input` from Task 5; `screenW` / `screenH` from Task 2.
- Produces: no new exports. Adds pointer handlers on the `<img>` and Back / Home / Recents buttons.

- [ ] **Step 1: Write the failing test**

Append to `app/src/components/devices/AsteraMirrorPanel.test.jsx`, inside the existing `describe`:

```jsx
  function mockImageBox(el, box) {
    vi.spyOn(el, 'getBoundingClientRect').mockReturnValue({
      left: box.left, top: box.top, width: box.width, height: box.height,
      right: box.left + box.width, bottom: box.top + box.height, x: box.left, y: box.top,
    });
  }

  it('converts a click to device pixels at a non-1:1 display scale', async () => {
    axios.get.mockResolvedValue(statusOf({}));
    render(<AsteraMirrorPanel />);
    const img = await screen.findByAltText('tablet screen');
    // displayed at 270x600 for a 1080x2400 device — exactly quarter scale
    mockImageBox(img, { left: 10, top: 20, width: 270, height: 600 });

    img.dispatchEvent(new PointerEvent('pointerdown',
      { clientX: 10 + 135, clientY: 20 + 300, bubbles: true }));
    img.dispatchEvent(new PointerEvent('pointerup',
      { clientX: 10 + 135, clientY: 20 + 300, bubbles: true }));

    await waitFor(() => expect(axios.post).toHaveBeenCalled());
    expect(axios.post).toHaveBeenCalledWith('/api/devices/astera/input',
      { action: 'tap', x: 540, y: 1200 });
  });

  it('sends a swipe when the pointer moves far enough', async () => {
    axios.get.mockResolvedValue(statusOf({}));
    render(<AsteraMirrorPanel />);
    const img = await screen.findByAltText('tablet screen');
    mockImageBox(img, { left: 0, top: 0, width: 270, height: 600 });

    img.dispatchEvent(new PointerEvent('pointerdown', { clientX: 10, clientY: 10, bubbles: true }));
    img.dispatchEvent(new PointerEvent('pointerup', { clientX: 100, clientY: 200, bubbles: true }));

    await waitFor(() => expect(axios.post).toHaveBeenCalled());
    const [, body] = axios.post.mock.calls[0];
    expect(body.action).toBe('swipe');
    expect(body).toMatchObject({ x: 40, y: 40, x2: 400, y2: 800 });
    expect(typeof body.durationMs).toBe('number');
  });

  it('sends allowed keycodes from the nav buttons', async () => {
    axios.get.mockResolvedValue(statusOf({}));
    render(<AsteraMirrorPanel />);
    (await screen.findByRole('button', { name: /back/i })).click();
    await waitFor(() => expect(axios.post).toHaveBeenCalledWith(
      '/api/devices/astera/input', { action: 'key', keycode: 'BACK' }));
  });

  it('has no controls at all when the tablet is offline', async () => {
    axios.get.mockResolvedValue(statusOf({ available: false, disabled: false,
                                           reason: 'tablet offline' }));
    render(<AsteraMirrorPanel />);
    await screen.findByText(/tablet offline/i);
    expect(screen.queryByRole('button', { name: /back/i })).not.toBeInTheDocument();
    expect(screen.queryByAltText('tablet screen')).not.toBeInTheDocument();
  });
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cd app && npx vitest run src/components/devices/AsteraMirrorPanel.test.jsx
```
Expected: FAIL — `axios.post` never called; there are no pointer handlers yet.

- [ ] **Step 3: Add control to the panel**

In `AsteraMirrorPanel.jsx`, add this constant beside the others:

```jsx
const TAP_SLOP_PX = 8;
```

Add inside the component, after `reconnect`:

```jsx
  const imgRef = useRef(null);
  const downRef = useRef(null);

  const toDevice = (e) => {
    const el = imgRef.current;
    if (!el || !status?.screenW || !status?.screenH) return null;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) return null;
    const x = Math.round(((e.clientX - r.left) / r.width) * status.screenW);
    const y = Math.round(((e.clientY - r.top) / r.height) * status.screenH);
    const clamp = (v, hi) => Math.max(0, Math.min(v, hi - 1));
    return { x: clamp(x, status.screenW), y: clamp(y, status.screenH) };
  };

  const send = async (body) => {
    try { await axios.post('/api/devices/astera/input', body); }
    catch (err) { setFrameError(err?.response?.data?.detail || 'input refused'); }
  };

  const onPointerDown = (e) => {
    downRef.current = { pt: toDevice(e), clientX: e.clientX, clientY: e.clientY,
                        at: Date.now() };
  };

  const onPointerUp = (e) => {
    const down = downRef.current;
    downRef.current = null;
    const up = toDevice(e);
    if (!down || !down.pt || !up) return;
    const moved = Math.hypot(e.clientX - down.clientX, e.clientY - down.clientY);
    if (moved < TAP_SLOP_PX) {
      send({ action: 'tap', x: up.x, y: up.y });
    } else {
      send({ action: 'swipe', x: down.pt.x, y: down.pt.y, x2: up.x, y2: up.y,
             durationMs: Math.max(50, Math.min(Date.now() - down.at, 5000)) });
    }
  };
```

Replace the `<img>` block and add the nav row:

```jsx
      {frameUrl && (
        <img ref={imgRef} src={frameUrl} alt="tablet screen"
             onPointerDown={onPointerDown} onPointerUp={onPointerUp}
             draggable={false}
             className={'border border-[var(--color-border)] max-h-[70vh] w-auto touch-none select-none cursor-pointer ' +
                        (stale ? 'opacity-60' : '')} />
      )}

      <div className="flex gap-2">
        {[['Back', 'BACK'], ['Home', 'HOME'], ['Recents', 'APP_SWITCH']].map(([label, keycode]) => (
          <button key={keycode}
            onClick={() => send({ action: 'key', keycode })}
            className="text-[10px] font-mono px-2 py-1 border border-[var(--color-border)] rounded-sm hover:border-brand">
            {label}
          </button>
        ))}
      </div>
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
cd app && npx vitest run src/components/devices/AsteraMirrorPanel.test.jsx
```
Expected: PASS, 11 tests.

- [ ] **Step 5: Run the full frontend suite and build**

Run:
```bash
cd app && npx vitest run && npm run build
```
Expected: all pass; the build emits only the pre-existing large-chunk warning. Frontend baseline before this feature was **74 passed across 7 files**.

- [ ] **Step 6: Commit**

```bash
git add app/src/components/devices/AsteraMirrorPanel.jsx app/src/components/devices/AsteraMirrorPanel.test.jsx
git commit -m "feat(mirror): tap, swipe and navigation control"
```

---

## Manual verification

Automated tests never touch a real tablet. Before handoff, with a paired device:

1. `FIVE12_MIRROR_TOOLS=1` and `FIVE12_MIRROR_SERIAL=<serial from adb devices>`, restart the backend.
2. Open Devices. The **Astera (tablet mirror)** card appears with a green dot.
3. The tablet screen renders. Measure the real frame rate and record it — the spec's 2–3 fps is an estimate from the S21, not a measurement from a tablet.
4. Tap a control in AsteraNext. It responds.
5. Turn Wireless debugging off on the tablet. Within ~3 s the panel says offline and offers Reconnect; the last frame is marked stale with an age, not left looking live.
6. Turn it back on, press Reconnect, confirm frames resume.

Record the results in `docs/coordination/active/claude--astera-tablet-mirror.md` under **Checks run**, with evidence level **verified on actual gear**.

---

## Self-review

**Spec coverage.** Every section maps to a task: the seam and adapter → Tasks 1, 2, 5; security model layers 3 and 4 → Tasks 1, 4, 5; the gate → Task 1; frame pipeline with single-flight and staleness → Task 3; control mapping → Tasks 4, 7; error states → Task 6; testing → every task; the "coming soon" copy → Task 6. Layers 1 and 2 of the security model (loopback bind, adb pairing) are existing properties of the environment, not code this plan writes — no task, correctly.

**Deliberate omissions, flagged rather than hidden.**
- `get_history()` is inherited from `DeviceAdapter` and fed by `self.history.record({'online': 0|1})` in Task 2. No separate task; the base class already returns it via `/api/devices/astera/history`.
- Sim mode. Every sibling adapter has `_sim_status()`. This one does not: a simulated mirror would have to fabricate a screenshot, and a fake picture of a lighting console is exactly the kind of plausible-but-false artifact the Astera bench record warns about. `get_adapter('astera', sim=True)` returns the real adapter, which reports unavailable without hardware. **If a reviewer wants sim parity, that is a design change, not an oversight.**
- The three numbers the spec left unpinned are now pinned: `FRAME_MS = 400`, `CAPTURE_TIMEOUT = 8`, `MAX_TAPS_PER_SECOND = 8`. They are first guesses; step 3 of manual verification is where they get corrected against real hardware.

**Type consistency.** `get_frame()` returns a 3-tuple `(png, age, detail)` in Tasks 3 and 5. `send_input(payload)` returns `(ok, detail)` in Tasks 4 and 5. Status keys `available`, `disabled`, `reason`, `deviceModel`, `androidVersion`, `screenW`, `screenH`, `mirrorRunning`, `lastFrameAgeSec` are identical across Tasks 2, 5 and 6. Keycodes `BACK` / `HOME` / `APP_SWITCH` match between `ALLOWED_KEYCODES` in Task 4 and the nav buttons in Task 7.

**Fixture check.** Task 5's route tests use the `client` fixture, confirmed to exist at `backend/tests/conftest.py:15`, depending on `app` at line 6. No new fixture is needed.

**What this plan cannot know.** The frame rate against a real tablet, whether 2–3 fps is usable for colour work, and whether AsteraNext lays out acceptably on a large screen. All three are settled by the manual verification section and by using it, not by any test written here.
