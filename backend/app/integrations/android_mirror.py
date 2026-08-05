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
# One status probe is `adb devices` + `wm size` + (first time) two getprops,
# each its own ADB_TIMEOUT subprocess — so a wedged adbd can hold a WSGI
# worker for ~24s. The panel polls status every 3s, so the TTL is set just
# under that: a lone panel is never served a cached answer and stays as live
# as it was, while bursts (several open tabs, a Reconnect click landing on a
# poll, a retry storm against a half-connected tablet) collapse onto one
# probe instead of stacking workers and adb children. Frame freshness is
# stamped at return time and never served from this cache — see get_status.
STATUS_TTL_SEC = 2.0
# A screencap on the SM-T290 measures 514-644 ms over USB. 8s was ~15x that,
# so a wedged capture froze the panel for eight seconds before the stale badge
# could appear. 3s is still five times the worst observed round-trip and fails
# visibly while the operator is still looking at it.
CAPTURE_TIMEOUT = 3
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
UNKNOWN_SIZE_DETAIL = 'screen size unknown — cannot validate coordinates'

# The exact key set of GET /api/devices/astera/status, declared once. Every
# status is built from it (see _status()), so a rename here changes the wire
# and the route-level contract test catches any drift — the panel reads
# these names directly and the stale badge is load-bearing.
STATUS_KEYS = ('available', 'disabled', 'alerts', 'reason', 'deviceModel',
               'androidVersion', 'screenW', 'screenH', 'mirrorRunning',
               'lastFrameAgeSec')
# device_routes.py stamps this one: only the request knows whether sim was
# asked for, so the adapter cannot report it (see supports_sim below).
WIRE_STATUS_KEYS = STATUS_KEYS + ('simIgnored',)


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
        # Name the path actually tried: 'set FIVE12_ADB_PATH' alone leaves the
        # operator unable to tell whether the variable was read at all.
        return False, b'' if binary else '', (
            f'adb binary not found at {_adb_path()!r} — set FIVE12_ADB_PATH')
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

    # This adapter has NO sim mode, deliberately: a fabricated screenshot of
    # a lighting console is exactly the plausible-but-false artifact this
    # project's hardware record warns against (see the module docstring).
    # Declaring it here makes get_adapter() resolve ?sim=1 and ?sim=0 to the
    # same instance — one rate-limit window, one capture lock, one status
    # cache — and lets device_routes.py tell the operator that sim was asked
    # for and not honoured, instead of silently driving the real tablet.
    supports_sim = False

    def __init__(self, sim=False):
        super().__init__()
        # Always False: get_adapter() normalises it, because supports_sim is
        # False. Kept for uniformity with the sibling adapters' signature.
        self.sim = bool(sim)
        self._screen = None
        self._props = {}
        self._last_frame = None
        self._last_frame_at = None
        self._capture_lock = threading.Lock()
        self._status_lock = threading.Lock()
        self._status_cache = None        # (monotonic_at, status dict)
        self._rate_lock = threading.Lock()
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
            # The tablet is cabled, so the cable is the overwhelmingly likely
            # cause and belongs first. Naming Wireless debugging here sent the
            # operator to a setting that is meant to be OFF on this rig.
            return {'found': False, 'address': serial,
                    'detail': ('tablet not in `adb devices` — check the USB cable '
                               '(a charge-only cable powers the tablet but is '
                               'invisible to adb), that the tablet is unlocked, '
                               'and that USB debugging is on')}
        return {'found': False, 'address': serial, 'detail': f'tablet {state}'}

    def screen_size(self):
        """(width, height) in device pixels, read once and cached on success.

        Coordinate validation depends on this, so an unparseable answer must
        read as unknown rather than as a guess. Failures are deliberately NOT
        cached — a negative cache would keep the panel broken after the
        tablet came back. The status single-flight/TTL bounds the re-probing.

        `wm size` prints two lines once Settings -> Display -> Display size
        has been touched:

            Physical size: 1080x2400
            Override size: 810x1800

        `input tap` coordinates live in the OVERRIDE space, so the LAST valid
        WxH wins. Taking the first scales every coordinate wrong and gets
        taps near the right/bottom edge refused as out of bounds.
        """
        if self._screen is not None:
            return self._screen
        ok, out, _detail = _run_adb(['shell', 'wm', 'size'], ADB_TIMEOUT)
        if not ok:
            return None
        found = None
        for token in out.split():
            if 'x' in token:
                w, _sep, h = token.partition('x')
                if w.isdigit() and h.isdigit():
                    found = (int(w), int(h))
        if found is not None:
            self._screen = found
        return found

    def _getprop(self, prop):
        """Cached for process life: ro.product.model and
        ro.build.version.release are immutable, and two extra spawns every
        status poll is ~28,800 over a six-hour show, per open tab."""
        if prop in self._props:
            return self._props[prop]
        ok, out, _detail = _run_adb(['shell', 'getprop', prop], ADB_TIMEOUT)
        value = out.strip() if ok and out.strip() else None
        if value is not None:
            self._props[prop] = value
        return value

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
                return self._last_frame, self._age(), detail
            if not out:
                return (self._last_frame, self._age(),
                        'screencap returned an empty image')
            self._last_frame = out
            self._last_frame_at = time.monotonic()
            return self._last_frame, 0.0, ''
        finally:
            self._capture_lock.release()

    def _status(self, **fields):
        """Every status has the same shape, built from STATUS_KEYS, so the
        panel never has to ask whether a key is missing or merely null."""
        out = dict.fromkeys(STATUS_KEYS)
        out.update({'available': False, 'disabled': False, 'alerts': []})
        out.update(fields)
        return self._stamp_freshness(out)

    def _stamp_freshness(self, status):
        """Frame age is computed at return time, never served from the status
        cache. The stale badge is load-bearing: a frozen image that looks live
        is the failure that has someone pressing buttons at a tablet which
        stopped listening two minutes ago."""
        status['mirrorRunning'] = self._last_frame is not None
        status['lastFrameAgeSec'] = self._age()
        # dict() is shallow, so give every returned status its own alerts
        # list rather than one aliased to the cached dict.
        status['alerts'] = list(status['alerts'] or [])
        return status

    def get_status(self):
        """Single-flight + short TTL, for the same reason get_frame() has
        them. One probe is up to four ADB_TIMEOUT subprocesses, and a tablet
        that is still listed as `device` but has stopped answering shell
        (asleep, half-connected USB, wedged adbd) turns a 3s poll into ~8
        concurrent requests, each holding a WSGI worker and up to four adb
        children. On sync workers that exhausts the pool and the WHOLE
        backend stops responding mid-show, not just the mirror.
        """
        # Config checks are free and must never be served from the cache:
        # flipping the gate off has to read as off immediately.
        if not _tools_enabled():
            return self._status(disabled=True, reason=DISABLED_DETAIL)
        if not _serial():
            return self._status(reason=NO_SERIAL_DETAIL)

        cached = self._status_cache
        if cached is not None and time.monotonic() - cached[0] < STATUS_TTL_SEC:
            return self._stamp_freshness(dict(cached[1]))

        if not self._status_lock.acquire(blocking=False):
            # A probe is already running. Prefer the last answer we had over
            # blinking the panel offline for one tick.
            if cached is not None:
                return self._stamp_freshness(dict(cached[1]))
            return self._status(reason='status check already in progress')
        try:
            # Another thread may have filled the cache while we were acquiring.
            cached = self._status_cache
            if cached is not None and time.monotonic() - cached[0] < STATUS_TTL_SEC:
                return self._stamp_freshness(dict(cached[1]))
            status = self._probe_status()
            self._status_cache = (time.monotonic(), status)
            return self._stamp_freshness(dict(status))
        finally:
            self._status_lock.release()

    def _probe_status(self):
        """The adb work behind get_status(). Called under _status_lock."""
        found = self.detect()
        if not found['found']:
            self.history.record({'online': 0})
            return self._status(reason=found['detail'])

        size = self.screen_size()
        if size is None:
            # detect() can succeed while `wm size` is unreadable. Reporting
            # available:true here renders the header as 'null x null', makes
            # the panel's toDevice() return null, and every tap is swallowed
            # with no request, no error and no explanation. Unknown bounds
            # are not a live mirror — say so and let the offline state,
            # Reconnect button included, do the work.
            self.history.record({'online': 0})
            return self._status(reason=UNKNOWN_SIZE_DETAIL)

        self.history.record({'online': 1})
        return self._status(
            available=True,
            deviceModel=self._getprop('ro.product.model'),
            androidVersion=self._getprop('ro.build.version.release'),
            screenW=size[0],
            screenH=size[1],
        )

    def _rate_ok(self):
        """Atomic: an unlocked check-then-append lets two threaded requests
        both see room for the last slot and both take it."""
        with self._rate_lock:
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
            return False, UNKNOWN_SIZE_DETAIL

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
            # Its own message: reporting a bad duration as a coordinate
            # problem sends the operator looking at the wrong thing during a
            # live failure, when the coordinates were fine all along.
            return False, 'durationMs must be an integer'
        duration = max(1, min(duration, MAX_SWIPE_MS))
        ok, _out, detail = _run_adb(
            ['shell', 'input', 'swipe', str(start[0]), str(start[1]),
             str(end[0]), str(end[1]), str(duration)], ADB_TIMEOUT)
        return ok, detail
