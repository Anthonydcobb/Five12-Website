"""Cintenna (LumenRadio TimoTwo / CRMX) adapter — read-only BLE inventory.

Unlike the Starlink, Bolero, and Stardust adapters this one does NOT talk to
its devices on demand: BLE is async and scanning is continuous, so a background
service owns the radio (see app/five12_ble/scanner.py) and this adapter is a
thin synchronous reader over its registry. No method here blocks on radio I/O.

Read-only. Configuration writes, TX Link, and RX Unlink are a later, separately
gated piece of work.
"""

from . import DeviceAdapter
from ..five12_ble.scanner import get_scan_service


class CintennaAdapter(DeviceAdapter):
    id = 'cintenna'
    name = 'Cintenna (CRMX)'

    def __init__(self, sim=False):
        super().__init__()
        self.sim = sim
        self.service = get_scan_service(sim)

    def detect(self):
        st = self.service.status()
        count = st['deviceCount']

        # Ownership/lock-mechanism failures are set by start() BEFORE the scan
        # loop ever runs, so they must be checked ahead of adapterAvailable —
        # which only flips True from inside a running loop. Otherwise a
        # losing gunicorn worker reports "no adapter" for its whole lifetime
        # when another Five12 process simply holds the radio.
        if st.get('lastError') == 'not-owner':
            return {
                'found': False,
                'address': None,
                'detail': 'another Five12 process owns the adapter',
            }
        if st.get('lastError') == 'lock-mechanism-unavailable':
            return {
                'found': False,
                'address': None,
                'detail': 'no OS-level lock available on this platform — Cintenna scanning is disabled',
            }
        if not st['adapterAvailable']:
            return {
                'found': False,
                'address': None,
                'detail': 'no Bluetooth adapter',
            }
        return {
            'found': count > 0,
            'address': None,   # BLE has no network address
            'detail': (
                f'{count} nearby' if count
                else ('scanning — none nearby' if st['running'] else 'not scanning')
            ),
        }

    def get_status(self):
        st = self.service.status()
        devices = [d.to_dict() for d in self.service.registry.all()]
        status = {
            'available': st['adapterAvailable'],
            'scanning': st['running'],
            'sim': st['sim'],
            'deviceCount': len(devices),
            'devices': devices,
            'alerts': [],
        }
        if not st['adapterAvailable']:
            status['alerts'] = [{
                'level': 'warn',
                'message': 'No Bluetooth adapter available — Cintennas cannot be discovered',
            }]
        # Passive-roster sample only: no per-device fields, no GATT data (this
        # layer never connects), just what the scan service itself knows.
        self.history.record({
            'deviceCount': status['deviceCount'],
            'scanning': status['scanning'],
            'available': status['available'],
        })
        return status
