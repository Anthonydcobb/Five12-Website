"""Starlink dish adapter — read-only gRPC telemetry.

[VERIFIED 2026-08-10 on the rig] The dish runs an unauthenticated gRPC server
on 192.168.100.1:9200 with server reflection enabled. Telemetry comes from
`starlink_grpc_client`, which builds the schema from the dish's own descriptors
at runtime, so there is no third-party package to install and no generated stub
to go stale. Only get_status and get_history are ever sent; that module's
allowlist is a safety boundary, not a convenience.

Why not the community wrapper this adapter used to import: it is not on PyPI
and its repository ships no packaging metadata, so both a plain `pip install`
and `pip install git+https://…` fail — both were tried on 2026-08-10. It works
only as a clone on PYTHONPATH, a deployment step that cannot be expressed in
requirements.txt and that nothing verifies at startup. Reflection needs no
clone. Its name is deliberately not written here: this docstring once carried
a pip line for it that could never have run, and the suite now fails if one
comes back.

Field names below come from a payload captured verbatim on 2026-08-10 and kept
in `tests/fixtures/`. A firmware update can move them, so every read is a
.get() with a default and the panel tolerates gaps.

Two things that capture settled, both of which the design got wrong from a
truncated sample:

- **There is no `state` field.** `device_state` carries uptime and nothing
  else, so the old `state == 'CONNECTED'` test could never have matched this
  payload. `'CONNECTED'` is not a word the dish sends: the community wrapper
  synthesises it whenever the dish reports no `outage` field, which is the
  only thing behind it. State here is derived from `disablement_code`, that
  same `outage` field, and `ready_states`, and reports the dish's own word for
  a fault rather than an invented one.
- **`dish_get_history` carries two clocks.** `outages[]` is stamped on an
  uncorrected clock reading 2016; `event_log.events[]` is on wall clock, ten
  years and change ahead. Everything time-based reads the event log, and the
  last-hour window is measured against the dish's own
  `event_log.current_timestamp_ns` rather than this host's clock.

Read-only by design. The endpoint also accepts destructive commands, which is
exactly why the client refuses to name them.
"""

import logging
import math
import time

from . import DeviceAdapter, check_thresholds, tcp_reachable
from . import starlink_grpc_client

log = logging.getLogger(__name__)

#: event_log reasons read `EVENT_REASON_OUTAGE_OBSTRUCTED`; the panel prints
#: the cause verbatim and only the last word carries meaning.
_EVENT_REASON_PREFIX = 'EVENT_REASON_OUTAGE_'
_EVENT_SEVERITY_PREFIX = 'EVENT_SEVERITY_'
_HOUR_NS = 3600 * 10 ** 9

DISH_HOST = '192.168.100.1'   # fixed address on any Starlink LAN [VERIFIED]
DISH_PORT = 9200

ALERT_RULES = [
    ('obstructionPct', 'gt', 5, 'Obstruction at {value}% — check sky view', 'warn'),
    ('online', 'eq', False, 'Dish is OFFLINE', 'crit'),
    ('latencyMs', 'gt', 120, 'Latency {value} ms — degraded', 'warn'),
    ('outagesLastHour', 'gt', 2, '{value} outages in the last hour', 'warn'),
]


def _num(value, scale=1.0, digits=2):
    """Scale and round, or None. Absent fields must not become zeroes — a tile
    reading 0 Mbps is a claim, and a missing field is not one."""
    return round(value * scale, digits) if isinstance(value, (int, float)) else None


def _int(value):
    """uptime_s arrives as a string: protobuf renders 64-bit ints that way."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _connection_state(dish):
    """Returns (state, online). The dish reports neither directly.

    Three fields carry it, checked worst-first so the operator sees the root
    cause rather than a symptom:

    1. `disablement_code` — the dish is administratively down (no account, and
       similar). Outranks everything: an outage under a disablement is its
       consequence.
    2. `outage` — an outage in progress, present only while one is happening.
       Load-bearing on its own: during an obstruction outage the disablement
       code stays OKAY and every ready_state stays true, so without this the
       panel would read READY while the link is dropping out.
    3. `ready_states` — a subsystem that has not come up.

    Missing evidence is never read as healthy: a firmware that drops these
    fields yields UNKNOWN and offline, not a green dot on no information.
    """
    code = dish.get('disablement_code')
    outage = dish.get('outage')
    ready = dish.get('ready_states') or {}

    if code and code != 'OKAY':
        return code, False
    if outage:
        # `cause` is absent when it is the zero-valued enum: protobuf omits it,
        # and an unnamed outage is still an outage.
        return outage.get('cause') or 'OUTAGE', False
    if not ready or not code:
        return 'UNKNOWN', False

    not_ready = sorted(name for name, up in ready.items() if not up)
    if not_ready:
        return 'NOT READY: ' + ', '.join(not_ready), False
    return 'READY', True


def _stowed(alignment):
    """No field reports stow state.

    A dish reporting no actuators cannot stow, which is the only claim the
    payload supports. Anything else is unknown, and None says so.
    """
    if alignment.get('has_actuators') == 'HAS_ACTUATORS_NO':
        return False
    return None


def _outages(history):
    """Returns (outages_in_the_last_hour, newest-first log).

    Read from `event_log.events`, deliberately not from `outages[]`: the two
    describe the same kind of event but `outages[]` is stamped on an
    uncorrected clock reading 2016, which would put every entry a decade in the
    past and leave the last-hour count permanently at zero.

    The window is measured against the dish's own `current_timestamp_ns` so it
    does not drift with host clock skew.
    """
    event_log = history.get('event_log') or {}
    now_ns = event_log.get('current_timestamp_ns')

    stamped = []
    for event in event_log.get('events') or []:
        start = _int(event.get('start_timestamp_ns'))
        if start is not None:
            stamped.append((start, event))
    stamped.sort(key=lambda pair: pair[0], reverse=True)

    entries = [{
        'ts': start / 1e9,
        'durationS': round((_int(event.get('duration_ns')) or 0) / 1e9, 3),
        'cause': (event.get('reason') or 'UNKNOWN').replace(_EVENT_REASON_PREFIX, ''),
        'severity': (event.get('severity') or '').replace(_EVENT_SEVERITY_PREFIX, ''),
    } for start, event in stamped]

    last_hour = None
    if _int(now_ns) is not None:
        last_hour = sum(1 for start, _ in stamped if _int(now_ns) - start <= _HOUR_NS)
    return last_hour, entries


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
        try:
            status = starlink_grpc_client.call('get_status')
        except Exception as exc:  # noqa: BLE001 — device offline, grpc errors, proto drift
            return {'available': False, 'reason': f'dish unreachable: {exc}'}

        dish = (status or {}).get('dish_get_status') or {}

        # A second, independent read. The dish's live state is worth showing
        # even when history fails, so this one is allowed to lose on its own.
        try:
            history = (starlink_grpc_client.call('get_history') or {}).get(
                'dish_get_history') or {}
        except Exception as exc:  # noqa: BLE001 — same failure modes, lesser stakes
            log.debug('starlink get_history failed, keeping live status: %s', exc)
            history = None

        outages_last_hour, outage_log = (
            (None, []) if history is None else _outages(history))

        state, online = _connection_state(dish)
        info = dish.get('device_info') or {}
        gps = dish.get('gps_stats') or {}
        obstruction = dish.get('obstruction_stats') or {}
        alignment = dish.get('alignment_stats') or {}

        return {
            'available': True,
            'source': 'grpc',
            'state': state,
            'online': online,
            'uptimeS': _int((dish.get('device_state') or {}).get('uptime_s')),
            'downMbps': _num(dish.get('downlink_throughput_bps'), 1 / 1e6),
            'upMbps': _num(dish.get('uplink_throughput_bps'), 1 / 1e6),
            'latencyMs': _num(dish.get('pop_ping_latency_ms')),
            # No snr key: the dish stopped reporting a figure years ago and it
            # is absent from the captured payload. is_snr_above_noise_floor is
            # what it reports instead.
            'snrAboveNoiseFloor': dish.get('is_snr_above_noise_floor'),
            'obstructionPct': _num(obstruction.get('fraction_obstructed'), 100),
            'obstructionValidS': _num(obstruction.get('valid_s')),
            'stowed': _stowed(alignment),
            'hardwareAlerts': [k for k, v in (dish.get('alerts') or {}).items() if v],
            'outagesLastHour': outages_last_hour,
            'outageLog': outage_log,
            'hardwareVersion': info.get('hardware_version'),
            'softwareVersion': info.get('software_version'),
            'bootcount': info.get('bootcount'),
            'softwareUpdateState': dish.get('software_update_state'),
            'gpsValid': gps.get('gps_valid'),
            'gpsSats': gps.get('gps_sats'),
            'ethSpeedMbps': dish.get('eth_speed_mbps'),
            'mobilityClass': dish.get('mobility_class'),
            'disablementCode': dish.get('disablement_code'),
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
