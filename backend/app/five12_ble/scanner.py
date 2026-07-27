"""BLE scan service — owns the bleak event loop and feeds the registry.

Follows the daemon-thread pattern of app/scanner.py (the ARP sweep), with one
guard that module does not need: only ONE process may own the Bluetooth
adapter. Two workers redundantly ARP-pinging is merely wasteful; two contending
for one radio is broken.

bleak is imported lazily inside _run_loop so this module — and every test that
touches handle_advertisement — works without the dependency installed.
"""

import logging
import os
import tempfile
import threading

from .advertisement import PLATFORM_TIMOTWO, decode_manufacturer_data, is_timotwo_service
from .constants import ACCEPTED_COMPANY_IDS
from .registry import Registry
from .sim import sim_advertisements

log = logging.getLogger(__name__)

SCAN_RESTART_DELAY = 5.0
SIM_POLL_INTERVAL = 2.0
# Bounded so a wedged scan thread delays a restart rather than hanging it.
STOP_JOIN_TIMEOUT = 5.0
_LOCK_PATH = os.path.join(tempfile.gettempdir(), 'five12-ble-adapter.lock')
# Byte 0 is the lock itself; the PID lives past it. Windows locks are
# mandatory, so a PID stored *inside* the locked byte would be unreadable by
# exactly the processes that want to know who owns the adapter.
_PID_OFFSET = 1


def _lock_fd(fd):
    """Take an exclusive advisory lock on an open descriptor, or raise OSError.

    The kernel drops this lock however the owning process ends — clean exit,
    crash, or kill — so a lock can never go stale and there is nothing to time
    out and steal. The platform module is imported here, like bleak, because
    only one of the two exists on any given machine.
    """
    if os.name == 'nt':
        import msvcrt
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_fd(fd):
    if os.name == 'nt':
        import msvcrt
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)


class BleScanService:
    def __init__(self, sim=False, stale_after=60.0):
        self.sim = sim
        self.registry = Registry(stale_after=stale_after)
        self._thread = None
        self._stop = threading.Event()
        self._running = False
        self._adapter_available = sim
        self._last_error = None
        self._lock_handle = None
        # The scan thread's own asyncio loop, so routes can submit device
        # operations to the ONE loop already driving the adapter instead of
        # opening a second one (see `loop` property below). None whenever no
        # scan thread is actively running that loop.
        self._loop = None

    # ── advertisement handling (pure w.r.t. bleak, hence directly testable) ──
    def handle_advertisement(self, os_id, name, rssi, service_uuids,
                             manufacturer_data, now=None):
        """Filter one advertisement and record it if it is TimoTwo evidence.

        Accepts either signal independently: some stacks drop service UUIDs
        from the advertisement while still carrying manufacturer data.
        """
        service_uuids = service_uuids or []
        manufacturer_data = manufacturer_data or {}

        by_service = any(is_timotwo_service(u) for u in service_uuids)

        advert, by_mfr = None, False
        for company_id, payload in manufacturer_data.items():
            if company_id not in ACCEPTED_COMPANY_IDS:
                continue
            advert = decode_manufacturer_data(company_id, payload)
            by_mfr = advert['platform'] == PLATFORM_TIMOTWO
            break

        if not (by_service or by_mfr):
            return None

        if advert is None:
            advert = decode_manufacturer_data(0, b'')
        advert = dict(advert)

        evidence = list(advert.get('evidence') or [])
        if by_service and 'service-uuid' not in evidence:
            evidence.insert(0, 'service-uuid')
        advert['evidence'] = evidence
        # Service-UUID match alone is sufficient platform evidence.
        advert['platform'] = PLATFORM_TIMOTWO
        advert['product'] = None

        return self.registry.upsert(os_id, name, rssi, advert, now=now)

    # ── sim ──
    def poll_sim(self, now=None):
        for os_id, name, rssi, advert in sim_advertisements(now=now):
            self.registry.upsert(os_id, name, rssi, advert, now=now)

    # ── lifecycle ──
    def _acquire_adapter_lock(self):
        """Exclusive OS-level lock so only one Five12 process scans. Under
        gunicorn every worker runs this module; only one may own the radio.

        Ownership is whatever the kernel says about this descriptor — never the
        file's existence or its mtime. Those only ever described a process that
        *had* started, not one that is still alive.
        """
        if self.sim:
            return True
        try:
            fd = os.open(_LOCK_PATH, os.O_CREAT | os.O_RDWR)
        except OSError:
            return False
        try:
            _lock_fd(fd)
        except OSError:
            os.close(fd)
            return False
        except ImportError:
            # Neither msvcrt nor fcntl exists on this platform. Same posture
            # as bleak missing: we cannot honestly claim adapter ownership,
            # so decline it here rather than let the ImportError climb out
            # of start() uncaught and take app startup down with it.
            os.close(fd)
            self._last_error = 'lock-mechanism-unavailable'
            log.error('BLE: no OS lock mechanism available on this platform; not scanning')
            return False
        self._lock_handle = fd
        # Diagnostics only — it never decides ownership. Padded to a fixed
        # width so a shorter PID cannot leave a previous owner's digits behind.
        try:
            os.lseek(fd, _PID_OFFSET, os.SEEK_SET)
            os.write(fd, b'%-16d' % os.getpid())
        except OSError:
            pass
        return True

    def _release_adapter_lock(self):
        """Closing the descriptor is what releases the lock.

        The file is deliberately left on disk: unlinking a path we can no
        longer prove we own is how one process deletes another's live lock. An
        orphaned empty file costs nothing, and an orphaned lock is impossible.
        """
        fd, self._lock_handle = self._lock_handle, None
        if fd is None:
            return
        try:
            _unlock_fd(fd)
        except OSError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass

    def start(self):
        if self._running:
            return
        if self._thread is not None and self._thread.is_alive():
            # stop() left this reference in place because the thread outlived
            # its join timeout — it is still the legitimate owner of the
            # adapter. Spawning a second thread here would be the same
            # two-owners-of-one-radio failure the lock exists to prevent, so
            # this guard does not lean on the lock at all to catch it.
            self._last_error = 'previous-scan-thread-still-running'
            log.warning('BLE: refusing to start; previous scan thread has not exited yet')
            return
        if not self._acquire_adapter_lock():
            # Don't clobber a more specific reason _acquire_adapter_lock may
            # have already recorded (e.g. an unsupported platform).
            if self._last_error != 'lock-mechanism-unavailable':
                self._last_error = 'not-owner'
                log.info('BLE: another process owns the adapter; not scanning')
            return
        # A fresh Event per thread. Clearing a shared one would un-stop a
        # previous thread that had not yet noticed it was told to exit.
        stop = threading.Event()
        self._stop = stop
        thread = threading.Thread(
            target=self._sim_loop if self.sim else self._run_loop,
            args=(stop,),
            name='five12-ble-scan',
            daemon=True,
        )
        self._thread = thread
        self._running = True
        thread.start()

    def stop(self):
        thread = self._thread
        self._stop.set()
        self._running = False
        # Join before releasing: the old thread must be gone before a later
        # start() can hand the adapter to a new one.
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=STOP_JOIN_TIMEOUT)
            if thread.is_alive():
                # Still running past our bounded wait — blocked in bleak's
                # async teardown, or behind a hung radio driver. It is still
                # the legitimate owner of the adapter: releasing the lock now
                # would let an immediate start() acquire a fresh one and spawn
                # a SECOND live scan thread while this one keeps running —
                # exactly the "two owners of one radio" failure this lock
                # exists to prevent. Leave the lock (and this reference, so
                # start() can see the thread is still alive) in place; either
                # _retire releases it when the thread eventually exits, or the
                # process dying does.
                log.warning(
                    'BLE: scan thread did not stop within %.1fs; keeping the '
                    'adapter lock held', STOP_JOIN_TIMEOUT)
                return
        self._thread = None
        self._release_adapter_lock()

    def status(self):
        return {
            'running': self._running,
            'sim': self.sim,
            'adapterAvailable': self._adapter_available,
            'deviceCount': len(self.registry.all()),
            'lastError': self._last_error,
        }

    @property
    def loop(self):
        """The running bleak event loop, or None if no scan thread owns one.

        Routes use this — via asyncio.run_coroutine_threadsafe — to run a BLE
        operation ON this loop rather than opening a second one that would
        race the scan loop for the same adapter. `self._loop` is set only
        while `_run_loop` actually has a live loop object (see below) and is
        cleared before that loop is closed, so callers never get handed a
        closed loop to submit work to.
        """
        return self._loop

    # ── loops ──
    def _sim_loop(self, stop):
        while not stop.is_set():
            self.poll_sim()
            stop.wait(SIM_POLL_INTERVAL)

    def _run_loop(self, stop):
        """Own a bleak event loop for the life of the process.

        `stop` is this thread's own Event, not self._stop: a stop()/start()
        pair replaces the latter, and a thread must keep obeying the signal it
        was started with rather than one a successor cleared.

        bleak is imported here, not at module scope, so the pure modules and
        their tests never require the dependency.
        """
        import asyncio

        try:
            from bleak import BleakScanner
        except ImportError:
            self._last_error = 'adapter-unavailable'
            self._adapter_available = False
            self._retire(stop)
            log.error('BLE: bleak is not installed; scanning disabled')
            return

        def _on_advert(device, advertisement_data):
            try:
                self.handle_advertisement(
                    os_id=str(device.address),
                    name=advertisement_data.local_name or device.name,
                    rssi=advertisement_data.rssi,
                    service_uuids=advertisement_data.service_uuids,
                    manufacturer_data=advertisement_data.manufacturer_data,
                )
            except Exception as exc:   # one bad advert must not kill the scan
                log.debug('BLE: bad advertisement ignored: %s', exc)

        async def _scan_forever():
            while not stop.is_set():
                try:
                    async with BleakScanner(detection_callback=_on_advert):
                        self._adapter_available = True
                        self._last_error = None
                        while not stop.is_set():
                            await asyncio.sleep(0.5)
                except Exception as exc:
                    self._adapter_available = False
                    self._last_error = 'adapter-unavailable'
                    log.error('BLE scan error: %s', exc)
                    await asyncio.sleep(SCAN_RESTART_DELAY)

        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_scan_forever())
        finally:
            # Clear the published loop BEFORE closing it: once close() runs,
            # nothing may be submitted to it, so a route thread must never be
            # able to observe this loop after that point.
            self._loop = None
            loop.close()
            self._retire(stop)

    def _retire(self, stop):
        """Tear down on the scan thread's way out, but only if this thread is
        still the current one — a join that timed out could otherwise let a
        dead thread clear the flags and drop the lock of its successor."""
        if self._stop is not stop:
            return
        self._running = False
        self._release_adapter_lock()


# ── module-level service registry (one per sim flag, like get_adapter) ───────
_services = {}
_services_lock = threading.Lock()


def get_scan_service(sim=False):
    key = bool(sim)
    with _services_lock:
        if key not in _services:
            _services[key] = BleScanService(sim=key)
        return _services[key]


def start_ble_service(app):
    """Called from the app factory when ENABLE_BLE_TOOLS is set."""
    from ..integrations import sim_enabled
    service = get_scan_service(sim_enabled())
    service.start()
    app.logger.info('BLE scan service started (sim=%s)', service.sim)
    return service
