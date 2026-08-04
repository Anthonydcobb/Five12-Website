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
