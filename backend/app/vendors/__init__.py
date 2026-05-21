import requests
import subprocess

_OUI_MAP = {
    '00:1C:A2': 'luminex',
    '70:A7:41': 'luminex',
    '78:8A:20': 'ubiquiti',
    'DC:9F:DB': 'ubiquiti',
    'FC:EC:DA': 'ubiquiti',
    '24:A4:3C': 'ubiquiti',
    '80:2A:A8': 'ubiquiti',
    'B4:FB:E4': 'ubiquiti',
    '00:27:22': 'swisson',
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


def _enrich_luminex(ip: str) -> dict:
    try:
        r = requests.get(f'http://{ip}/api/v1/system', timeout=3)
        if r.status_code == 200:
            data = r.json()
            return {
                'model': data.get('model'),
                'firmware': data.get('firmware'),
                'uptime': data.get('uptime'),
                'portCount': data.get('portCount'),
                'activePorts': data.get('activePorts'),
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
        r = requests.get(f'http://{ip}/api/status', timeout=3)
        if r.status_code == 200:
            return r.json()
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
