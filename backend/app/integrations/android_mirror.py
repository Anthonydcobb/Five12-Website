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
CAPTURE_TIMEOUT = 8
MAX_TAPS_PER_SECOND = 8

# The COMPLETE set of key events this module may send. Anything not here is
# unreachable by construction, including POWER and anything text-related.
ALLOWED_KEYCODES = {'BACK': 'KEYCODE_BACK',
                    'HOME': 'KEYCODE_HOME',
                    'APP_SWITCH': 'KEYCODE_APP_SWITCH'}

MAX_SWIPE_MS = 5000

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
            keycode_value = payload.get('keycode')
            # Only a str may be looked up — dict.get hashes its key, and a
            # request-supplied list/dict for 'keycode' would otherwise raise
            # TypeError instead of producing the intended refusal.
            keycode = (ALLOWED_KEYCODES.get(keycode_value)
                       if isinstance(keycode_value, str) else None)
            if keycode is None:
                return False, f'keycode {keycode_value!r} not allowed'
            if not self._rate_ok():
                return False, 'rate limit exceeded'
            ok, _out, detail = _run_adb(
                ['shell', 'input', 'keyevent', keycode], ADB_TIMEOUT)
            return ok, detail

        # Rate-limit BEFORE any adb work, including screen_size(). screen_size()
        # only caches on success — on failure (offline tablet) it re-spawns an
        # adb subprocess (6s timeout) on every call. If it ran ahead of
        # _rate_ok(), a flood of requests against an offline tablet would
        # spawn unboundedly many adb processes with no limiter ever reached.
        if not self._rate_ok():
            return False, 'rate limit exceeded'

        bounds = self.screen_size()
        if bounds is None:
            return False, 'screen size unknown — cannot validate coordinates'

        start = self._valid_point(payload, 'x', 'y', bounds)
        if start is None:
            return False, 'coordinate out of bounds or not an integer'

        if action == 'tap':
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
        ok, _out, detail = _run_adb(
            ['shell', 'input', 'swipe', str(start[0]), str(start[1]),
             str(end[0]), str(end[1]), str(duration)], ADB_TIMEOUT)
        return ok, detail
