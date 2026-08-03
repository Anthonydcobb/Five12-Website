"""Device integration framework (research doc 2026-07-04).

One pattern, three adapters: device-aware panels layered on the Network
Monitor. Every adapter is READ-ONLY in v1 and isolated behind this thin
interface so a firmware change breaks one module, not the app.

Security notes (the GigaCore/Swisson SSRF lesson):
  * No screen-scraping. Starlink = gRPC, Bolero = its own REST surface,
    Stardust = RDM-over-Art-Net (documented standard).
  * Outbound requests only ever go to FIXED addresses (Starlink's
    192.168.100.1) or operator-configured PRIVATE addresses validated by
    _require_private_host(). Nothing derived from request input.
  * Sim mode (FIVE12_DEVICE_SIM=1 or ?sim=1) fabricates realistic telemetry
    for development/demo without hardware.
"""

import ipaddress
import os
import socket
import threading
import time


def sim_enabled(request_args=None):
    if request_args is not None and request_args.get('sim') in ('1', 'true'):
        return True
    return os.getenv('FIVE12_DEVICE_SIM', '') in ('1', 'true')


def require_private_host(host):
    """Refuse to talk to anything that isn't a private/link-local address.
    Hostnames are resolved first so DNS can't smuggle a public target."""
    try:
        resolved = socket.getaddrinfo(host, None)[0][4][0]
        ip = ipaddress.ip_address(resolved)
    except (socket.gaierror, ValueError, IndexError):
        raise ValueError(f'cannot resolve {host!r}')
    if not (ip.is_private or ip.is_link_local):
        raise ValueError(f'{host!r} resolves to non-private {ip} — refused')
    return str(ip)


def tcp_reachable(host, port, timeout=0.6):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class HistoryRing:
    """In-memory telemetry history: bounded, thread-safe, throttled.
    Persists for the life of the Flask process (per user decision —
    DB persistence is a later step)."""

    def __init__(self, maxlen=2880, min_interval=4.0):
        self.maxlen = maxlen
        self.min_interval = min_interval
        self._samples = []
        self._lock = threading.Lock()
        self._last_at = 0.0

    def record(self, sample):
        now = time.time()
        with self._lock:
            if now - self._last_at < self.min_interval:
                return
            self._last_at = now
            self._samples.append({'ts': now, **sample})
            if len(self._samples) > self.maxlen:
                del self._samples[: len(self._samples) - self.maxlen]

    def tail(self, n=240):
        with self._lock:
            return list(self._samples[-n:])


def check_thresholds(status, rules):
    """Shared alerts primitive: rules = [(key_path, op, limit, message)].
    Returns a list of {'level','message'} dicts; missing keys never raise."""
    alerts = []
    for path, op, limit, message, level in rules:
        val = status
        for part in path.split('.'):
            val = val.get(part) if isinstance(val, dict) else None
            if val is None:
                break
        if val is None:
            continue
        hit = (op == 'gt' and val > limit) or \
              (op == 'lt' and val < limit) or \
              (op == 'eq' and val == limit) or \
              (op == 'ne' and val != limit)
        if hit:
            alerts.append({'level': level, 'message': message.format(value=val)})
    return alerts


class DeviceAdapter:
    """Interface every device implements. All read-only in v1."""

    id = 'base'
    name = 'Device'

    def detect(self):
        """-> {'found': bool, 'address': str|None, 'detail': str}"""
        raise NotImplementedError

    def get_status(self):
        """-> camelCase dict; must include 'available' and 'alerts'."""
        raise NotImplementedError

    # history is uniform: adapters call self.history.record() in get_status
    def __init__(self):
        self.history = HistoryRing()

    def get_history(self, n=240):
        return self.history.tail(n)


_registry = {}
_registry_lock = threading.Lock()


def get_adapter(device_id, sim):
    """Adapters are cached per (device, sim) so history accumulates."""
    from .starlink import StarlinkAdapter
    from .bolero import BoleroAdapter
    from .stardust import StardustAdapter
    from .cintenna import CintennaAdapter
    from .astera import AsteraAdapter
    classes = {
        'starlink': StarlinkAdapter,
        'bolero': BoleroAdapter,
        'stardust': StardustAdapter,
        'cintenna': CintennaAdapter,
        'astera': AsteraAdapter,
    }
    cls = classes.get(device_id)
    if cls is None:
        return None
    key = (device_id, bool(sim))
    with _registry_lock:
        if key not in _registry:
            _registry[key] = cls(sim=bool(sim))
        return _registry[key]


ALL_DEVICE_IDS = ('starlink', 'bolero', 'stardust', 'cintenna', 'astera')
