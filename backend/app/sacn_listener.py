"""Passive sACN (E1.31) listener — what is live on the wire, and who is sourcing it.

Design: docs/superpowers/specs/2026-07-20-sacn-listener-design.md

Every other discovery path in this app *infers* what a device is: the ARP sweep
guesses from an OUI, Art-Net discovery matches on name strings. sACN is the one
path where a device names itself — every E1.31 packet carries a 64-byte Source
Name set by the operator on the console. On this rig that reads "Processor,
Netnumber 2, Output 1", which identifies console, net number (matching the final
IP octet) and output.

Scope note, so it is not re-litigated: this is a NETWORK-WIDE view, not a
per-device one. In E1.31 sources announce themselves; receivers announce
nothing. The Stardust is a pure receiver, so no amount of listening reveals its
patch — that is a property of the protocol, not a gap here.

Entirely passive: transmits nothing, so it is safe mid-show, and needs no admin.
Nothing is persisted — this is live state, meaningless after a restart.

Three units, split so the parsers are testable without a socket and the registry
without threads:
    parse_data_packet / parse_discovery_packet   pure bytes -> dict
    UniverseRegistry                             lock-guarded live state + TTL
    SacnListener                                 socket, joins, receive loop
"""

import logging
import os
import socket
import struct
import threading
import time
from datetime import datetime, timezone

from .local_ifaces import local_ipv4s

log = logging.getLogger(__name__)

SACN_PORT = 5568
DISCOVERY_GROUP = '239.255.250.214'

ACN_PACKET_ID = b'ASC-E1.17\x00\x00\x00'
ROOT_VECTOR_DATA = 0x00000004
ROOT_VECTOR_EXTENDED = 0x00000008
FRAMING_VECTOR_DATA = 0x00000002
FRAMING_VECTOR_DISCOVERY = 0x00000002
DISCOVERY_VECTOR_LIST = 0x00000001

# E1.31 options bits (ANSI E1.31-2018 §6.2.6). NOTE: the design doc says
# "bit 6 preview, bit 5 stream-terminated"; that is off by one against the
# standard, which the wire follows. Implemented per the standard.
OPT_PREVIEW_DATA = 0x80
OPT_STREAM_TERMINATED = 0x40

MIN_DATA_PACKET = 126        # framing layer ends at 114, DMP header at 115-125
MIN_DISCOVERY_PACKET = 120   # universe list starts at 120; an empty list is legal

# Timing. SOURCE_ACTIVE_AGE is E1.31's own source-loss timeout.
SOURCE_ACTIVE_AGE = 2.5
SOURCE_PURGE_AGE = 15.0
UNIVERSE_PURGE_AGE = 60.0
JOIN_DROP_AGE = 60.0
MAX_JOINED_UNIVERSES = 128
FPS_WINDOW = 1.0

# Baseline universes joined unconditionally at startup, never dropped.
#
# The design doc's join lifecycle joins a universe group only once a discovery
# packet names it, and recorded the risk: "sources predating E1.31-2016 do not
# send universe discovery packets and will therefore be invisible. Accepted for
# v1. If it bites in the field, the fallback is a configured baseline range."
# [VERIFIED 2026-07-21] It bit immediately — with discovery-only joins the
# listener heard nothing on a rig whose Hog processors source universes 1-6.
# So the documented fallback is now the default. 1-16 matches the range the
# proven scan-sacn.ps1 used. FIVE12_SACN_UNIVERSES overrides, e.g. "1-32" or
# "1-16,101-104"; set it empty to restore pure discovery-driven joins.
DEFAULT_BASELINE_UNIVERSES = range(1, 17)


def _parse_universe_spec(spec: str) -> set[int]:
    """Parse "1-16,101-104" into a set. Ignores malformed parts rather than
    failing startup over a typo in an env var."""
    out = set()
    for part in spec.split(','):
        part = part.strip()
        if not part:
            continue
        try:
            if '-' in part:
                lo, hi = (int(x) for x in part.split('-', 1))
                out.update(range(lo, hi + 1))
            else:
                out.add(int(part))
        except ValueError:
            log.warning('sACN: ignoring malformed universe spec %r', part)
    return {u for u in out if 1 <= u <= 63999}


def baseline_universes() -> set[int]:
    spec = os.getenv('FIVE12_SACN_UNIVERSES')
    if spec is None:
        return set(DEFAULT_BASELINE_UNIVERSES)
    return _parse_universe_spec(spec)


def _universe_group(universe: int) -> str:
    """Multicast group for a universe: 239.255.<hi>.<lo>."""
    return f'239.255.{(universe >> 8) & 0xFF}.{universe & 0xFF}'


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _valid_root(data: bytes, expected_vector: int) -> bool:
    if data[4:16] != ACN_PACKET_ID:
        return False
    return struct.unpack('!I', data[18:22])[0] == expected_vector


def _source_name(data: bytes) -> str:
    return data[44:108].split(b'\x00', 1)[0].decode('utf-8', 'replace').strip()


def _cid(data: bytes) -> str:
    return data[22:38].hex()


# ── parsers: pure, defensive, never raise ──

def parse_data_packet(data: bytes) -> dict | None:
    """Decode an E1.31 DMX data packet. None for anything else."""
    try:
        if len(data) < MIN_DATA_PACKET:
            return None
        if not _valid_root(data, ROOT_VECTOR_DATA):
            return None
        if struct.unpack('!I', data[40:44])[0] != FRAMING_VECTOR_DATA:
            return None
        options = data[112]
        return {
            'cid': _cid(data),
            'name': _source_name(data),
            'priority': data[108],
            'sequence': data[111],
            'preview': bool(options & OPT_PREVIEW_DATA),
            'terminated': bool(options & OPT_STREAM_TERMINATED),
            'universe': struct.unpack('!H', data[113:115])[0],
        }
    except (struct.error, IndexError, UnicodeError):
        return None


def parse_discovery_packet(data: bytes) -> dict | None:
    """Decode an E1.31 universe discovery packet. None for anything else."""
    try:
        if len(data) < MIN_DISCOVERY_PACKET:
            return None
        if not _valid_root(data, ROOT_VECTOR_EXTENDED):
            return None
        if struct.unpack('!I', data[40:44])[0] != FRAMING_VECTOR_DISCOVERY:
            return None
        if struct.unpack('!I', data[114:118])[0] != DISCOVERY_VECTOR_LIST:
            return None
        body = data[120:]
        # A trailing odd byte means a truncated list; drop it rather than
        # inventing a universe from one byte.
        universes = [u[0] for u in struct.iter_unpack('!H', body[:len(body) - len(body) % 2])]
        return {
            'cid': _cid(data),
            'name': _source_name(data),
            'page': data[118],
            'lastPage': data[119],
            'universes': universes,
        }
    except (struct.error, IndexError, UnicodeError):
        return None


# ── registry ──

class UniverseRegistry:
    """Live universe/source state. `clock` is injectable so expiry is testable
    without sleeping."""

    def __init__(self, clock=time.time):
        self._clock = clock
        self._lock = threading.Lock()
        # universe -> {'announcedAt': float|None, 'sources': {cid -> source}}
        self._universes: dict[int, dict] = {}

    def _universe(self, universe: int) -> dict:
        entry = self._universes.get(universe)
        if entry is None:
            entry = {'announcedAt': None, 'sources': {}}
            self._universes[universe] = entry
        return entry

    def record_data(self, packet: dict, src_ip: str) -> None:
        now = self._clock()
        with self._lock:
            entry = self._universe(packet['universe'])
            # A terminated stream is gone immediately — waiting out the TTL
            # would show a dead source as live for 15s.
            if packet['terminated']:
                entry['sources'].pop(packet['cid'], None)
                return
            src = entry['sources'].get(packet['cid'])
            if src is None:
                src = {'name': packet['name'], 'ip': src_ip, 'priority': 0,
                       'sequence': 0, 'lastSeen': 0.0, '_ticks': []}
                entry['sources'][packet['cid']] = src
                log.info('sACN: universe %d source %s "%s"',
                         packet['universe'], src_ip, packet['name'])
            # Newest wins: the operator can rename or re-prioritise mid-session.
            src['name'] = packet['name']
            src['ip'] = src_ip
            src['priority'] = packet['priority']
            src['sequence'] = packet['sequence']
            src['lastSeen'] = now
            src['_ticks'].append(now)
            src['_ticks'] = [t for t in src['_ticks'] if t > now - FPS_WINDOW]

    def record_discovery(self, packet: dict) -> None:
        now = self._clock()
        with self._lock:
            for universe in packet['universes']:
                self._universe(universe)['announcedAt'] = now

    def expire(self) -> None:
        now = self._clock()
        with self._lock:
            for universe, entry in list(self._universes.items()):
                for cid, src in list(entry['sources'].items()):
                    if src['lastSeen'] < now - SOURCE_PURGE_AGE:
                        del entry['sources'][cid]
                announced = entry['announcedAt']
                stale_announce = announced is None or announced < now - UNIVERSE_PURGE_AGE
                if not entry['sources'] and stale_announce:
                    del self._universes[universe]

    def announced_universes(self) -> set[int]:
        """Universes worth holding a multicast join for — anything named by
        discovery or currently sourced."""
        now = self._clock()
        with self._lock:
            return {u for u, e in self._universes.items()
                    if (e['announcedAt'] is not None
                        and e['announcedAt'] > now - JOIN_DROP_AGE)
                    or any(s['lastSeen'] > now - JOIN_DROP_AGE
                           for s in e['sources'].values())}

    def snapshot(self) -> list[dict]:
        """API shape, universes ascending. A universe's top-level priority is
        the highest among its ACTIVE sources — the one a compliant receiver
        would actually follow."""
        now = self._clock()
        out = []
        with self._lock:
            for universe in sorted(self._universes):
                entry = self._universes[universe]
                sources = []
                for cid, src in entry['sources'].items():
                    active = src['lastSeen'] > now - SOURCE_ACTIVE_AGE
                    sources.append({
                        'cid': cid,
                        'name': src['name'],
                        'ip': src['ip'],
                        'priority': src['priority'],
                        'fps': len(src['_ticks']),
                        'active': active,
                        'lastSeen': _iso(src['lastSeen']),
                    })
                sources.sort(key=lambda s: (-s['priority'], s['ip']))
                active_priorities = [s['priority'] for s in sources if s['active']]
                out.append({
                    'universe': universe,
                    'active': bool(active_priorities),
                    'priority': max(active_priorities) if active_priorities else None,
                    'sources': sources,
                })
        return out


# ── listener ──

class SacnListener:
    def __init__(self, registry: UniverseRegistry | None = None):
        self.registry = registry or UniverseRegistry()
        self.interfaces: list[str] = []
        self.error: str | None = None
        self.listening = False
        self._sock: socket.socket | None = None
        self._joined: set[int] = set()
        self._baseline: set[int] = baseline_universes()
        self._capped_logged = False

    # -- socket --

    def _open_socket(self) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # MUST bind INADDR_ANY, not the interface's unicast IP. Binding the
        # unicast IP — the intuitive thing, and what the Art-Net unicast path
        # correctly does — silently receives ZERO multicast on Windows.
        # [VERIFIED 2026-07-20] Do not "fix" this back.
        sock.bind(('', SACN_PORT))
        sock.settimeout(1.0)
        return sock

    def _membership(self, universe_group: str, op: int) -> int:
        """Add or drop `universe_group` on every local interface. Returns how
        many succeeded; a failure on one interface must not affect the others."""
        ok = 0
        for iface in self.interfaces:
            try:
                mreq = socket.inet_aton(universe_group) + socket.inet_aton(iface or '0.0.0.0')
                self._sock.setsockopt(socket.IPPROTO_IP, op, mreq)
                ok += 1
            except OSError as exc:
                log.debug('sACN: membership %s on %s failed — %s',
                          universe_group, iface, exc)
        return ok

    def _reconcile_joins(self) -> None:
        # Baseline universes are always wanted, so a source that never sends
        # discovery packets stays audible even after it falls silent and its
        # registry entry expires.
        wanted = self.registry.announced_universes() | self._baseline
        if len(wanted) > MAX_JOINED_UNIVERSES:
            if not self._capped_logged:
                log.warning('sACN: %d universes announced, capping joins at %d',
                            len(wanted), MAX_JOINED_UNIVERSES)
                self._capped_logged = True
            wanted = set(sorted(wanted)[:MAX_JOINED_UNIVERSES])

        for universe in wanted - self._joined:
            if self._membership(_universe_group(universe), socket.IP_ADD_MEMBERSHIP):
                self._joined.add(universe)
                log.info('sACN: joined universe %d', universe)
        for universe in self._joined - wanted:
            self._membership(_universe_group(universe), socket.IP_DROP_MEMBERSHIP)
            self._joined.discard(universe)
            log.info('sACN: dropped universe %d (silent %.0fs)',
                     universe, JOIN_DROP_AGE)

    # -- loop --

    def run(self) -> None:
        self.interfaces = local_ipv4s('FIVE12_SACN_SRC')
        try:
            self._sock = self._open_socket()
        except OSError as exc:
            # Port 5568 already held (a visualiser, or a second worker) is the
            # common case. Record it so the API can say WHY it sees nothing
            # rather than implying a quiet wire.
            self.error = f'cannot bind UDP {SACN_PORT}: {exc}'
            log.error('sACN: %s', self.error)
            return

        if not self._membership(DISCOVERY_GROUP, socket.IP_ADD_MEMBERSHIP):
            self.error = 'joined no interface for the discovery group'
            log.error('sACN: %s', self.error)
            return

        self._reconcile_joins()   # baseline universes, before the first packet
        self.listening = True
        log.info('sACN: listening on :%d across %d interface(s), baseline '
                 'universes %s', SACN_PORT, len(self.interfaces),
                 f'{min(self._baseline)}-{max(self._baseline)}'
                 if self._baseline else '(none, discovery-driven)')

        next_tick = time.time() + 1.0
        while True:
            try:
                data, addr = self._sock.recvfrom(1144)
                packet = parse_data_packet(data)
                if packet:
                    # Preview data is a console's blind/preview stream, not
                    # what is live on the wire. Counting it would show phantom
                    # sources on universes nothing is actually outputting.
                    if not packet['preview']:
                        self.registry.record_data(packet, addr[0])
                else:
                    discovery = parse_discovery_packet(data)
                    if discovery:
                        self.registry.record_discovery(discovery)
            except socket.timeout:
                pass
            except OSError as exc:
                log.error('sACN: receive error: %s', exc)
                time.sleep(1)

            if time.time() >= next_tick:
                next_tick = time.time() + 1.0
                self.registry.expire()
                try:
                    self._reconcile_joins()
                except Exception as exc:
                    # Join bookkeeping must never kill the listener; the next
                    # tick retries and the registry stays correct meanwhile.
                    log.error('sACN: join reconcile failed: %s', exc)

    def api_state(self) -> dict:
        if not self.listening:
            return {'listening': False,
                    'error': self.error or 'listener not started',
                    'interfaces': self.interfaces,
                    'universes': []}
        return {'listening': True,
                'error': None,
                'interfaces': self.interfaces,
                'universes': self.registry.snapshot()}


# ── module singleton ──

_listener: SacnListener | None = None


def get_listener() -> SacnListener | None:
    return _listener


def start_sacn_listener(app=None) -> SacnListener:
    """Start the receive thread once per process. `app` is accepted for
    symmetry with start_scanner but unused — nothing here touches the DB."""
    global _listener
    if _listener is not None:
        return _listener
    _listener = SacnListener()
    threading.Thread(target=_listener.run, daemon=True,
                     name='sacn-listener').start()
    return _listener
