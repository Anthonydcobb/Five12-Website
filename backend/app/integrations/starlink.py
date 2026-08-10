"""Starlink dish adapter — read-only gRPC telemetry.

[VERIFIED] Dishy runs an unauthenticated gRPC server on 192.168.100.1:9200
(HTTP/2, server reflection on). Community tooling: sparky8512's
sparky8512's starlink-grpc-tools provides the `starlink_grpc` module. It is NOT
on PyPI and the repo ships no setup.py or pyproject.toml, so neither
`pip install starlink-grpc-tools` nor `pip install git+https://...` works --
both were tried and both fail. Clone the repo and put it on PYTHONPATH.
No official API — reverse-engineered but stable/widely used.

[VERIFIED 2026-08-10] on the app interpreter (Python 3.12), this sequence gives
a working `import starlink_grpc` and a live read:

    pip install grpcio grpcio-tools protobuf yagrc typing-extensions
    git clone https://github.com/sparky8512/starlink-grpc-tools.git
    set PYTHONPATH=<clone dir>

status_data() then returned state=CONNECTED with 23 status fields from the dish
at 192.168.100.1. The remaining entries in the repo's own requirements.txt
(paho-mqtt, influxdb, pypng, croniter, python-dateutil) are for its dish_grpc_*
scripts and are NOT needed to import the module.

Field names below follow starlink_grpc's status_data() output.
[NEEDS VERIFICATION on your firmware] — a Starlink update can shift fields,
so every read is .get() with a default and the panel tolerates gaps.

Read-only by design. The API also supports reboot/stow — deliberately NOT
exposed (v2, behind confirmation, per the research doc).
"""

import math
import os
import sys
import time

from . import DeviceAdapter, check_thresholds, tcp_reachable

DISH_HOST = '192.168.100.1'   # fixed address on any Starlink LAN [VERIFIED]
DISH_PORT = 9200

#: Directory holding a clone of sparky8512/starlink-grpc-tools.
#:
#: The module cannot be pip-installed (see the header), so the only way to make
#: `import starlink_grpc` work is to have its directory on sys.path. Setting
#: PYTHONPATH at launch does that, but only for whoever remembers -- start.ps1
#: does not set it, so live telemetry would silently revert to unavailable the
#: next time anyone started the app normally. This makes the location
#: configuration instead of a launch-time incantation.
#:
#: Unset by default: an operator who does not want live telemetry gets exactly
#: the behaviour they had before, and nothing is added to sys.path.
GRPC_PATH_ENV = 'FIVE12_STARLINK_GRPC_PATH'


def _ensure_grpc_path():
    '''Put the starlink-grpc-tools clone on sys.path, if configured.

    Returns the directory added or already present, else None.

    Deliberately narrow: it will not add a path that does not exist, because a
    typo'd directory silently doing nothing is indistinguishable from the
    feature being off, and the operator would have no way to tell which. A
    configured-but-missing directory is reported instead -- see _real_status.

    Idempotent, so repeated status reads do not grow sys.path.
    '''
    raw = (os.getenv(GRPC_PATH_ENV) or '').strip().strip('"')
    if not raw:
        return None
    path = os.path.abspath(raw)
    if not os.path.isdir(path):
        return None
    if path not in sys.path:
        sys.path.insert(0, path)
    return path

ALERT_RULES = [
    ('obstructionPct', 'gt', 5, 'Obstruction at {value}% — check sky view', 'warn'),
    ('online', 'eq', False, 'Dish is OFFLINE', 'crit'),
    ('latencyMs', 'gt', 120, 'Latency {value} ms — degraded', 'warn'),
    ('outagesLastHour', 'gt', 2, '{value} outages in the last hour', 'warn'),
]


class StarlinkAdapter(DeviceAdapter):
    id = 'starlink'
    name = 'Starlink (Dishy)'

    def __init__(self, sim=False):
        super().__init__()
        self.sim = sim
        self._sim_t0 = time.time()
        self._sim_outages = []

    # ── detection ──
    def detect(self):
        if self.sim:
            return {'found': True, 'address': DISH_HOST, 'detail': 'simulated'}
        found = tcp_reachable(DISH_HOST, DISH_PORT)
        return {
            'found': found,
            'address': DISH_HOST if found else None,
            'detail': 'gRPC port open' if found else f'{DISH_HOST}:{DISH_PORT} unreachable',
        }

    # ── status ──
    def get_status(self):
        status = self._sim_status() if self.sim else self._real_status()
        status['alerts'] = check_thresholds(status, ALERT_RULES)
        if status.get('available'):
            self.history.record({
                'downMbps': status.get('downMbps'),
                'upMbps': status.get('upMbps'),
                'latencyMs': status.get('latencyMs'),
                'obstructionPct': status.get('obstructionPct'),
                'online': status.get('online'),
            })
        return status

    def _real_status(self):
        configured = os.getenv(GRPC_PATH_ENV)
        resolved = _ensure_grpc_path()
        try:
            import starlink_grpc  # from starlink-grpc-tools
        except ImportError:
            # Distinguish the three states rather than emitting one message for
            # all of them. "Set it" and "you set it to somewhere that isn't
            # there" need different actions, and an operator staring at a
            # generic string cannot tell which they are in.
            if configured and not resolved:
                reason = (f"{GRPC_PATH_ENV} is set to '{configured}', but that "
                          f"directory does not exist.")
            elif not configured:
                reason = (f"Module 'starlink_grpc' not importable. It is not on "
                          f"PyPI: clone sparky8512/starlink-grpc-tools, then set "
                          f"{GRPC_PATH_ENV} to that directory. Also "
                          f"'pip install grpcio grpcio-tools protobuf yagrc'. "
                          f"Sim mode needs none of this.")
            else:
                reason = (f"{GRPC_PATH_ENV} points at '{resolved}' but "
                          f"'import starlink_grpc' still failed. Check the clone "
                          f"contains starlink_grpc.py and that "
                          f"'pip install grpcio grpcio-tools protobuf yagrc' ran "
                          f"on the interpreter serving this app.")
            return {'available': False, 'reason': reason}
        try:
            groups = starlink_grpc.status_data()  # (status, obstruction, alerts)
            g_status, g_obstruct, g_alerts = groups
        except Exception as exc:  # noqa: BLE001 — device offline, grpc errors, proto drift
            return {'available': False, 'reason': f'dish unreachable: {exc}'}

        def num(d, key, scale=1.0):
            v = d.get(key)
            return round(v * scale, 2) if isinstance(v, (int, float)) else None

        state = g_status.get('state', 'UNKNOWN')
        return {
            'available': True,
            'source': 'grpc',
            'state': state,
            'online': state == 'CONNECTED',
            'uptimeS': g_status.get('uptime'),
            'downMbps': num(g_status, 'downlink_throughput_bps', 1 / 1e6),
            'upMbps': num(g_status, 'uplink_throughput_bps', 1 / 1e6),
            'latencyMs': num(g_status, 'pop_ping_latency_ms'),
            'snr': g_status.get('snr'),
            'snrAboveNoiseFloor': g_status.get('is_snr_above_noise_floor'),
            'obstructionPct': num(g_obstruct, 'fraction_obstructed', 100),
            'stowed': g_status.get('state') == 'STOWED',
            'hardwareAlerts': [k for k, v in (g_alerts or {}).items() if v],
            'outagesLastHour': None,   # needs history_data(); v2
            'outageLog': [],
        }

    # ── simulator: realistic drift, occasional outage ──
    def _sim_status(self):
        t = time.time() - self._sim_t0
        # outage roughly every 7 minutes, lasting ~20 s
        cycle = t % 420
        in_outage = cycle > 400
        if in_outage and (not self._sim_outages or t - self._sim_outages[-1]['at'] > 60):
            self._sim_outages.append({'at': t, 'ts': time.time(), 'durationS': 20, 'cause': 'OBSTRUCTED'})
        self._sim_outages = self._sim_outages[-20:]
        hour_ago = time.time() - 3600
        recent = [o for o in self._sim_outages if o['ts'] > hour_ago]
        obstruction = 2.5 + 2.2 * math.sin(t / 180) + (4 if in_outage else 0)
        return {
            'available': True,
            'source': 'sim',
            'state': 'OBSTRUCTED' if in_outage else 'CONNECTED',
            'online': not in_outage,
            'uptimeS': int(t) + 86400 * 2,
            'downMbps': 0.0 if in_outage else round(140 + 60 * math.sin(t / 47) + 15 * math.sin(t / 7), 1),
            'upMbps': 0.0 if in_outage else round(18 + 6 * math.sin(t / 31), 1),
            'latencyMs': None if in_outage else round(38 + 12 * math.sin(t / 23) + (25 if obstruction > 5 else 0), 1),
            'snr': 9 if not in_outage else 2,
            'snrAboveNoiseFloor': not in_outage,
            'obstructionPct': round(max(0, obstruction), 2),
            'stowed': False,
            'hardwareAlerts': [],
            'outagesLastHour': len(recent),
            'outageLog': [
                {'ts': o['ts'], 'durationS': o['durationS'], 'cause': o['cause']}
                for o in reversed(recent)
            ],
        }
