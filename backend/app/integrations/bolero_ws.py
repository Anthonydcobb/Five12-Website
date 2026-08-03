"""Per-antenna beltpack counts from the Bolero websocket.

Full protocol findings, established against the live rig and a devtools capture,
are in `docs/architecture/bolero-websocket-protocol.md`. Three of them decide the
whole shape of this module:

1. **The socket takes no requests.** Every frame the Bolero GUI sends is
   `{"event":"ping","data":"ping"}`. There is no subscribe and no state request,
   so there is no snapshot to ask for. A fresh listener knows nothing and learns
   only as `audioPorts` messages arrive.

2. **A pack's antenna changes several times a second.** On the real rig, pack 30
   moved MBS LM 3 -> LM 1 -> LM 3 inside 450 ms; pack 35 moved four times in
   1.5 s. That is DECT handover working normally. A per-pack "which antenna"
   value is stale before it renders, which is why this module produces an
   aggregate count and deliberately exposes no per-pack antenna.

3. **`audioPorts` only ever says `registered: true`.** No deregistration was
   observed, so it is not known whether a pack can hold bearers on several
   antennas at once.

Point 3 is unresolved and Anthony chose to proceed anyway. The model is
therefore **last announcement wins**: a pack counts toward the antenna named in
the most recent `audioPorts` message about it. That is well defined under either
reading — the current assignment if handover is exclusive, the most recently
announced bearer if it is not — and it can never double-count, because a pack
maps to exactly one antenna at a time. What would change under the multi-bearer
reading is the *meaning* of the number, from "attached to" to "most recently
announced on", not its arithmetic.

Deliberately NOT wired into anything. `create_app()`, `run_desktop.py` and the
startup lifecycle belong to the runtime manager, which is Hermes' milestone and
does not exist yet. `BoleroAntennaListener` implements the lifecycle shape the
plan's Task 3.1 specifies so registration is a few lines once it does.
"""

import json
import logging
import threading
import time

log = logging.getLogger(__name__)

WS_PATH = '/wsapp'
BELTPACK_PORT_TYPE = 1          # id.type 1 is a beltpack; other kinds exist
RECONNECT_BACKOFF = (1, 2, 5, 10, 30)


class BoleroAntennaCounts:
    """Accumulates `{beltpack id -> node id}` from `audioPorts` messages.

    Pure: no sockets, no clock, no I/O. All the interesting behaviour lives here
    so it can be driven directly by tests, which is the same split the polling
    adapter uses for `_normalize`.
    """

    def __init__(self, names_by_id=None):
        self._names = dict(names_by_id or {})
        self._owner = {}                       # bp id -> node id
        self._lock = threading.Lock()

    def set_names(self, names_by_id):
        """Refresh nodeId -> antenna name, which comes from REST nodeConfig."""
        with self._lock:
            self._names = dict(names_by_id or {})

    def observe(self, message):
        """Fold one parsed websocket message in. Anything that is not an
        `audioPorts` message is ignored rather than treated as an error — the
        socket carries nodeStatus, userEventAdded and pongs on the same wire."""
        if not isinstance(message, dict):
            return
        ports = message.get('audioPorts')
        if not isinstance(ports, list):
            return
        with self._lock:
            for port in ports:
                if not isinstance(port, dict) or not port.get('registered'):
                    continue
                ident = port.get('id') or {}
                if ident.get('type') != BELTPACK_PORT_TYPE:
                    continue
                bp_id, node_id = ident.get('id'), port.get('nodeId')
                if bp_id is None or node_id is None:
                    continue
                self._owner[bp_id] = node_id   # last announcement wins

    def _name(self, node_id):
        return self._names.get(node_id) or f'Antenna {node_id}'

    def snapshot(self, packs_online):
        """Counts per antenna, or an honest refusal.

        `packs_online` is the authoritative list of connected beltpack ids, which
        comes from the REST poll — the websocket alone cannot tell us who is
        online, only who moved.

        Until every pack in that list has been seen at least once, the picture is
        incomplete, and an incomplete count that renders like a complete one is
        the exact failure this whole feature came out of. So `byAntenna` is None
        and `converged` is False until then.
        """
        with self._lock:
            online = list(packs_online or [])
            missing = [p for p in online if p not in self._owner]
            if missing:
                return {
                    'converged': False,
                    'byAntenna': None,
                    'awaiting': len(missing),
                    'packsKnown': len(self._owner),
                }
            counts = {}
            for bp_id in online:
                name = self._name(self._owner[bp_id])
                counts[name] = counts.get(name, 0) + 1
            return {
                'converged': True,
                'byAntenna': counts,
                'awaiting': 0,
                'packsKnown': len(self._owner),
            }


class BoleroAntennaListener:
    """Long-lived websocket reader feeding a `BoleroAntennaCounts`.

    Shaped to the lifecycle contract in the hardening plan's Task 3.1 —
    idempotent `start()`, idempotent `stop()`, deterministic `status()` — so the
    runtime manager can register it unchanged when it exists. It is NOT started
    by anything in the current tree.

    Read-only: the socket is used to read state. The only frame ever sent is the
    keepalive the server expects, mirroring what the Bolero GUI itself sends.
    """

    name = 'bolero-antenna'
    category = 'adapter'

    def __init__(self, host, counts, user='user', password='userPass',
                 ping_interval=20.0):
        self.host = host
        self.counts = counts
        self._user, self._password = user, password
        self._ping_interval = ping_interval
        self._thread = None
        self._stop = threading.Event()
        self._state = 'stopped'
        self._started_at = None
        self._last_success_at = None
        self._last_error_at = None
        self._last_error_summary = None
        self._message_count = 0
        self._restart_count = 0
        self._lock = threading.Lock()

    # ── lifecycle ──────────────────────────────────────────────────────────
    def start(self):
        """Idempotent: starting a running listener is harmless."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return False
            self._stop.clear()
            self._state = 'starting'
            self._started_at = time.time()
            self._thread = threading.Thread(
                target=self._run, name='five12-bolero-ws', daemon=True)
            self._thread.start()
            return True

    def stop(self, timeout=5.0):
        """Idempotent, and bounded. A listener that will not stop is reported as
        degraded rather than being allowed to hold up process exit."""
        with self._lock:
            thread = self._thread
        self._stop.set()
        if thread and thread.is_alive():
            thread.join(timeout=timeout)
            if thread.is_alive():
                with self._lock:
                    self._state = 'degraded'
                    self._last_error_summary = 'listener did not stop in time'
                return False
        with self._lock:
            self._state = 'stopped'
            self._thread = None
        return True

    def status(self):
        """Deterministic snapshot. Carries no credentials and no show data."""
        with self._lock:
            return {
                'name': self.name,
                'category': self.category,
                'state': self._state,
                'startedAt': self._started_at,
                'lastSuccessAt': self._last_success_at,
                'lastErrorAt': self._last_error_at,
                'lastErrorSummary': self._last_error_summary,
                'workCount': self._message_count,
                'restartCount': self._restart_count,
                'interface': f'ws://{self.host}{WS_PATH}' if self.host else None,
            }

    # ── the loop ───────────────────────────────────────────────────────────
    def _connect(self):
        import base64
        import websocket
        token = base64.b64encode(
            f'{self._user}:{self._password}'.encode()).decode()
        return websocket.create_connection(
            f'ws://{self.host}{WS_PATH}',
            header=[f'Authorization: Basic {token}'],
            origin=f'http://{self.host}',
            timeout=10,
        )

    def _run(self):
        import websocket
        attempt = 0
        while not self._stop.is_set():
            sock = None
            try:
                sock = self._connect()
                sock.settimeout(5)
                with self._lock:
                    self._state = 'running'
                    self._last_success_at = time.time()
                attempt = 0
                last_ping = time.time()
                while not self._stop.is_set():
                    try:
                        raw = sock.recv()
                    except websocket.WebSocketTimeoutException:
                        raw = None
                    if raw:
                        with self._lock:
                            self._message_count += 1
                            self._last_success_at = time.time()
                        try:
                            self.counts.observe(json.loads(raw))
                        except (ValueError, TypeError):
                            pass          # a frame we cannot parse is not fatal
                    if time.time() - last_ping >= self._ping_interval:
                        # the same keepalive the Bolero GUI sends
                        sock.send(json.dumps({'event': 'ping', 'data': 'ping'}))
                        last_ping = time.time()
            except Exception as exc:      # noqa: BLE001 — report, never mask
                with self._lock:
                    self._state = 'degraded'
                    self._last_error_at = time.time()
                    self._last_error_summary = f'{type(exc).__name__}: {exc}'[:200]
                    self._restart_count += 1
                log.warning('bolero websocket: %s', exc)
            finally:
                if sock is not None:
                    try:
                        sock.close()
                    except Exception:     # noqa: BLE001
                        pass
            if self._stop.is_set():
                break
            delay = RECONNECT_BACKOFF[min(attempt, len(RECONNECT_BACKOFF) - 1)]
            attempt += 1
            self._stop.wait(delay)
        with self._lock:
            self._state = 'stopped'
