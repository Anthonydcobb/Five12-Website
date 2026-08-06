import logging
import re
import requests
import subprocess
from datetime import datetime

# `_utc_iso` is the repo's one serializer for a naive-UTC instant (trailing Z,
# never a bare offset-less string — see its docstring for the 4h-in-the-future
# bug that motivated it). No cycle: `models` imports only `db` from the package
# root, and nothing in `models` or the package root imports `vendors` — every
# caller of this module imports it lazily inside a function.
from ..models import _utc_iso

try:
    import puresnmp
except ImportError:  # dependency not installed in this interpreter
    puresnmp = None

log = logging.getLogger(__name__)

# Read-only SNMP defaults. GigaCore ships v2c enabled with community "public".
_SNMP_COMMUNITY = 'public'
_SNMP_TIMEOUT = 2

# OUI -> device type. Entries marked "confirmed on rig" were verified during the
# July 2026 network survey by resolving known-good device IPs to their MACs
# (see docs/network-state.md). Everything else is from the public IEEE registry.
_OUI_MAP = {
    # Luminex — GigaCore AV switches
    '00:1C:A2': 'luminex',
    '70:A7:41': 'luminex',
    'D0:69:9E': 'luminex',          # confirmed on rig
    # Ubiquiti
    '78:8A:20': 'ubiquiti',
    'DC:9F:DB': 'ubiquiti',
    'FC:EC:DA': 'ubiquiti',
    '24:A4:3C': 'ubiquiti',
    '80:2A:A8': 'ubiquiti',
    'B4:FB:E4': 'ubiquiti',
    # Swisson — DMX nodes
    '00:27:22': 'swisson',
    '28:36:38': 'swisson',          # confirmed on rig
    # ACPD (AC Power Distribution) — PDXND-4-1 Ethernet/DMX nodes.
    # [VERIFIED 2026-08-05] 15 units on the sACN segment (10.9.15.101-.121).
    # This OUI is NOT in the IEEE registry snapshot Wireshark/scapy ship — a
    # lookup returns nothing, while known OUIs in this table resolve fine. The
    # identification is the devices' own report: GET /model/device answers
    # modelName 'PDXND-4-1' and longArtNetName 'ACPD NODE ENET/DMX (PDXND-4-1)',
    # identically on all fifteen. Do not "correct" this against a registry
    # lookup that comes back empty.
    '04:11:19': 'acpd',             # confirmed on rig
    # Starlink. UNVERIFIED — this entry is not registry-sourced, despite the
    # header above. [CHECKED 2026-08-05] the IEEE/Wireshark OUI database
    # attributes 20:B0:01 to "Technicolor Delivery Technologies Belgium NV",
    # and contains no SpaceX entry at all (the only "StarLink" match is Star
    # Link Communication Pvt. Ltd., an unrelated company). The mapping traces
    # to a line in docs/2026-05-21-network-monitoring-dashboard.md, i.e. it was
    # planned rather than observed.
    #
    # Left in place deliberately: consumer CPE routinely ships the ODM's OUI
    # rather than the brand owner's, and Technicolor builds exactly that class
    # of hardware, so a Starlink router on a Technicolor OUI is plausible. It
    # could equally be wrong. No dish has been on the network to check.
    #
    # TO SETTLE: when the dish is up, read its MAC. If it starts 20:B0:01,
    # replace this block with "confirmed on rig". If it does not, delete the
    # entry — a wrong OUI is worse than an absent one, because it labels
    # somebody else's Technicolor hardware as a satellite terminal.
    '20:B0:01': 'starlink',
    # Riedel — Bolero antennas. [VERIFIED 2026-07-21] both rig antennas
    # (192.168.1.11, .12) share this OUI.
    '00:19:7C': 'bolero',
    # Stardust. NOTE: E4:5F:01 is a Raspberry Pi Trading OUI, and Stardusts are
    # Pi-based — so this maps to 'stardust' rather than 'raspberrypi' on purpose.
    # A generic Pi on the lighting network would be misreported; none are expected.
    'E4:5F:01': 'stardust',         # confirmed on rig
    # High End Systems / ETC — Hog 4 family. Art-Net/sACN source names read
    # "Processor, Netnumber N, Output M"; N matches the final IP octet.
    '00:90:A1': 'hog',              # confirmed on rig
    '00:A0:64': 'hog',
    # Fortinet — the venue FortiGate, not lighting gear, but worth naming so it
    # doesn't sit in the list as "unknown".
    '00:09:0F': 'fortinet',
    # NETGEAR — M4250 AV line and older switches. 28:94:01 confirmed on rig
    # (172.16.3.97, M4250-10G2F-PoE+); the rest are registry entries.
    '28:94:01': 'netgear',          # confirmed on rig
    '00:09:5B': 'netgear', '00:0F:B5': 'netgear', '00:14:6C': 'netgear',
    '00:18:4D': 'netgear', '00:1B:2F': 'netgear', '00:1E:2A': 'netgear',
    '00:1F:33': 'netgear', '00:22:3F': 'netgear', '00:24:B2': 'netgear',
    '00:26:F2': 'netgear', '20:0C:C8': 'netgear', '28:C6:8E': 'netgear',
    '2C:30:33': 'netgear', '30:46:9A': 'netgear', '44:94:FC': 'netgear',
    '6C:B0:CE': 'netgear', '84:1B:5E': 'netgear', '9C:3D:CF': 'netgear',
    'A0:40:A0': 'netgear', 'A0:63:91': 'netgear', 'C0:3F:0E': 'netgear',
    'C4:04:15': 'netgear', 'CC:40:D0': 'netgear', 'E0:91:F5': 'netgear',
    'E4:F4:C6': 'netgear', 'F8:73:94': 'netgear',
}


def is_randomized_mac(mac: str) -> bool:
    """True if `mac` is locally administered (bit 0x02 of the first octet).

    Phones and laptops randomize their MAC per-SSID; lighting infrastructure
    never does. On this rig ~50 venue Wi-Fi clients share the Management /16,
    and without this check every one of them is persisted as a NetworkDevice
    row keyed on a MAC that changes on the next association.
    """
    try:
        return bool(int(mac.replace('-', ':').split(':')[0], 16) & 0x02)
    except (ValueError, IndexError):
        return False


# Types whose display form is not str.capitalize(). Only acronyms belong here —
# anything absent keeps the old behaviour, so adding an entry cannot restyle a
# label somewhere else by accident.
_TYPE_DISPLAY = {
    'acpd': 'ACPD',
}


def display_name(device_type: str) -> str:
    """Human form of a device type, for auto-generated labels.

    The scanner builds a label as f"{type} {model}" when a device has none.
    str.capitalize() renders 'acpd' as 'Acpd', which is wrong for an acronym
    and shows up on fifteen nodes in the Network tab.
    """
    return _TYPE_DISPLAY.get(device_type, device_type.capitalize())


def detect_vendor_type(mac: str) -> str:
    # CHANGE: normalize '-' to ':' before lookup. _arp_fallback already converts,
    # but scapy and any future caller may pass dash-form; a dash-form MAC used to
    # silently return 'unknown' for every device.
    return _OUI_MAP.get(mac.upper().replace('-', ':')[:8], 'unknown')


def enrich_device(ip: str, mac: str, device_type: str) -> dict:
    if device_type == 'luminex':
        return _enrich_luminex(ip)
    if device_type == 'netgear':
        return _enrich_netgear(ip)
    if device_type == 'ubiquiti':
        return _enrich_ubiquiti(ip)
    # Swisson and ACPD serve the same /model/device contract — same field
    # names, same shapes. [VERIFIED 2026-08-05] against 15 PDXND-4-1 units.
    # The PDXND appears to be that API's node design carrying ACPD's badge;
    # whatever the provenance, one reader covers both.
    if device_type in ('swisson', 'acpd'):
        return _enrich_model_device_api(ip)
    if device_type == 'starlink':
        return _enrich_starlink(ip)
    # 'stardust' is enriched by Art-Net discovery in scanner._scan_artnet, which
    # returns far more (firmware, universes outputting) than SNMP would.
    # 'hog' and 'fortinet' expose nothing useful read-only; named, not probed.
    return {}


def _snmp_get(ip: str, oid: str):
    """Single read-only SNMP GET. OctetStrings are decoded to str."""
    val = puresnmp.get(ip, _SNMP_COMMUNITY, oid, timeout=_SNMP_TIMEOUT)
    if isinstance(val, bytes):
        return val.decode('latin-1').strip()
    return val


def _snmp_walk_map(ip: str, oid: str) -> dict:
    """Walk a table column, keyed by the interface index (last OID arc)."""
    out = {}
    for row in puresnmp.walk(ip, _SNMP_COMMUNITY, oid, timeout=_SNMP_TIMEOUT):
        o = str(getattr(row, 'oid', row[0]))
        val = getattr(row, 'value', row[1])
        out[o.rsplit('.', 1)[-1]] = val
    return out


def _snmp_walk_suffix(ip: str, oid: str) -> dict:
    """Walk a table column keyed by the FULL remaining OID suffix.

    `_snmp_walk_map` keys on the last arc alone, which is correct for tables
    indexed by one integer (ifIndex) and destroys tables indexed by anything
    wider. The bridge forwarding database is indexed by the six octets of a
    MAC address, so keying on the last arc returns '91' — the final byte —
    where the answer is a whole device.

    Kept alongside rather than replacing it: `_snmp_walk_map` serves the
    Netgear and Luminex enrichers today and must not change behaviour.
    """
    out = {}
    prefix = oid + '.'
    for row in puresnmp.walk(ip, _SNMP_COMMUNITY, oid, timeout=_SNMP_TIMEOUT):
        # NOTE: deliberately not `getattr(row, 'oid', row[0])` — that default
        # expression evaluates `row[0]` unconditionally, even when `row.oid`
        # exists, and raises on any row object that isn't also subscriptable.
        o = str(row.oid) if hasattr(row, 'oid') else str(row[0])
        val = row.value if hasattr(row, 'value') else row[1]
        out[o[len(prefix):] if o.startswith(prefix) else o] = val
    return out


def _mac_from_oid_suffix(suffix: str) -> str | None:
    """'0.25.124.2.224.91' -> '00:19:7C:02:E0:5B'. None if it isn't six octets,
    or if any arc isn't a byte (0-255) — `int('-5')` and `int('300')` both
    succeed, and without this check they'd format as '-5' and '12C' rather
    than being rejected, silently naming the wrong device on a port."""
    parts = suffix.split('.')
    if len(parts) != 6:
        return None
    try:
        octets = [int(p) for p in parts]
    except ValueError:
        return None
    if any(o < 0 or o > 255 for o in octets):
        return None
    return ':'.join(f'{o:02X}' for o in octets)


def read_switch_ports(ip: str) -> dict:
    """Which MACs are behind each physical port of a managed switch.

    Four standard read-only walks — BRIDGE-MIB forwarding database, the
    bridge-port to ifIndex map, and MIB-II's ifDescr and ifOperStatus.
    The underlying walks were [VERIFIED 2026-08-06] against five GigaCore12s,
    ~2s each; this function itself has not yet been run against a switch
    (hardware verification is Task 7, still pending).

    READ-ONLY. GET and WALK only; this never issues an SNMP SET. The rig is
    live and a configuration change would be visible on stage.

    A forwarding database records where a MAC was LAST SEEN, not what is
    plugged in where, so `deviceCount` travels with every port: only a count
    of exactly one proves direct attachment. Callers must not present a
    higher-count port as a device's location.

    ifName is unsupported on this firmware (0 rows) — the label comes from
    ifDescr, which returns bytes padded to a fixed width (b'Port  1').

    Returns {} on any failure, so the scanner's merge keeps the last good map.
    """
    try:
        fdb = _snmp_walk_suffix(ip, '1.3.6.1.2.1.17.4.3.1.2')
        bp2if = _snmp_walk_map(ip, '1.3.6.1.2.1.17.1.4.1.2')
        descr = _snmp_walk_map(ip, '1.3.6.1.2.1.2.2.1.2')
        oper = _snmp_walk_map(ip, '1.3.6.1.2.1.2.2.1.8')
    except Exception:
        return {}
    if not bp2if:
        return {}

    # A switch returning a bridge-port key or FDB value that isn't cleanly
    # int()-convertible (malformed MIB response, an unexpected ASN.1 type
    # from puresnmp, a firmware quirk) must not raise out of here — this runs
    # inside the scanner's per-subnet sweep, and an uncaught ValueError/
    # TypeError would abort the rest of that sweep, same failure class as the
    # /model/status port-parsing bug fixed in 7033761.
    try:
        by_port = {int(bp): [] for bp in bp2if}
        for suffix, bridge_port in fdb.items():
            # Bridge ports absent from dot1dBasePortIfIndex are not physical
            # ports — port 0 is the switch's own management MAC. Assigning it
            # a port number would invent hardware.
            if str(bridge_port) not in bp2if:
                continue
            mac = _mac_from_oid_suffix(suffix)
            if mac:
                by_port[int(bridge_port)].append(mac)
    except Exception:
        return {}

    ports = []
    for bridge_port in sorted(by_port):
        if_index = str(bp2if[str(bridge_port)])
        raw = descr.get(if_index, b'')
        name = (raw.decode('latin-1') if isinstance(raw, bytes) else str(raw))
        # b'Port  1' -> 'Port 1'. The padding is the device's, not ours.
        name = ' '.join(name.split()) or f'Port {bridge_port}'
        macs = sorted(by_port[bridge_port])
        ports.append({
            'port': bridge_port,
            'name': name,
            'link': 'up' if oper.get(if_index) == 1 else 'down',
            'macs': macs,
            'deviceCount': len(macs),
        })

    return {
        'switchPorts': ports,
        # Stamped here, at the moment of the read. The sibling DMX feature
        # shipped a bug where the staleness timestamp was the ICMP ping clock
        # rather than the data's own clock, so a wedged-but-pingable device
        # showed an hours-old reading labelled seconds old.
        'switchPortsAsOf': _utc_iso(datetime.utcnow()),
    }


def _entity_field(ip: str, oid: str):
    """First non-empty value in an ENTITY-MIB column.

    The chassis is conventionally index 1, but that is convention, not a
    guarantee — so take the lowest-indexed row that is actually populated.
    Netgear leaves most of these columns as empty strings (notably
    entPhysicalHardwareRev), which is why blank is treated as absent.

    Returns None rather than raising: not every managed switch implements
    ENTITY-MIB, and a switch that doesn't must still yield its MIB-II data.
    """
    try:
        rows = _snmp_walk_map(ip, oid)
    except Exception:
        return None
    for idx in sorted(rows, key=lambda k: int(k) if k.isdigit() else 1 << 30):
        val = rows[idx]
        if isinstance(val, bytes):
            val = val.decode('latin-1')
        val = str(val).strip()
        if val:
            return val
    return None


def _versions_in(text: str) -> list[str]:
    """Dotted version numbers in a sysDescr, in order.

    Netgear's M4250 sysDescr ends '..., 13.0.5.26, 1.0.0.11' — firmware then
    boot loader. That tail is the only place the boot version appears at all;
    entPhysicalFirmwareRev is empty on this hardware.
    """
    return re.findall(r'\d+(?:\.\d+){2,}', text or '')


def _enrich_snmp_switch(ip: str, vendor: str) -> dict:
    """Model, firmware and port counts from standard MIB-II + ENTITY-MIB.
    Works on any managed switch with SNMP v2c and community `public` —
    [VERIFIED 2026-07-21] against the M4250 at 172.16.3.97.

    CHANGE: firmware used to be hardcoded None. It is available two ways —
    entPhysicalSoftwareRev ('13.0.5.26'), and as the tail of sysDescr — and
    neither was being read. Serial number comes free from the same walk.
    """
    if puresnmp is None:
        log.warning('puresnmp not installed; skipping %s SNMP enrichment', vendor)
        return {}
    try:
        sys_descr = _snmp_get(ip, '1.3.6.1.2.1.1.1.0')        # sysDescr
        if_types = _snmp_walk_map(ip, '1.3.6.1.2.1.2.2.1.3')  # ifType
        oper = _snmp_walk_map(ip, '1.3.6.1.2.1.2.2.1.8')      # ifOperStatus
    except Exception:
        # Silent {} is correct here: on this rig SNMP v2c is only configured on
        # one M4250 so far, so the other switches legitimately never answer.
        return {}

    # Physical ports are ifType == 6 (ethernetCsmacd); the rest are VLANs.
    phys = [idx for idx, t in if_types.items() if t == 6]

    # ENTITY-MIB is probed only after MIB-II succeeded, and each field is
    # independently optional, so a switch without it keeps model and ports.
    versions = _versions_in(sys_descr)
    data = {
        'model': _entity_field(ip, '1.3.6.1.2.1.47.1.1.1.1.13') or sys_descr,
        'firmware': (_entity_field(ip, '1.3.6.1.2.1.47.1.1.1.1.10')
                     or (versions[0] if versions else None)),
        'portCount': len(phys),
        'activePorts': sum(1 for idx in phys if oper.get(idx) == 1),  # 1 == up
    }
    serial = _entity_field(ip, '1.3.6.1.2.1.47.1.1.1.1.11')
    if serial:
        data['serial'] = serial
    # Netgear reports no entPhysicalHardwareRev, so the boot-loader version
    # from the sysDescr tail is the closest thing to a hardware revision.
    if len(versions) > 1:
        data['bootVersion'] = versions[1]
    return data


def _enrich_luminex(ip: str) -> dict:
    # GigaCore's web GUI is auth-locked (401) and exposes no public REST API,
    # but SNMP v2c is enabled by default. Firmware is not in any MIB GigaCore
    # implements, so it stays blank.
    return _enrich_snmp_switch(ip, 'Luminex')


def _enrich_netgear(ip: str) -> dict:
    # M4250 answers MIB-II once v2c is enabled — it is NOT on by default, unlike
    # Luminex. Configure per switch: community `public`, ReadOnly, restricted to
    # the Management range. Returns {} until then.
    return _enrich_snmp_switch(ip, 'Netgear')


def _enrich_ubiquiti(ip: str) -> dict:
    try:
        r = requests.get(f'https://{ip}/api/s/default/stat/sta', timeout=3, verify=False)
        if r.status_code == 200:
            data = r.json()
            return {'clientCount': len(data.get('data', [])), 'source': 'unifi'}
    except Exception:
        pass
    return {}


# /model/status enum codes, decoded ONLY where a value has actually been seen
# on hardware or confirmed by the operator. [VERIFIED 2026-08-05] all 68 ports
# across one XND-8 and 15 PDXND-4-1s read status 3 / direction 1 / protocol 2,
# so there is no second sample of any of these fields anywhere on the rig.
# Art-Net's protocol code is operator-confirmed, not observed.
#
# Do NOT add speculative entries. An unmapped code renders as 'code N', which
# is what will surface the real value the first time a port is set to input,
# disabled, or loses signal.
_PORT_PROTOCOL = {1: 'Art-Net', 2: 'sACN'}
_PORT_DIRECTION = {1: 'Output'}
_PORT_STATUS = {3: 'OK'}


def _port_enum(table: dict, code) -> str:
    """Decoded label for `code`, or the literal 'code N' when unmapped."""
    return table.get(code, f'code {code}')


# The universe a port outputs is the column an operator is actually reading —
# it is the answer to "which port is feeding this rig". A node that omits it
# used to pass None straight through, and PortTable renders null as nothing, so
# the cell went BLANK. A blank cell is unreadable in exactly the wrong way: it
# looks like a rendering fault, or like universe 0, or like the row is still
# loading. Same principle as the 'code N' convention one function up — never
# blank, never guessed — applied to the value rather than to an enum.
_UNIVERSE_UNREPORTED = 'not reported'


def _port_universe(value):
    """The universe as the node reported it, or a visible 'not reported'."""
    return _UNIVERSE_UNREPORTED if value is None else value


def read_port_status(ip: str) -> dict:
    """Per-port universe/protocol/direction/status from /model/status.

    Served identically by the Swisson XND-8 (8 ports) and the ACPD PDXND-4-1
    (4 ports) — the same shared contract as /model/device. Array index is the
    port number, zero-based, so it is reported here 1-based.

    Note /model/port is NOT a per-port endpoint: it ignores ?index=, ?port=
    and ?portIndex=, always returns one record, and reports a protocol that
    contradicts this one. Do not cross-reference the two.

    Returns {} on any failure, so the scanner's carry-forward in
    `_process_discovered_device` leaves a previously stored patch intact — one
    missed poll must not erase it.

    A successful read is stamped with `portsAsOf`. That timestamp is the whole
    point: it rides into vendor_data on the sweep at no cost, and it is the
    ONLY honest provenance for the patch. NetworkDevice.last_seen cannot stand
    in for it — the 20s keep-alive re-probe refreshes last_seen without
    enriching at all, so a node whose HTTP stack is wedged but which still
    answers ping would otherwise show an hours-old patch under a 10s-old
    timestamp, and somebody can repatch that node from its front panel inside
    that window.
    """
    try:
        r = requests.get(f'http://{ip}/model/status', timeout=3)
        if r.status_code != 200:
            return {}
        ports = r.json().get('ports')
    except Exception:
        return {}
    if not isinstance(ports, list) or not ports:
        return {}
    # A node answering HTTP 200 with a `ports` array does not guarantee each
    # element is a well-formed port object. A non-dict element raises
    # AttributeError on `p.get(...)`, and an unhashable enum value (a list or
    # dict where an int code is expected) raises TypeError from
    # `table.get(code, ...)`. Either used to escape uncaught, propagate out of
    # enrich_device, and abort the rest of that subnet's sweep — including its
    # stale-device prune — every cycle until the node was fixed. Per-port
    # parsing is best-effort like the request above it: any failure here is
    # just as much "this node can't be trusted right now" as a timeout is.
    try:
        parsed = [
            {
                'port': i + 1,
                'universe': _port_universe(p.get('universe')),
                'protocol': _port_enum(_PORT_PROTOCOL, p.get('protocol')),
                'direction': _port_enum(_PORT_DIRECTION, p.get('direction')),
                'status': _port_enum(_PORT_STATUS, p.get('status')),
            }
            for i, p in enumerate(ports)
        ]
    except Exception:
        return {}
    # Stamped only on the success path, so `portsAsOf` can never appear
    # without the `ports` it describes.
    return {'ports': parsed, 'portsAsOf': _utc_iso(datetime.utcnow())}


def _enrich_model_device_api(ip: str) -> dict:
    """Read the /model/device report served by Swisson and ACPD nodes alike.

    Named for the contract rather than a vendor, because two vendors' hardware
    answers it with identical field names. portCount is derived from the RDM
    UID list — a PDXND-4-1 reports four, one per DMX port.

    /model/status is read alongside it for the per-port patch. The two are
    merged independently: a node that answers one and not the other still
    contributes what it has.
    """
    data = {}
    try:
        r = requests.get(f'http://{ip}/model/device', timeout=3)
        if r.status_code == 200:
            body = r.json()
            data = {
                'model': body.get('modelName'),
                'firmware': body.get('swVersionStr'),
                'hwVersion': body.get('hwVersionStr'),
                'portCount': len(body.get('uids', [])),
                'longName': body.get('longArtNetName'),
            }
    except Exception:
        pass
    data.update(read_port_status(ip))
    return data


def _enrich_starlink(ip: str) -> dict:
    try:
        result = subprocess.run(
            ['ping', '-n', '1', '-w', '1000', ip],
            capture_output=True, timeout=3
        )
        online = result.returncode == 0
        return {'pingOnline': online, 'note': 'gRPC stats require grpcio (v2)'}
    except Exception:
        pass
    return {}
