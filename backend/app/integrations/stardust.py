"""LumenRadio Stardust adapter — RDM-over-Art-Net (the standards path).

[VERIFIED] Stardust is an 8-universe DMX/RDM wireless transmitter speaking
sACN and Art-Net, and exposes RDM to third-party controllers via
RDM-over-Art-Net. That is the clean integration surface; the web UI is
deliberately NOT scraped (the fragile/SSRF pattern this codebase removed).

Implementation: minimal Art-Net UDP (port 6454):
  * ArtPoll (OpPoll 0x2000) broadcast -> ArtPollReply (0x2100) to find nodes
    and identify LumenRadio by the short/long name fields.
  * ArtTodRequest (OpTodRequest 0x8000) -> ArtTodData (0x8100) per universe
    to enumerate downstream RDM UIDs (6 bytes each).
Packet layouts follow the Art-Net 4 spec; parsing is defensive
[NEEDS VERIFICATION against a real Stardust for name strings / port config].

Fetching each fixture's DMX_START_ADDRESS needs full RDM GET via OpRdm
(0x8300) — marked v2. In v1 the patch reconciliation compares what RDM
discovery reports (sim provides addresses; real mode provides UIDs) against
the PatchSheet.

Almost entirely read-only: discovery only, no RDM SETs, no config writes.
The ONE exception is link_output() — a user-triggered CRMX LinkCommand over
/ws that puts an output into pairing mode. No other frame is ever written.
"""

import logging
import math
import os
import select
import socket
import struct
import threading
import time

from . import DeviceAdapter, check_thresholds, require_private_host
from ..local_ifaces import local_ipv4s

log = logging.getLogger(__name__)

ARTNET_PORT = 6454
POLL_TIMEOUT = 1.2
# A Stardust answers the broadcast ArtPoll only intermittently, and a single
# lost datagram would otherwise blank the whole panel. Re-broadcast this often
# inside the POLL_TIMEOUT window so one dropped poll is not fatal — the loop
# already listens the full window, so this adds packets, not latency.
POLL_RESEND_SEC = 0.4
# How long a just-seen unit stays "available" through a poll that misses it.
# Bridges brief discovery gaps at the source (backend) so the UI stops flapping
# RECONNECTING; longer than NODES_TTL, shorter than the frontend's hold window.
STARDUST_STICKY_SEC = 12.0
# Discovery binds UDP 6454 and listens ~POLL_TIMEOUT. The status, units, and
# detect polls each call it on their own cadence; when two overlap they compete
# for the single ArtPollReply (SO_REUSEADDR hands each datagram to only one
# socket), so a unit that answers one poll vanishes from the other. Serialize
# discovery and let all callers share a result this fresh.
NODES_TTL = 2.5
# (Net<<8)|(Sub<<4)|SwOut with every bit set — Art-Net's "port not assigned to
# a universe" sentinel. [VERIFIED 2026-07-20] a Stardust reports 32767 on all
# eight replies, so it must never be shown as a real universe.
UNIVERSE_UNASSIGNED = 0x7FFF
WS_TIMEOUT = 2.5   # seconds; ws://<ip>/ws connect + read budget for outputs
LINK_TIMEOUT = 3.0  # seconds; wait budget for the device's LinkingStarted reply
# The outputs config changes rarely, but the /ws fetch costs ~WS_TIMEOUT and
# would otherwise run on every fast status poll — enough to make the whole
# panel flap. Fetch it at most this often and serve the last good result in
# between; a failed refresh keeps the cached outputs rather than blanking them.
OUTPUTS_TTL = 20.0
OP_POLL = 0x2000
OP_POLL_REPLY = 0x2100
OP_TOD_REQUEST = 0x8000
OP_TOD_DATA = 0x8100
HEADER = b'Art-Net\x00'

ALERT_RULES = [
    ('universesDown', 'gt', 0, '{value} universe(s) not transmitting', 'crit'),
    ('weakestRfPct', 'lt', 30, 'RF link at {value}% on a universe', 'warn'),
]


def _artpoll_packet():
    # Art-Net 4: ID, OpPoll (lo-hi), ProtVer 14 (hi-lo), Flags, Priority
    return HEADER + struct.pack('<H', OP_POLL) + struct.pack('>H', 14) + bytes([0x00, 0x00])


def _tod_request_packet(net, subuni):
    # ID, OpTodRequest, ProtVer, filler(2), spare(7), Net, Command(0=TodFull),
    # AddCount(1), Address[1]
    return (HEADER + struct.pack('<H', OP_TOD_REQUEST) + struct.pack('>H', 14)
            + bytes(2) + bytes(7) + bytes([net & 0x7F, 0x00, 1, subuni & 0xFF]))


def _parse_poll_reply(data):
    if len(data) < 207 or not data.startswith(HEADER):
        return None
    op = struct.unpack('<H', data[8:10])[0]
    if op != OP_POLL_REPLY:
        return None
    ip = '.'.join(str(b) for b in data[10:14])
    firmware = '%d.%d' % (data[16], data[17])   # VersInfoH.VersInfoL
    esta = '0x%02X%02X' % (data[25], data[24])  # EstaManHi, EstaManLo ("LU"=LumenRadio)
    short_name = data[26:44].split(b'\x00')[0].decode('latin-1', 'replace')
    long_name = data[44:108].split(b'\x00')[0].decode('latin-1', 'replace')
    # MAC at offset 201 (Art-Net 4 ArtPollReply). Uppercase colon form to
    # match the ARP scanner's NetworkDevice keys so labels unify across both
    # discovery paths. [VERIFIED against a live Stardust 2026-07-20: MAC,
    # names, firmware, and ESTA code all parse correctly.]
    mac = ':'.join('%02X' % b for b in data[201:207])
    # Output ports. Art-Net caps one reply at 4 ports; a node with more sends
    # several replies (one per port group) that _discover_nodes merges by MAC.
    # NetSwitch/SubSwitch are read PER REPLY — [VERIFIED 2026-07-20] a Swisson
    # port with SubSwitch=6, SwOut=5 is universe 101, which a device-wide
    # SubSwitch would get wrong.
    ports = []
    for p in range(min(4, data[173])):
        universe = (data[18] << 8) | (data[19] << 4) | (data[190 + p] & 0x0F)
        if universe == UNIVERSE_UNASSIGNED:
            continue
        ports.append({'universe': universe,
                      # GoodOutput bit7 = "data is being transmitted"
                      'transmitting': bool(data[182 + p] & 0x80)})
    return {'ip': ip, 'mac': mac, 'shortName': short_name, 'longName': long_name,
            'firmware': firmware, 'estaMan': esta, 'ports': ports}


def _parse_tod_data(data):
    if len(data) < 28 or not data.startswith(HEADER):
        return None
    op = struct.unpack('<H', data[8:10])[0]
    if op != OP_TOD_DATA:
        return None
    # Port(1)@12? layout: ProtVer, RdmVer, Port, spare(6), BindIndex, Net,
    # CommandResponse, Address, UidTotalHi/Lo, BlockCount, UidCount, UIDs...
    subuni = data[23]
    uid_count = data[27]
    uids = []
    off = 28
    for _ in range(uid_count):
        if off + 6 > len(data):
            break
        raw = data[off:off + 6]
        uids.append('{:02X}{:02X}:{:02X}{:02X}{:02X}{:02X}'.format(*raw))
        off += 6
    return {'subuni': subuni, 'uids': uids}


def universes_outputting(node):
    """Universes this node reports as actively transmitting (ArtPollReply)."""
    return sorted({p['universe'] for p in node.get('ports', []) if p['transmitting']})


# ── Stardust control plane (WebSocket) — per-output config ──────────────────
# The LumenRadio GUI drives everything over ws://<ip>/ws with JSON _type_ frames
# [VERIFIED 2026-07-22 from the GUI bundle main.7bc0d075.chunk.js]. We poll it
# READ-ONLY for the outputs config (source universe + CRMX radio type) that
# Art-Net cannot provide. We send ONLY Get* frames, never a Settings frame.

OUTPUT_LETTERS = {1: 'A', 2: 'B', 3: 'C', 4: 'D', 5: 'E', 6: 'F', 7: 'G', 8: 'H'}

# rf_protocols[i] raw enum -> label, keyed by device output count N. CRMX2 can
# be split across outputs, so the same raw value reads differently by N.
# Transcribed verbatim from the bundle's `It` table.
CRMX_LABELS = {
    2: {'CRMX': 'CRMX Classic', 'CRMX2_1_4': 'CRMX²',
        'WDMX_G3': 'W-DMX G3', 'WDMX_G4S': 'W-DMX G4S'},
    4: {'CRMX': 'CRMX Classic', 'CRMX2_1_4': '1/2 CRMX²',
        'CRMX2_2_4': 'CRMX²', 'WDMX_G3': 'W-DMX G3', 'WDMX_G4S': 'W-DMX G4S'},
    6: {'CRMX': 'CRMX Classic', 'CRMX2_1_4': '1/3 CRMX²',
        'CRMX2_2_4': '2/3 CRMX²', 'CRMX2_3_4': 'CRMX²',
        'WDMX_G3': 'W-DMX G3', 'WDMX_G4S': 'W-DMX G4S'},
    8: {'CRMX': 'CRMX Classic', 'CRMX2_1_4': '1/4 CRMX²',
        'CRMX2_2_4': '2/4 CRMX²', 'CRMX2_3_4': '3/4 CRMX²',
        'CRMX2': 'CRMX²', 'WDMX_G3': 'W-DMX G3', 'WDMX_G4S': 'W-DMX G4S'},
}


def _output_letter(n):
    """Output/universe number (1-based) -> letter A..H, matching the GUI."""
    return OUTPUT_LETTERS.get(n, ' ')


def _artnet_addr(v):
    """Art-Net universe int -> 'net/sub/uni', decoded exactly as the GUI does."""
    return '{}/{}/{}'.format((v >> 8) & 0x7F, (v >> 4) & 0x0F, v & 0x0F)


def _crmx_label(raw, n):
    """Raw rf_protocols enum + device output count -> friendly CRMX label.
    Unknown N falls back to the 8-output table; unknown raw returns verbatim."""
    return CRMX_LABELS.get(n, CRMX_LABELS[8]).get(raw, raw)


def _merge_outputs(timo, sacn, artnet):
    """Join the three /ws GetSettings payloads into a per-output list.

    timo:   dmx_sink.timo_sink settings (universe_nrs, output_names,
            output_powers_mw, rf_protocols, enabled_universe_nrs).
    sacn:   dmx_source.sacn_source settings; universe_map {sacnUniverse:[outNr]}.
    artnet: dmx_source.artnet_source settings; universe_map {outNr: addrInt}.

    Returns a list of per-output dicts sorted by output letter:
      {output, name, source, universe, crmxType, powerMw, enabled}
    source is 'sACN' / 'ArtNet' / 'None'; universe is the sACN universe number
    (str), the ArtNet 'net/sub/uni' (str), or None.
    """
    nrs = timo.get('universe_nrs', []) or []
    names = timo.get('output_names', []) or []
    powers = timo.get('output_powers_mw', []) or []
    protocols = timo.get('rf_protocols', []) or []
    enabled = set(timo.get('enabled_universe_nrs', []) or [])
    n = len(nrs)

    # sACN map is universe -> [outputs]; invert to output -> universe.
    sacn_by_output = {}
    for uni, outs in (sacn.get('universe_map', {}) or {}).items():
        for out in outs or []:
            sacn_by_output[out] = str(uni)
    artnet_map = artnet.get('universe_map', {}) or {}

    outputs = []
    for i, out_nr in enumerate(nrs):
        source, universe = 'None', None
        if out_nr in sacn_by_output:
            source, universe = 'sACN', sacn_by_output[out_nr]
        else:
            addr = artnet_map.get(str(out_nr), artnet_map.get(out_nr))
            if addr is not None:
                source, universe = 'ArtNet', _artnet_addr(int(addr))
        outputs.append({
            'output': _output_letter(out_nr),
            'outputNr': out_nr,
            'name': names[i] if i < len(names) else None,
            'source': source,
            'universe': universe,
            'crmxType': _crmx_label(protocols[i] if i < len(protocols) else None, n),
            'powerMw': powers[i] if i < len(powers) else None,
            'enabled': out_nr in enabled,
        })
    outputs.sort(key=lambda o: o['output'])
    return outputs


def _local_ipv4s():
    """Every local IPv4 to poll from. Thin wrapper kept so this call site and
    the FIVE12_ARTNET_SRC pin read exactly as before; the implementation moved
    to app/local_ifaces.py to be shared with the sACN listener."""
    return local_ipv4s('FIVE12_ARTNET_SRC')


class StardustAdapter(DeviceAdapter):
    id = 'stardust'
    name = 'LumenRadio Stardust'

    def __init__(self, sim=False):
        super().__init__()
        self.sim = sim
        self._sim_t0 = time.time()
        # Optional pin: unicast target instead of broadcast discovery
        self.host = os.getenv('FIVE12_STARDUST_HOST', '').strip() or None
        # Throttled cache for the /ws outputs config (see OUTPUTS_TTL).
        self._outputs_cache = None
        self._outputs_cache_at = 0.0
        self._outputs_cache_host = None
        # Why the last outputs fetch failed, in operator-facing words, or None.
        # Surfaced as status['outputsError'] so an empty grid always says why.
        self._outputs_error = None
        # Shared, serialized Art-Net discovery (see NODES_TTL).
        self._nodes_cache = None
        self._nodes_cache_at = 0.0
        self._nodes_lock = threading.Lock()
        # Last sighting per unit (mac -> {'node', 'at'}), for sticky availability
        # (see STARDUST_STICKY_SEC) — holds a unit up through a missed poll
        # without leaking one unit's reading into another.
        self._last_seen = {}

    # ── Art-Net plumbing ──
    def _open_socket(self, src='', timeout=POLL_TIMEOUT):
        """Bind a UDP socket to `src` on the fixed Art-Net port.

        Port 6454 rather than an ephemeral one because ArtPollReply/ArtTodData
        are sent back to 6454, not to the sender's port. SO_REUSEADDR must be
        set before bind() so several interfaces can hold the same port at once.
        """
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(timeout)
        s.bind((src, ARTNET_PORT))
        return s

    def _discover_nodes(self):
        """ArtPoll from every local interface; tag each node with the source
        IP that heard it ('via') so later unicast can bind the same one."""
        target = '255.255.255.255'
        if self.host:
            target = require_private_host(self.host)

        socks = {}
        for src in _local_ipv4s():
            try:
                socks[self._open_socket(src)] = src
            except OSError as exc:
                # One unusable interface (port contention, adapter down) must
                # not sink discovery on the others.
                log.debug('Art-Net: cannot bind %s:%d — %s', src, ARTNET_PORT, exc)
        if not socks:
            raise OSError(f'no bindable interface on port {ARTNET_PORT}')

        def _broadcast():
            for s, src in socks.items():
                try:
                    s.sendto(_artpoll_packet(), (target, ARTNET_PORT))
                except OSError as exc:
                    log.debug('Art-Net: poll from %s failed — %s', src, exc)

        nodes = {}
        try:
            # select() across all sockets against one shared deadline: reading
            # them serially would burn the whole window blocked on the first
            # quiet interface and never reach the one that can hear replies.
            # Re-broadcast every POLL_RESEND_SEC and listen the full window
            # (never early-break) so a unit whose first reply was lost still
            # gets counted from a later one.
            deadline = time.time() + POLL_TIMEOUT
            next_send = 0.0
            while True:
                now = time.time()
                remaining = deadline - now
                if remaining <= 0:
                    break
                if now >= next_send:
                    _broadcast()
                    next_send = now + POLL_RESEND_SEC
                ready, _, _ = select.select(list(socks), [], [], min(remaining, POLL_RESEND_SEC))
                if not ready:
                    continue
                for s in ready:
                    try:
                        data, _addr = s.recvfrom(2048)
                    except OSError:
                        continue
                    node = _parse_poll_reply(data)
                    if not node:
                        continue
                    # Identity dedupes by MAC (one physical unit = one row),
                    # but PORTS must merge across replies: an 8-port node
                    # sends 8 replies sharing one MAC, so first-reply-wins
                    # would silently discard seven of its universes.
                    known = nodes.get(node['mac'])
                    if known is None:
                        node['via'] = socks[s]
                        nodes[node['mac']] = node
                        continue
                    by_uni = {p['universe']: p for p in known['ports']}
                    for p in node['ports']:
                        if p['universe'] in by_uni:
                            # Two ports on the same universe: outputting on
                            # either one means the universe is on air.
                            by_uni[p['universe']]['transmitting'] |= p['transmitting']
                        else:
                            known['ports'].append(p)
                            by_uni[p['universe']] = p
        finally:
            for s in socks:
                s.close()
        return list(nodes.values())

    def _discover_nodes_cached(self):
        """Serialized, briefly-cached wrapper around _discover_nodes.

        The lock guarantees only one poll listens on 6454 at a time (removing
        the reply contention between overlapping status/units/detect polls), and
        NODES_TTL lets a second caller reuse a poll this recent instead of
        launching its own. Errors propagate uncached so callers still see them.
        """
        now = time.time()
        if self._nodes_cache is not None and now - self._nodes_cache_at < NODES_TTL:
            return self._nodes_cache
        with self._nodes_lock:
            # A peer may have refreshed the cache while we waited for the lock.
            now = time.time()
            if self._nodes_cache is not None and now - self._nodes_cache_at < NODES_TTL:
                return self._nodes_cache
            nodes = self._discover_nodes()
            self._nodes_cache = nodes
            self._nodes_cache_at = time.time()
            return nodes

    @staticmethod
    def _is_stardust(node):
        blob = (node['shortName'] + ' ' + node['longName']).lower()
        return 'stardust' in blob or 'lumenradio' in blob or 'crmx' in blob

    def discover_units(self):
        """All Stardust units on the network, each with its MAC — the basis for
        MAC-persistent labels ('which physical unit is this?'). Read-only."""
        if self.sim:
            return self._sim_units()
        try:
            nodes = self._discover_nodes_cached()
        except (OSError, ValueError):
            return []
        return [{'mac': n['mac'], 'ip': n['ip'],
                 'shortName': n['shortName'], 'longName': n['longName'],
                 'firmware': n.get('firmware'), 'estaMan': n.get('estaMan'),
                 'via': n.get('via', ''),
                 'universesOutputting': universes_outputting(n)}
                for n in nodes if self._is_stardust(n)]

    @staticmethod
    def _sim_units():
        # Stable fake MACs so a label set in sim persists across polls/restart.
        return [
            {'mac': '00:1A:2B:00:00:01', 'ip': '10.0.0.80',
             'shortName': 'Stardust', 'longName': 'Stardust DTx8 (sim A)'},
            {'mac': '00:1A:2B:00:00:02', 'ip': '10.0.0.81',
             'shortName': 'Stardust', 'longName': 'Stardust DTx8 (sim B)'},
        ]

    def detect(self):
        if self.sim:
            return {'found': True, 'address': '10.0.0.80', 'detail': 'simulated'}
        try:
            nodes = self._discover_nodes_cached()
        except (OSError, ValueError) as exc:
            return {'found': False, 'address': None, 'detail': f'Art-Net poll failed: {exc}'}
        hits = [n for n in nodes if self._is_stardust(n)]
        if hits:
            return {'found': True, 'address': hits[0]['ip'],
                    'detail': hits[0]['longName'] or hits[0]['shortName']}
        return {'found': False, 'address': None,
                'detail': f'{len(nodes)} Art-Net node(s) found, none LumenRadio'}

    def _ws_fetch_settings(self, ip):
        """Poll the Stardust control plane at ws://ip/ws for the outputs config.

        Read-only: sends only the three Get*Command frames and reads until all
        three responses arrive or WS_TIMEOUT elapses. Returns (timo, sacn,
        artnet) settings dicts; a missing response comes back as {}. Host is
        re-validated as private every call and never derived from request input.
        """
        import json
        import websocket   # websocket-client
        ip = require_private_host(ip)
        wanted = {
            'dmx_sink.timo_sink.GetSettingsResponse': 'timo',
            'dmx_source.sacn_source.GetSettingsResponse': 'sacn',
            'dmx_source.artnet_source.GetSettingsResponse': 'artnet',
        }
        commands = (
            '{"_type_":"dmx_sink.timo_sink.GetSettingsCommand"}',
            '{"_type_":"dmx_source.sacn_source.GetSettingsCommand"}',
            '{"_type_":"dmx_source.artnet_source.GetSettingsCommand"}',
        )
        got = {}
        ws = websocket.create_connection(f'ws://{ip}/ws', timeout=WS_TIMEOUT)
        try:
            for cmd in commands:
                ws.send(cmd)
            deadline = time.time() + WS_TIMEOUT
            while len(got) < len(wanted) and time.time() < deadline:
                try:
                    msg = json.loads(ws.recv())
                except (ValueError, websocket.WebSocketTimeoutException):
                    break
                key = wanted.get(msg.get('_type_'))
                if key:
                    got[key] = msg.get('settings', {}) or {}
        finally:
            ws.close()
        return got.get('timo', {}), got.get('sacn', {}), got.get('artnet', {})

    def _cached_outputs(self, ws_host):
        """Merged outputs for ws_host, refetched over /ws at most every
        OUTPUTS_TTL so the slow WS poll stays out of the hot status path.

        Returns the last good list (or None). A stale entry triggers one
        refetch; a failed refetch logs and keeps whatever was cached. Changing
        ws_host invalidates the cache so a moved/renamed unit refetches at once.

        Every failure path records a reason in self._outputs_error. This used
        to be one blanket `except Exception` that logged and moved on, which
        meant a missing Python package and a fixture that had walked out of
        range produced identical, invisible results: an empty grid, no error,
        nothing to tell them apart from the UI. Best-effort is right for the
        DEVICE being unreachable; it is wrong for a broken install.
        """
        now = time.time()
        fresh = (self._outputs_cache_host == ws_host
                 and now - self._outputs_cache_at < OUTPUTS_TTL)
        if fresh:
            return self._outputs_cache

        try:
            timo, sacn, artnet = self._ws_fetch_settings(ws_host)
        except ImportError as exc:
            # NOT best-effort. websocket-client is pinned in requirements.txt,
            # so its absence is a broken server install, not a device
            # condition, and it will never fix itself by retrying.
            self._outputs_error = (
                'The server cannot read output configuration: the '
                'websocket-client package is not installed. Run '
                '"pip install -r backend/requirements.txt" and restart.'
            )
            log.error('Stardust /ws outputs unavailable — missing dependency: %s', exc)
            return self._outputs_cache
        except Exception as exc:  # noqa: BLE001 — the unit itself is best-effort
            self._outputs_error = (
                f'Could not read output configuration from {ws_host}. '
                f'The unit may be busy, rebooting, or off the network '
                f'({type(exc).__name__}).'
            )
            log.warning('Stardust /ws outputs fetch failed for %s: %s', ws_host, exc)
            return self._outputs_cache

        if not timo.get('universe_nrs'):
            # Answered, but with nothing usable. Distinct from "did not answer".
            self._outputs_error = (
                f'{ws_host} responded but reported no output configuration.'
            )
            log.warning('Stardust /ws returned no universe_nrs from %s', ws_host)
            return self._outputs_cache

        self._outputs_cache = _merge_outputs(timo, sacn, artnet)
        self._outputs_cache_at = now
        self._outputs_cache_host = ws_host
        self._outputs_error = None
        return self._outputs_cache

    # ── control: CRMX linking (the ONE deliberate write) ──
    # Everything else in this adapter is read-only. link_output is the single
    # exception: a user-triggered command that puts one output into CRMX
    # linking mode so a receiver can pair. We send ONLY the LinkCommand frame
    # (never Settings, never Unlink — Unlink is intentionally not exposed).
    def _ws_open(self, ip):
        """Open the Stardust control-plane socket. Host re-validated private."""
        import websocket   # websocket-client
        return websocket.create_connection(
            f'ws://{require_private_host(ip)}/ws', timeout=WS_TIMEOUT)

    def _stardust_ip(self, mac=None):
        """Current IP of the target Stardust: fresh discovery, else its last
        sighting, else the pinned host. Linking has to reach the actual unit."""
        try:
            hits = [n for n in self._discover_nodes_cached() if self._is_stardust(n)]
            if mac is not None:
                hits = [n for n in hits if n['mac'] == mac]
            if hits:
                return hits[0]['ip']
        except (OSError, ValueError):
            pass
        node = self._sticky_node(mac)
        if node:
            return node.get('ip')
        return self.host if mac is None else None

    @staticmethod
    def _await_type(ws, wanted_type, timeout):
        import json
        import websocket
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                msg = json.loads(ws.recv())
            except (ValueError, websocket.WebSocketTimeoutException):
                break
            if isinstance(msg, dict) and msg.get('_type_') == wanted_type:
                return True
        return False

    def link_output(self, out_nr, mac=None):
        """Put output `out_nr` (1..8) on the given unit into CRMX linking mode.

        The integration's one write: sends a single
        dmx_sink.timo_sink.LinkCommand over ws://<ip>/ws and waits briefly for
        the device's LinkingStarted confirmation. Read-only otherwise. `mac`
        selects which unit when several are on the network.
        """
        if isinstance(out_nr, bool) or not isinstance(out_nr, int) or not (1 <= out_nr <= 8):
            raise ValueError(f'output number must be an int 1..8, got {out_nr!r}')
        letter = _output_letter(out_nr)
        if self.sim:
            return {'ok': True, 'outputNr': out_nr, 'output': letter, 'sim': True}
        ip = self._stardust_ip(mac)
        if not ip:
            return {'ok': False, 'outputNr': out_nr, 'output': letter,
                    'reason': 'Stardust not found on network'}
        import json
        frame = json.dumps({'universe_nrs': [out_nr],
                            '_type_': 'dmx_sink.timo_sink.LinkCommand'})
        try:
            ws = self._ws_open(ip)
        except Exception as exc:  # noqa: BLE001
            return {'ok': False, 'outputNr': out_nr, 'output': letter,
                    'reason': f'link failed: {exc}'}
        try:
            ws.send(frame)
            started = self._await_type(ws, 'dmx_sink.timo_sink.LinkingStarted', LINK_TIMEOUT)
        finally:
            ws.close()
        return {'ok': started, 'outputNr': out_nr, 'output': letter,
                'reason': None if started else 'no LinkingStarted confirmation'}

    # ── status + RDM TOD ──
    def get_status(self, mac=None):
        status = self._sim_status() if self.sim else self._real_status(mac)
        status['alerts'] = check_thresholds(status, ALERT_RULES)
        if status.get('available'):
            self.history.record({
                'universesUp': status.get('universesUp'),
                'weakestRfPct': status.get('weakestRfPct'),
                'fixturesDiscovered': status.get('fixturesDiscovered'),
            })
        return status

    def _sticky_node(self, mac=None):
        """The last Stardust seen, within STARDUST_STICKY_SEC — holds a unit up
        through a momentary discovery miss instead of flapping RECONNECTING.
        With a MAC, only that unit's sighting counts; without, the most recent
        still-fresh sighting (the default 'a Stardust' view)."""
        now = time.time()
        if mac is not None:
            e = self._last_seen.get(mac)
            return e['node'] if e and now - e['at'] < STARDUST_STICKY_SEC else None
        fresh = [e for e in self._last_seen.values() if now - e['at'] < STARDUST_STICKY_SEC]
        return max(fresh, key=lambda e: e['at'])['node'] if fresh else None

    def _real_status(self, mac=None):
        # Discover directly rather than via detect() so the node's 'via'
        # survives — the TOD unicast has to leave the same interface that
        # heard the ArtPollReply or it goes out the default route and dies.
        try:
            nodes = self._discover_nodes_cached()
        except (OSError, ValueError) as exc:
            node = self._sticky_node(mac)
            if node is None:
                return {'available': False, 'reason': f'Art-Net poll failed: {exc}'}
            return self._status_from_node(node, stale=True)
        hits = [n for n in nodes if self._is_stardust(n)]
        if mac is not None:
            hits = [n for n in hits if n['mac'] == mac]
        if hits:
            node = hits[0]
            self._last_seen[node['mac']] = {'node': node, 'at': time.time()}
            return self._status_from_node(node, stale=False)
        # Missed the unit this poll — hold the last good reading if it was seen
        # moments ago, otherwise report it genuinely gone.
        node = self._sticky_node(mac)
        if node is None:
            reason = (f'Stardust {mac} not found' if mac is not None
                      else f'{len(nodes)} Art-Net node(s) found, none LumenRadio')
            return {'available': False, 'reason': reason}
        return self._status_from_node(node, stale=True)

    def _status_from_node(self, node, stale):
        ip = node['ip']
        universes = []
        try:
            with self._open_socket(node.get('via', '')) as s:
                for u in range(8):                     # Stardust: 8 universes
                    s.sendto(_tod_request_packet(0, u), (ip, ARTNET_PORT))
                deadline = time.time() + 1.5
                tods = {}
                while time.time() < deadline:
                    try:
                        data, _addr = s.recvfrom(2048)
                    except socket.timeout:
                        break
                    tod = _parse_tod_data(data)
                    if tod:
                        tods.setdefault(tod['subuni'], []).extend(tod['uids'])
        except OSError as exc:
            return {'available': False, 'reason': f'RDM TOD failed: {exc}'}
        for u in range(8):
            uids = tods.get(u, [])
            universes.append({
                'universe': u + 1,
                'transmitting': u in tods,   # replied to TOD [NEEDS VERIFICATION as an "up" proxy]
                'rfPct': None,               # RF quality not in Art-Net; web UI/v2
                'fixtures': [{'uid': uid, 'dmxAddress': None, 'model': None} for uid in uids],
            })
        found = sum(len(u['fixtures']) for u in universes)
        outputting = universes_outputting(node)
        # [VERIFIED 2026-07-20] A Stardust answers neither ArtTodRequest nor
        # advertises real SwOut values, so a TOD reply is NOT a usable "up"
        # proxy — treating it as one reported "8 universes down" on a healthy
        # unit. Report up/down only from ArtPollReply port data; when the node
        # publishes none, report unknown (None) so the alert rule stays quiet
        # rather than crying wolf. Stardust universes need the sACN listener.
        for u in universes:
            u['transmitting'] = (u['universe'] in outputting) if node['ports'] else None
        up = len(outputting) if node['ports'] else None
        status = {
            'available': True, 'source': 'artnet-rdm',
            'stale': stale,
            'node': node['longName'] or node['shortName'], 'address': ip,
            'via': node.get('via', ''),
            'firmware': node.get('firmware'),
            'mac': node['mac'],
            'universes': universes,
            'universesOutputting': outputting,
            'universesUp': up,
            'universesDown': (8 - up) if up is not None else None,
            'weakestRfPct': None,
            'fixturesDiscovered': found,
            'outputs': None,
        }
        ws_host = node.get('ip') or self.host
        if ws_host:
            status['outputs'] = self._cached_outputs(ws_host)
        else:
            self._outputs_error = (
                'No address is known for this unit, so its output '
                'configuration cannot be read.'
            )
        # Always present, so an empty grid can state its reason instead of
        # leaving the operator to guess between "unreachable" and "broken".
        status['outputsError'] = self._outputs_error
        return status

    # ── simulator ──
    def _sim_status(self):
        t = time.time() - self._sim_t0
        fixtures_by_uni = {
            1: [('4C4C:00A11201', 'Astera AX5', 45), ('4C4C:00A11202', 'Astera AX5', 52),
                ('4C4C:00A11203', 'Astera AX5', 50)],
            2: [('4A6F:00220301', 'Aputure LS 600x', 1), ('4A6F:00220302', 'Aputure LS 600x', 25)],
            5: [('4C4C:00B00101', 'Astera Titan', 101)],
        }
        universes = []
        for u in range(1, 9):
            rf = max(8, min(99, round(82 + 14 * math.sin(t / 53 + u * 2.1) - (u == 5) * 40)))
            transmitting = u in fixtures_by_uni or u <= 4
            universes.append({
                'universe': u,
                'transmitting': transmitting,
                'rfPct': rf if transmitting else None,
                'fixtures': [
                    {'uid': uid, 'model': model, 'dmxAddress': addr}
                    for uid, model, addr in fixtures_by_uni.get(u, [])
                ],
            })
        up = [u for u in universes if u['transmitting']]
        rfs = [u['rfPct'] for u in up if u['rfPct'] is not None]
        # Outputs config — on real hardware this comes from ws://<ip>/ws; here we
        # feed the same _merge_outputs join so ?sim=1 renders the real table.
        sim_timo = {
            'universe_nrs': [1, 2, 3, 4, 5, 6, 7, 8],
            'output_names': ['Front', 'Back', 'Spots', 'Cyc', 'FOH', 'Booms', 'Haze', ''],
            'output_powers_mw': [100, 100, 100, 30, 100, 100, 7, 100],
            'rf_protocols': ['CRMX', 'CRMX', 'CRMX2_1_4', 'CRMX2_2_4', 'CRMX',
                             'WDMX_G3', 'CRMX', 'CRMX'],
            'enabled_universe_nrs': [1, 2, 3, 4, 5, 6, 7],
        }
        sim_sacn = {'universe_map': {'1': [1], '2': [2], '5': [3], '6': [5]}}
        sim_artnet = {'universe_map': {'4': (0 << 8) | (0 << 4) | 1,
                                       '6': (0 << 8) | (1 << 4) | 2}}
        sim_outputs = _merge_outputs(sim_timo, sim_sacn, sim_artnet)
        return {
            'available': True, 'source': 'sim',
            'node': 'Stardust DTx8 (sim)', 'address': '10.0.0.80',
            'universes': universes,
            'universesUp': len(up),
            'universesDown': 8 - len(up),
            'weakestRfPct': min(rfs) if rfs else None,
            'fixturesDiscovered': sum(len(u['fixtures']) for u in universes),
            'outputs': sim_outputs,
            # Shape parity with _real_status: the key always exists.
            'outputsError': None,
        }

    # ── patch reconciliation (the novel bit) ──
    def reconcile(self, patch_rows):
        """Compare RDM-discovered fixtures against PatchRow entries.
        patch_rows: iterable of PatchRow. Returns per-universe diffs."""
        status = self.get_status()
        if not status.get('available'):
            return {'available': False, 'reason': status.get('reason')}
        patched = {}
        for r in patch_rows:
            if r.universe is None:
                continue
            patched.setdefault(r.universe, []).append({
                'address': r.address, 'fixture': r.fixture, 'type': r.type,
            })
        report = []
        for u in status['universes']:
            uni = u['universe']
            plist = patched.get(uni, [])
            discovered = u['fixtures']
            issues = []
            if discovered and not plist:
                issues.append('fixtures on air but universe not in patch')
            if plist and not discovered and u['transmitting'] is False:
                issues.append('patched but universe not transmitting')
            addrs_patch = {p['address'] for p in plist if p['address'] is not None}
            addrs_rdm = {f['dmxAddress'] for f in discovered if f.get('dmxAddress') is not None}
            for a in sorted(addrs_rdm - addrs_patch):
                issues.append(f'fixture reports address {a} — not in patch')
            for a in sorted(addrs_patch - addrs_rdm):
                if discovered:  # only meaningful when RDM gave us addresses
                    issues.append(f'patched at {a} but no fixture reports it')
            if plist or discovered or issues:
                report.append({
                    'universe': uni,
                    'patchedCount': len(plist),
                    'discoveredCount': len(discovered),
                    'issues': issues,
                })
        return {'available': True, 'report': report,
                'note': 'RDM DMX addresses need full RDM GET (v2); '
                        'sim mode demonstrates the reconciliation shape'}
