"""Astera ART7 adapter — read-only fixture-system telemetry via AsteraNext.

[UNVERIFIED — static analysis only, 2026-07-28] Everything here about the
AsteraNext HTTP surface comes from disassembling the Android app (13.18 /
code 812), NOT from a live server. Field names and semantics must be treated
as unconfirmed until a bench capture against a real AsteraNext instance.
KB reference: 10-Lighting/References/Astera/art7-asteranext-communications-
and-integration.md. Review + agreed direction: docs/agent-reviews/
2026-07-29-claude-review-of-astera-integration-spec.md and Hermes' response
(KB Hermes/Reviews/2026-07-29-hermes-response-to-claude-five12-art7-review.md).

Transport: AsteraNext's embedded RemoteControl web server (EmbedIO), which
binds http://*:8080 on the phone/tablet running the app. That server ALSO
exposes state-changing GET routes (/api/launch, /api/set_power, ...) with no
visible authentication. This adapter must never reference them: the allowlist
below is the complete set of paths this module may fetch, and both are reads.

Gate contract (agreed with Hermes, stricter than the other adapters because
live fixtures share the set with this app):
  * FIVE12_ASTERA_TOOLS unset/0 (default): NO network activity of any kind —
    no DNS, no TCP probe, no HTTP. The UI shows "disabled", never
    "searched and absent". The gate governs sim mode too.
  * Gate on, no host: report the exact setup requirement, still no request.

Configuration:
  FIVE12_ASTERA_TOOLS=1                  master switch, default off
  FIVE12_ASTERA_HOST=<phone-ip>          must resolve private; IPv6 bracketed,
                                         IPv6 link-local refused (no zone
                                         handling yet — B5)
  FIVE12_ASTERA_PORT=8080                AsteraNext RemoteControl port
"""

import hashlib
import ipaddress
import json
import os

import requests

from . import DeviceAdapter, check_thresholds, require_private_host, tcp_reachable

# The COMPLETE allowlist of paths this module may fetch. Both are reads.
# Never add a state-changing route here — AsteraNext implements those as
# GET, so "it's only a GET" is not a safety argument on this server.
ENDPOINTS = {
    'status': '/api/status',    # app online state, PIN, bridge name/battery
    'targets': '/api/targets',  # target/set metadata
}

# No live AsteraNext server has been captured yet; the payload shapes the
# normalizers expect are hypotheses from static analysis of the app binary.
VERIFIED_AGAINST_UNIT = False

DEFAULT_PORT = 8080

# A status/targets read is small metadata; anything approaching this size is
# not the payload we asked for. Streamed and enforced before parsing.
MAX_RESPONSE_BYTES = 1_048_576  # 1 MiB
FETCH_TIMEOUT = 3

DISABLED_DETAIL = 'Astera tools disabled — set FIVE12_ASTERA_TOOLS=1 to enable'
NO_HOST_DETAIL = ('set FIVE12_ASTERA_HOST to the address of the phone/tablet '
                  'running AsteraNext (RemoteControl enabled)')

ALERT_RULES = [
    ('bridge.batteryPct', 'lt', 20, 'ART7 bridge battery at {value}%', 'crit'),
    ('appOnline', 'eq', False, 'AsteraNext app offline', 'warn'),
]


def _pin_alias(pin):
    """Deterministic alias so operators can tell 'the PIN changed' apart from
    'same PIN' across sessions without the raw value ever being displayed or
    logged. Hygiene, not secrecy — a 4-digit PIN is trivially brute-forced
    from any short hash, so the protection is keeping it out of casual view
    and logs, which is all the agreed direction requires.

    8 hex characters, not 4 (Hermes review S1, 2026-08-03): a 16-bit alias
    collides across the 10 000 possible PINs, and a collision renders as "the
    PIN did not change" — a confidently wrong value, which is the failure mode
    this project keeps meeting. The width is about telling PINs apart, not
    about strength."""
    if pin is None:
        return None
    return 'PIN-' + hashlib.sha256(str(pin).encode()).hexdigest()[:8].upper()


def _gate_enabled():
    """Read at call time, not construction: the registry caches adapter
    instances for process life, and a cached instance must honor the
    operator flipping the gate."""
    return os.getenv('FIVE12_ASTERA_TOOLS', '0') == '1'


class AsteraAdapter(DeviceAdapter):
    id = 'astera'
    name = 'Astera ART7'

    def __init__(self, sim=False):
        super().__init__()
        self.sim = sim

    @property
    def host(self):
        return os.getenv('FIVE12_ASTERA_HOST', '').strip() or None

    @property
    def port(self):
        try:
            return int(os.getenv('FIVE12_ASTERA_PORT', str(DEFAULT_PORT)))
        except ValueError:
            return DEFAULT_PORT

    def detect(self):
        if not _gate_enabled():
            return {'found': False, 'address': None, 'detail': DISABLED_DETAIL}
        if self.sim:
            return {'found': True, 'address': self.host or '192.168.1.50',
                    'detail': 'simulated'}
        if not self.host:
            return {'found': False, 'address': None, 'detail': NO_HOST_DETAIL}
        try:
            ip = require_private_host(self.host)
        except ValueError as exc:
            return {'found': False, 'address': None, 'detail': str(exc)}
        found = tcp_reachable(ip, self.port)
        detail = ('AsteraNext RemoteControl port open' if found else
                  f'port {self.port} closed on {ip} — is RemoteControl '
                  'enabled in AsteraNext?')
        return {'found': found, 'address': ip, 'detail': detail}

    def get_status(self):
        if not _gate_enabled():
            # `disabled` is a separate flag from `available` on purpose: the UI
            # must be able to say "we never looked" rather than the generic
            # "device unavailable", which reads as searched-and-absent.
            return {'available': False, 'disabled': True,
                    'reason': DISABLED_DETAIL, 'alerts': []}
        if self.sim:
            return self._sim_status()
        try:
            raw_status = self._fetch_json('status')
            raw_targets = self._fetch_json('targets')
        except (ValueError, OSError, requests.RequestException) as exc:
            return {'available': False, 'reason': str(exc), 'alerts': []}
        # A payload can be valid JSON and still not be the object we expect —
        # `null`, a list, a bare string. With the protocol unverified that is a
        # live possibility, and it must read as unavailable-with-a-reason
        # rather than becoming an AttributeError and a backend 500 (review W1).
        for name, payload in (('/api/status', raw_status),
                              ('/api/targets', raw_targets)):
            if not isinstance(payload, dict):
                return {'available': False, 'alerts': [],
                        'reason': (f'unexpected payload shape from {name}: '
                                   f'expected an object, got '
                                   f'{type(payload).__name__}')}
        status = self._normalize(raw_status, raw_targets)
        status['alerts'] = check_thresholds(status, ALERT_RULES)
        self.history.record({'bridgeBatteryPct': status['bridge']['batteryPct']})
        return status

    def _normalize(self, raw_status, raw_targets):
        """[UNVERIFIED] Field names are hypotheses from static analysis of
        AsteraNext 13.18 — hence protocolVerified and the defensive .get()s.
        The bench capture corrects this mapping; until then a missing field
        reads as None, never as a guess."""
        # Nested shapes get the same treatment as the top level, and are the
        # likelier failure: one renamed or retyped key in an unverified payload
        # is enough. Anything not of the expected type reads as absent.
        bridge = raw_status.get('bridge')
        if not isinstance(bridge, dict):
            bridge = {}
        raw_list = raw_targets.get('targets')
        if not isinstance(raw_list, list):
            raw_list = []
        targets = []
        for t in raw_list:
            if isinstance(t, dict):
                targets.append({
                    'id': t.get('id'),
                    'name': t.get('name'),
                    'selected': t.get('selected'),
                    'brightnessPct': t.get('brightness'),
                })
        return {
            'available': True,
            'simulated': False,
            'protocolVerified': VERIFIED_AGAINST_UNIT,
            'appOnline': raw_status.get('online'),
            'appVersion': raw_status.get('version'),
            'platform': raw_status.get('platform'),
            'bridge': {'name': bridge.get('name'),
                       'batteryPct': bridge.get('battery')},
            'radioPinAlias': _pin_alias(raw_status.get('pin')),
            'targets': targets,
            'targetCount': len(targets),
        }

    def _fetch_json(self, key):
        """Fetch one allowlisted read. `key` indexes ENDPOINTS — a path can
        never be passed in, so the state-changing AsteraNext routes are
        unreachable by construction. Raises ValueError with the reason on
        any boundary violation."""
        path = ENDPOINTS[key]
        ip = require_private_host(self.host)
        addr = ipaddress.ip_address(ip)
        if addr.version == 6:
            if addr.is_link_local:
                raise ValueError(
                    f'{ip} is IPv6 link-local — refused until zone handling '
                    'is designed (review B5)')
            hostpart = f'[{ip}]'
        else:
            hostpart = ip
        resp = requests.get(
            f'http://{hostpart}:{self.port}{path}',
            timeout=FETCH_TIMEOUT,
            allow_redirects=False,
            stream=True,
        )
        try:
            if 300 <= resp.status_code < 400:
                raise ValueError(f'refused redirect (HTTP {resp.status_code})')
            if resp.status_code != 200:
                raise ValueError(f'HTTP {resp.status_code} from {path}')
            ctype = (resp.headers.get('Content-Type') or '').split(';')[0].strip()
            if ctype != 'application/json':
                raise ValueError(f'unexpected content type {ctype!r} from {path}')
            body = b''
            for chunk in resp.iter_content(chunk_size=65536):
                body += chunk
                if len(body) > MAX_RESPONSE_BYTES:
                    raise ValueError(f'response from {path} too large (>{MAX_RESPONSE_BYTES} bytes)')
        finally:
            resp.close()
        return json.loads(body)

    def _sim_status(self):
        """Models ONLY the normalized Five12 contract. Nothing here is
        protocol evidence; every consumer sees simulated=True."""
        status = {
            'available': True,
            'simulated': True,
            'appOnline': True,
            'appVersion': '13.18 (sim)',
            'platform': 'sim',
            'bridge': {'name': 'ART7-SIM', 'batteryPct': 76},
            'radioPinAlias': 'PIN-SIM',
            'targets': [
                {'id': 1, 'name': 'Key Tubes', 'selected': True,
                 'brightnessPct': 80},
                {'id': 2, 'name': 'BG NYX', 'selected': False,
                 'brightnessPct': 45},
            ],
        }
        status['targetCount'] = len(status['targets'])
        status['alerts'] = check_thresholds(status, ALERT_RULES)
        self.history.record({'bridgeBatteryPct': status['bridge']['batteryPct']})
        return status
