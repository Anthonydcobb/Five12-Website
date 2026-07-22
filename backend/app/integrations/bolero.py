"""Riedel Bolero adapter — read-only beltpack/antenna telemetry.

[VERIFIED 2026-07-22] Mapped against a real Bolero Standalone at 192.168.1.11
(HAR capture). The web GUI is an AngularJS app over a plain REST surface:

  GET /rest/nodeStatus  antennas + LIVE per-pack battery (each node's bp[] are
                        the packs currently attached to that antenna)
  GET /rest/nodeConfig  nodeId -> antenna name (MBS LM 2 = .11, MBS LM 1 = .12)
  GET /rest/bp          DECT id -> crew name (bpConfig.bpName), ~98 KB

Auth is HTTP Basic with the factory READ-ONLY account the GUI itself uses
(user/userPass); overridable via env. No login flow. There is also a
ws://…/wsapp live-push socket — deliberately out of scope for v1 polling.

Read-only in v1: writing to a live comms system mid-show is out of scope.

Configuration:
  FIVE12_BOLERO_HOST=<ip-of-antenna>   (must be a private IP)
  FIVE12_BOLERO_USER / FIVE12_BOLERO_PASS  (default to the read-only account)
"""

import logging
import math
import os
import time

from . import DeviceAdapter, check_thresholds, require_private_host, tcp_reachable

log = logging.getLogger(__name__)

# ── Real REST endpoints, verified against a unit ────────────────────────────
ENDPOINTS = {
    'antennas': '/rest/nodeStatus',   # antennas + live per-pack battery
    'nodes': '/rest/nodeConfig',      # nodeId -> antenna name
    'roster': '/rest/bp',             # DECT id -> crew name (large; cached)
}
VERIFIED_AGAINST_UNIT = True

# The roster is ~98 KB and changes rarely; the live battery (nodeStatus) is
# small and polled every cycle. Refresh the id->name map no more than this.
NAME_CACHE_TTL = 300.0

ALERT_RULES = [
    ('lowestBatteryPct', 'lt', 20, 'Beltpack battery at {value}%', 'crit'),
    ('ptpSynced', 'eq', False, 'PTP sync LOST on an antenna', 'crit'),
    ('packsOnline', 'eq', 0, 'No beltpacks online', 'warn'),
]

# ── Signal quality — mirrors Riedel's OWN getSignalIconClass/getSignalTooltip ──
# (verified in the GUI bundle app-028c6fe2a3.js). `signalLevel` in
# /rest/nodeStatus is Riedel's BP_SIGNAL_LEVELS enum, NOT a raw 0/1 scale: the
# GUI maps it straight to bars (icon-radiolevel_N) + a word, and does NOT
# consult `timeslots` at all. We reproduce that mapping exactly:
#
#   level 0 EXCELLENT -> icon-radiolevel_4  "Excellent"
#   level 1 GOOD      -> icon-radiolevel_3  "Good"
#   level 2 MEDIUM    -> icon-radiolevel_2  "Medium"
#   level 3 BAD       -> icon-radiolevel_1  "Bad"
#   0xFF   INVALID    -> icon-radiolevel_off "Not Connected"
SIGNAL_LEVELS = {
    0: (4, 'Excellent'),
    1: (3, 'Good'),
    2: (2, 'Medium'),
    3: (1, 'Bad'),
}
SIGNAL_NOT_CONNECTED = (0, 'Not Connected')  # BP_SIGNAL_LEVELS.INVALID (0xFF)


def _signal_quality(signal_level):
    """Map a pack's raw signalLevel enum to (bars 0-4, label), matching the
    Bolero GUI exactly. Any value outside 0-3 (0xFF INVALID, missing, unknown)
    reads as 'Not Connected' / 0 bars — the GUI's INVALID case."""
    return SIGNAL_LEVELS.get(signal_level, SIGNAL_NOT_CONNECTED)


class BoleroAdapter(DeviceAdapter):
    id = 'bolero'
    name = 'Riedel Bolero'

    def __init__(self, sim=False):
        super().__init__()
        self.sim = sim
        self._sim_t0 = time.time()
        self.host = os.getenv('FIVE12_BOLERO_HOST', '').strip() or None
        self.user = os.getenv('FIVE12_BOLERO_USER', 'user')
        self.password = os.getenv('FIVE12_BOLERO_PASS', 'userPass')
        self._name_cache = {}
        self._name_cache_at = 0.0

    def detect(self):
        if self.sim:
            return {'found': True, 'address': self.host or '192.168.1.11', 'detail': 'simulated'}
        if not self.host:
            return {'found': False, 'address': None,
                    'detail': 'set FIVE12_BOLERO_HOST to the antenna address'}
        try:
            ip = require_private_host(self.host)
        except ValueError as exc:
            return {'found': False, 'address': None, 'detail': str(exc)}
        found = tcp_reachable(ip, 80) or tcp_reachable(ip, 443)
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

    # ── real hardware ──────────────────────────────────────────────────────
    def _fetch_json(self, path):
        """GET a /rest endpoint on the configured PRIVATE host over Basic auth.
        Host is re-validated every call so it can never be a non-private
        target, and it is never derived from request input."""
        import requests
        ip = require_private_host(self.host)
        resp = requests.get(f'http://{ip}{path}',
                            auth=(self.user, self.password), timeout=3)
        resp.raise_for_status()
        return resp.json()

    def _name_map(self):
        """Cached DECT id -> crew name from /rest/bp. Refreshed at most every
        NAME_CACHE_TTL; a failed refresh keeps the last good map rather than
        blanking every pack's name."""
        now = time.time()
        if self._name_cache and now - self._name_cache_at < NAME_CACHE_TTL:
            return self._name_cache
        try:
            data = self._fetch_json(ENDPOINTS['roster'])
            self._name_cache = {
                bp['id']: (bp.get('bpConfig', {}).get('bpName') or f"Pack {bp['id']}")
                for bp in data.get('bp', []) if 'id' in bp
            }
            self._name_cache_at = now
        except Exception as exc:  # noqa: BLE001
            log.warning('Bolero roster fetch failed, keeping cached names: %s', exc)
        return self._name_cache

    def _real_status(self):
        if not self.host:
            return {'available': False, 'reason': 'FIVE12_BOLERO_HOST not configured'}
        try:
            node_status = self._fetch_json(ENDPOINTS['antennas'])
            node_config = self._fetch_json(ENDPOINTS['nodes'])
            names = self._name_map()
        except Exception as exc:  # noqa: BLE001
            return {'available': False, 'reason': f'Bolero unreachable: {exc}'}
        return self._normalize(node_status, node_config, names)

    def _normalize(self, node_status, node_config, name_map):
        """Join the real payloads into the panel contract.

        A pack is 'attached' to exactly the antenna whose bp[] lists it, which
        is how the operator sees it in the GUI. `online` is therefore True for
        every pack present in a node's bp[].
        """
        names_by_id = {n['nodeId']: n.get('name') for n in node_config.get('nodeConfig', [])}

        antennas, beltpacks = [], []
        for node in node_status.get('nodeStatus', []):
            nid = node.get('nodeId')
            aname = names_by_id.get(nid) or f'Antenna {nid}'
            ptp_synced = node.get('ptpStatus', {}).get('lockState') == 2
            packs = node.get('bp', []) or []
            antennas.append({
                'id': nid, 'name': aname, 'online': True,
                'ptpSynced': ptp_synced, 'packCount': len(packs),
            })
            for bp in packs:
                batt = bp.get('battery', {}) or {}
                pid = bp.get('id')
                sig_bars, sig_label = _signal_quality(bp.get('signalLevel'))
                beltpacks.append({
                    'id': pid,
                    'name': name_map.get(pid) or f'Pack {pid}',
                    'batteryPct': batt.get('status'),
                    'mAh': batt.get('currentCharge'),
                    'healthPct': batt.get('batteryHealth'),
                    'tempC': batt.get('batteryTemperature'),
                    'charging': bool(batt.get('usbPower')),
                    'signalQuality': sig_bars,
                    'signalLabel': sig_label,
                    'antenna': aname,
                    'online': True,
                })

        beltpacks.sort(key=lambda p: p['batteryPct'] if isinstance(p.get('batteryPct'), (int, float)) else 999)
        batts = [p['batteryPct'] for p in beltpacks if isinstance(p.get('batteryPct'), (int, float))]
        return {
            'available': True, 'source': 'rest',
            'antennas': antennas,
            'beltpacks': beltpacks,
            'packsOnline': len(beltpacks),
            'lowestBatteryPct': min(batts) if batts else None,
            'ptpSynced': all(a['ptpSynced'] for a in antennas) if antennas else None,
        }

    # ── simulator: a small show rig with realistic battery drain ──
    def _sim_status(self):
        t = time.time() - self._sim_t0
        crew = ['Stage Mgr', 'A1 Audio', 'LX Op', 'Camera 1', 'Camera 2', 'Grip']
        sig_levels = [0, 0, 1, 0, 2, 3]                 # a plausible spread of enums
        packs = []
        for i, name in enumerate(crew):
            start = 95 - i * 9
            drain = t / 60 * (0.55 + i * 0.13)          # %/min, varies per pack
            batt = max(2, round(start - drain))
            online = not (i == 5 and int(t / 240) % 2 == 1)   # grip wanders off
            level = sig_levels[i] if online else 0xFF   # offline reads Not Connected
            sig_bars, sig_label = _signal_quality(level)
            packs.append({
                'id': i + 1, 'name': name,
                'batteryPct': batt,
                'mAh': round(batt / 100 * 4800),
                'healthPct': max(70, 100 - i * 3),
                'tempC': round(28 + 6 * math.sin(t / 91 + i), 1),
                'charging': i == 0 and int(t / 120) % 2 == 1,   # SM docks now and then
                'signalQuality': sig_bars,
                'signalLabel': sig_label,
                'antenna': 'ANT-A' if i % 2 == 0 else 'ANT-B',
                'online': online,
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
