"""Dataclasses shared across the BLE package.

Identity note: `os_id` is whatever bleak reports for the peripheral. On Windows
this is an OS-level handle, and the peripheral may use a resolvable private
address that rotates — the captured unit reports address resolution supported
(0x2AA6). Treat os_id as best-effort identity within a session, never as a
stable key equivalent to an Ethernet MAC.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class DiscoveredDevice:
    """A radio seen in a passive scan. Advertisement data only — no GATT."""
    os_id: str
    local_name: Optional[str]
    rssi: int
    rssi_smoothed: float
    first_seen: float
    last_seen: float
    advert: dict
    # Advertisements seen from this radio. No consumer yet — it exists so the
    # same-key upsert race is falsifiable: incrementing it is a compound
    # read-modify-write, so the concurrency test can prove Registry's lock is
    # load-bearing rather than merely present. Deliberately absent from
    # to_dict(); that key set is the HTTP API surface.
    update_count: int = 0

    def to_dict(self):
        return {
            'osId': self.os_id,
            'localName': self.local_name,
            'rssi': self.rssi,
            'rssiSmoothed': round(self.rssi_smoothed, 1),
            'firstSeen': self.first_seen,
            'lastSeen': self.last_seen,
            'platform': self.advert.get('platform'),
            'product': self.advert.get('product'),
            'hardwareId': self.advert.get('hardwareId'),
            'estaManufacturerId': self.advert.get('estaManufacturerId'),
            'modelId': self.advert.get('modelId'),
            'rawManufacturerData': self.advert.get('rawManufacturerData'),
            'evidence': self.advert.get('evidence', []),
        }
