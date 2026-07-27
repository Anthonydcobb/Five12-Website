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
import time

from .advertisement import PLATFORM_TIMOTWO, decode_manufacturer_data, is_timotwo_service
from .constants import ACCEPTED_COMPANY_IDS
from .registry import Registry
from .sim import sim_advertisements

log = logging.getLogger(__name__)

SCAN_RESTART_DELAY = 5.0
SIM_POLL_INTERVAL = 2.0
_LOCK_PATH = os.path.join(tempfile.gettempdir(), 'five12-ble-adapter.lock')


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
        gunicorn every worker runs this module; only one may own the radio."""
        if self.sim:
            return True
        try:
            fd = os.open(_LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_RDWR)
        except FileExistsError:
            # A stale lock from a killed process would block scanning forever.
            try:
                if time.time() - os.path.getmtime(_LOCK_PATH) > 300:
                    os.unlink(_LOCK_PATH)
                    return self._acquire_adapter_lock()
            except OSError:
                pass
            return False
        except OSError:
            return False
        self._lock_handle = fd
        os.write(fd, str(os.getpid()).encode())
        return True

    def _release_adapter_lock(self):
        if self._lock_handle is not None:
            try:
                os.close(self._lock_handle)
                os.unlink(_LOCK_PATH)
            except OSError:
                pass
            self._lock_handle = None

    def start(self):
        if self._running:
            return
        if not self._acquire_adapter_lock():
            self._last_error = 'not-owner'
            log.info('BLE: another process owns the adapter; not scanning')
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._sim_loop if self.sim else self._run_loop,
            name='five12-ble-scan',
            daemon=True,
        )
        self._running = True
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._running = False
        self._release_adapter_lock()

    def status(self):
        return {
            'running': self._running,
            'sim': self.sim,
            'adapterAvailable': self._adapter_available,
            'deviceCount': len(self.registry.all()),
            'lastError': self._last_error,
        }

    # ── loops ──
    def _sim_loop(self):
        while not self._stop.is_set():
            self.poll_sim()
            self._stop.wait(SIM_POLL_INTERVAL)

    def _run_loop(self):
        """Own a bleak event loop for the life of the process.

        bleak is imported here, not at module scope, so the pure modules and
        their tests never require the dependency.
        """
        import asyncio

        try:
            from bleak import BleakScanner
        except ImportError:
            self._last_error = 'adapter-unavailable'
            self._adapter_available = False
            self._running = False
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
            while not self._stop.is_set():
                try:
                    async with BleakScanner(detection_callback=_on_advert):
                        self._adapter_available = True
                        self._last_error = None
                        while not self._stop.is_set():
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
            loop.close()
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
