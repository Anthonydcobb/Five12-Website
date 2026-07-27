"""Thread-safe registry of nearby BLE devices.

Written by the scan thread, read by Flask request threads. Entries are hidden
from the roster once stale but retained in the map, so a device that walks out
of range and back keeps its first_seen rather than looking brand new.
"""

import threading
import time

from .models import DiscoveredDevice

# Exponential smoothing factor for displayed RSSI. 0.4 settles within a few
# adverts while still damping the several-dB jitter of a raw reading.
_RSSI_ALPHA = 0.4


class Registry:
    def __init__(self, stale_after=60.0):
        self.stale_after = stale_after
        self._devices = {}
        self._lock = threading.Lock()

    def upsert(self, os_id, name, rssi, advert, now=None):
        now = time.time() if now is None else now
        with self._lock:
            existing = self._devices.get(os_id)
            if existing is None:
                self._devices[os_id] = DiscoveredDevice(
                    os_id=os_id,
                    local_name=name,
                    rssi=rssi,
                    rssi_smoothed=float(rssi),
                    first_seen=now,
                    last_seen=now,
                    advert=advert,
                )
                return self._devices[os_id]

            existing.local_name = name or existing.local_name
            existing.rssi = rssi
            existing.rssi_smoothed = (
                _RSSI_ALPHA * rssi + (1 - _RSSI_ALPHA) * existing.rssi_smoothed
            )
            existing.last_seen = now
            if advert:
                existing.advert = advert
            return existing

    def get(self, os_id):
        with self._lock:
            return self._devices.get(os_id)

    def all(self, now=None):
        """Fresh devices, strongest signal first."""
        now = time.time() if now is None else now
        with self._lock:
            fresh = [
                d for d in self._devices.values()
                if now - d.last_seen <= self.stale_after
            ]
        return sorted(fresh, key=lambda d: d.rssi_smoothed, reverse=True)

    def count(self):
        with self._lock:
            return len(self._devices)

    def clear(self):
        with self._lock:
            self._devices.clear()
