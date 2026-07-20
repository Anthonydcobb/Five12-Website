"""Riedel Bolero adapter — read-only beltpack/antenna telemetry.

[VERIFIED] Bolero Standalone is configured over IP via a web UI backed by a
REST API (the third-party DECT app speaks the same API), with live WebSocket
updates carrying battery, signal, antenna status, PTP sync and temperature.

[NEEDS VERIFICATION] The exact REST endpoints and payload schemas are NOT
publicly documented — DECT reverse-engineered them. Every path/field in
ENDPOINTS/_normalize below is a PLACEHOLDER to be corrected from a real
unit's browser DevTools session (Network/WS tabs). That mapping is the
gating task; until it's done, the real adapter reports 'endpoint map
unverified' rather than guessing silently.

Read-only in v1 (the research doc's 80/20: battery board first). Writing to
a live comms system mid-show is deliberately out of scope.

Configuration: FIVE12_BOLERO_HOST=<ip-of-antenna/AP> (must be a private IP).
"""

import math
import os
import time

from . import DeviceAdapter, check_thresholds, require_private_host, tcp_reachable

# ── The single place to fix when the real API is mapped ─────────────────────
# [NEEDS VERIFICATION] placeholders — map against a real unit before trusting.
ENDPOINTS = {
    'beltpacks': '/api/beltpacks',    # roster: battery/signal/antenna/temp
    'antennas': '/api/antennas',      # antenna + PTP sync state
}
VERIFIED_AGAINST_UNIT = False   # flip to True once DevTools mapping is done

ALERT_RULES = [
    ('lowestBatteryPct', 'lt', 20, 'Beltpack battery at {value}%', 'crit'),
    ('ptpSynced', 'eq', False, 'PTP sync LOST on an antenna', 'crit'),
    ('packsOnline', 'eq', 0, 'No beltpacks online', 'warn'),
]


class BoleroAdapter(DeviceAdapter):
    id = 'bolero'
    name = 'Riedel Bolero'

    def __init__(self, sim=False):
        super().__init__()
        self.sim = sim
        self._sim_t0 = time.time()
        self.host = os.getenv('FIVE12_BOLERO_HOST', '').strip() or None

    def detect(self):
        if self.sim:
            return {'found': True, 'address': self.host or '10.0.0.60', 'detail': 'simulated'}
        if not self.host:
            return {'found': False, 'address': None,
                    'detail': 'set FIVE12_BOLERO_HOST to the antenna/AP address'}
        try:
            ip = require_private_host(self.host)
        except ValueError as exc:
            return {'found': False, 'address': None, 'detail': str(exc)}
        found = tcp_reachable(ip, 443) or tcp_reachable(ip, 80)
        return {'found': found, 'address': ip,
                'detail': 'web port open' if found else 'host unreachable'}

    def get_status(self):
        status = self._sim_status() if self.sim else self._real_status()
        status['alerts'] = check_thresholds(status, ALERT_RULES)
        if status.get('available'):
            self.history.record({
                'lowestBatteryPct': status.get('lowestBatteryPct'),
                'packsOnline': status.get('packsOnline'),
                'ptpSynced': status.get('ptpSynced'),
            })
        return status

    def _real_status(self):
        if not self.host:
            return {'available': False,
                    'reason': 'FIVE12_BOLERO_HOST not configured'}
        if not VERIFIED_AGAINST_UNIT:
            # Refuse to pretend: shipping guesses against a live intercom is
            # how integrations silently lie. Map the API first (DevTools),
            # correct ENDPOINTS/_normalize, then flip VERIFIED_AGAINST_UNIT.
            return {'available': False,
                    'reason': 'Bolero endpoint map not yet verified against a '
                              'real unit — see ENDPOINTS in bolero.py'}
        import requests
        try:
            ip = require_private_host(self.host)
            base = f'http://{ip}'
            packs = requests.get(base + ENDPOINTS['beltpacks'], timeout=3).json()
            ants = requests.get(base + ENDPOINTS['antennas'], timeout=3).json()
        except Exception as exc:  # noqa: BLE001
            return {'available': False, 'reason': f'Bolero unreachable: {exc}'}
        return self._normalize(packs, ants)

    def _normalize(self, packs_raw, ants_raw):
        """[NEEDS VERIFICATION] shape of real payloads — adapt when mapped."""
        packs = [{
            'id': p.get('id'),
            'name': p.get('name') or f"Pack {p.get('id')}",
            'batteryPct': p.get('battery'),
            'signal': p.get('signal'),
            'antenna': p.get('antenna'),
            'tempC': p.get('temperature'),
            'online': bool(p.get('online', True)),
        } for p in (packs_raw or [])]
        antennas = [{
            'id': a.get('id'),
            'name': a.get('name') or f"Antenna {a.get('id')}",
            'online': bool(a.get('online', True)),
            'ptpSynced': bool(a.get('ptpSynced', True)),
            'packCount': a.get('packCount'),
        } for a in (ants_raw or [])]
        online = [p for p in packs if p['online']]
        batts = [p['batteryPct'] for p in online if isinstance(p.get('batteryPct'), (int, float))]
        return {
            'available': True, 'source': 'rest',
            'beltpacks': sorted(packs, key=lambda p: p.get('batteryPct') or 999),
            'antennas': antennas,
            'packsOnline': len(online),
            'lowestBatteryPct': min(batts) if batts else None,
            'ptpSynced': all(a['ptpSynced'] for a in antennas) if antennas else None,
        }

    # ── simulator: a small show rig with realistic battery drain ──
    def _sim_status(self):
        t = time.time() - self._sim_t0
        crew = ['Stage Mgr', 'A1 Audio', 'LX Op', 'Camera 1', 'Camera 2', 'Grip']
        packs = []
        for i, name in enumerate(crew):
            start = 95 - i * 9
            drain = t / 60 * (0.55 + i * 0.13)          # %/min, varies per pack
            batt = max(2, round(start - drain))
            sig = round(72 + 20 * math.sin(t / 37 + i * 1.7))
            packs.append({
                'id': i + 1, 'name': name,
                'batteryPct': batt,
                'signal': max(15, min(99, sig)),
                'antenna': 'ANT-A' if i % 2 == 0 else 'ANT-B',
                'tempC': round(28 + 6 * math.sin(t / 91 + i), 1),
                'online': not (i == 5 and int(t / 240) % 2 == 1),  # grip wanders off
            })
        ptp_glitch = 55 < (t % 300) < 70                 # brief PTP loss every 5 min
        antennas = [
            {'id': 1, 'name': 'ANT-A', 'online': True, 'ptpSynced': True,
             'packCount': sum(1 for p in packs if p['antenna'] == 'ANT-A' and p['online'])},
            {'id': 2, 'name': 'ANT-B', 'online': True, 'ptpSynced': not ptp_glitch,
             'packCount': sum(1 for p in packs if p['antenna'] == 'ANT-B' and p['online'])},
        ]
        online = [p for p in packs if p['online']]
        batts = [p['batteryPct'] for p in online]
        return {
            'available': True, 'source': 'sim',
            'beltpacks': sorted(packs, key=lambda p: p['batteryPct']),
            'antennas': antennas,
            'packsOnline': len(online),
            'lowestBatteryPct': min(batts) if batts else None,
            'ptpSynced': not ptp_glitch,
        }
