import logging
import requests
import subprocess

try:
    import puresnmp
except ImportError:  # dependency not installed in this interpreter
    puresnmp = None

log = logging.getLogger(__name__)

# Read-only SNMP defaults. GigaCore ships v2c enabled with community "public".
_SNMP_COMMUNITY = 'public'
_SNMP_TIMEOUT = 2

_OUI_MAP = {
    '00:1C:A2': 'luminex',
    '70:A7:41': 'luminex',
    'D0:69:9E': 'luminex',
    '78:8A:20': 'ubiquiti',
    'DC:9F:DB': 'ubiquiti',
    'FC:EC:DA': 'ubiquiti',
    '24:A4:3C': 'ubiquiti',
    '80:2A:A8': 'ubiquiti',
    'B4:FB:E4': 'ubiquiti',
    '00:27:22': 'swisson',
    '28:36:38': 'swisson',
    '20:B0:01': 'starlink',
}


def detect_vendor_type(mac: str) -> str:
    return _OUI_MAP.get(mac.upper()[:8], 'unknown')


def enrich_device(ip: str, mac: str, device_type: str) -> dict:
    if device_type == 'luminex':
        return _enrich_luminex(ip)
    if device_type == 'ubiquiti':
        return _enrich_ubiquiti(ip)
    if device_type == 'swisson':
        return _enrich_swisson(ip)
    if device_type == 'starlink':
        return _enrich_starlink(ip)
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


def _enrich_luminex(ip: str) -> dict:
    # GigaCore's web GUI is auth-locked (401) and exposes no public REST API,
    # but SNMP v2c is enabled by default. Pull model + port stats from standard
    # MIBs. Firmware is not in any MIB GigaCore implements, so it stays blank.
    if puresnmp is None:
        log.warning('puresnmp not installed; skipping Luminex SNMP enrichment')
        return {}
    try:
        model = _snmp_get(ip, '1.3.6.1.2.1.1.1.0')          # sysDescr
        if_types = _snmp_walk_map(ip, '1.3.6.1.2.1.2.2.1.3')  # ifType
        oper = _snmp_walk_map(ip, '1.3.6.1.2.1.2.2.1.8')      # ifOperStatus
        # Physical ports are ifType == 6 (ethernetCsmacd); the rest are VLANs.
        phys = [idx for idx, t in if_types.items() if t == 6]
        return {
            'model': model,
            'firmware': None,
            'portCount': len(phys),
            'activePorts': sum(1 for idx in phys if oper.get(idx) == 1),  # 1 == up
        }
    except Exception:
        pass
    return {}


def _enrich_ubiquiti(ip: str) -> dict:
    try:
        r = requests.get(f'https://{ip}/api/s/default/stat/sta', timeout=3, verify=False)
        if r.status_code == 200:
            data = r.json()
            return {'clientCount': len(data.get('data', [])), 'source': 'unifi'}
    except Exception:
        pass
    return {}


def _enrich_swisson(ip: str) -> dict:
    try:
        r = requests.get(f'http://{ip}/model/device', timeout=3)
        if r.status_code == 200:
            data = r.json()
            return {
                'model': data.get('modelName'),
                'firmware': data.get('swVersionStr'),
                'hwVersion': data.get('hwVersionStr'),
                'portCount': len(data.get('uids', [])),
                'longName': data.get('longArtNetName'),
            }
    except Exception:
        pass
    return {}


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
