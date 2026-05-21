# Network Monitoring Dashboard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a live network device discovery dashboard with vendor-enriched status, MAC-keyed notes, and named location snapshots, replacing the placeholder `/network` page.

**Architecture:** Flask background thread runs ARP sweeps every 30s on configured subnets, probes vendor APIs for enriched data, and writes results to MySQL. React frontend (Layout B: sidebar + device list + detail panel) polls the API and renders live status. Notes and labels persist to MAC address across IP changes and locations.

**Tech Stack:** Python `scapy` (ARP scan, with `arp -a` fallback), `requests` (vendor HTTP APIs), Flask blueprint (`network_routes.py`), SQLAlchemy models, React 19 + Tailwind CSS 4, Axios.

---

## File Map

**Create:**
- `backend/tests/conftest.py` — pytest fixtures (Flask test app + DB)
- `backend/tests/test_network_models.py` — model unit tests
- `backend/tests/test_network_routes.py` — route integration tests
- `backend/tests/test_scanner.py` — scanner unit tests
- `backend/app/vendors/__init__.py` — OUI lookup + vendor dispatch
- `backend/app/vendors/luminex.py` — Luminex GigaCore REST API
- `backend/app/vendors/ubiquiti.py` — Ubiquiti UniFi local API
- `backend/app/vendors/starlink.py` — Starlink ping (v1)
- `backend/app/vendors/swisson.py` — Swisson XND HTTP probe
- `backend/app/scanner.py` — background ARP sweep thread
- `backend/app/network_routes.py` — all `/api/network/*` routes
- `app/src/components/network/NetworkSidebar.jsx`
- `app/src/components/network/NetworkDeviceList.jsx`
- `app/src/components/network/NetworkDeviceDetail.jsx`
- `app/src/components/network/SaveLocationModal.jsx`
- `app/src/components/network/SubnetSettings.jsx`

**Modify:**
- `backend/app/models.py` — add 4 new models
- `backend/app/__init__.py` — register blueprint, start scanner thread
- `backend/requirements.txt` — add scapy
- `app/src/pages/NetworkMonitor.jsx` — full rewrite (replaces DMX canvas placeholder)

---

## Task 1: Pytest setup

**Files:**
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/conftest.py`

- [ ] **Step 1: Install pytest**

Run from `backend/` (with venv active):
```
pip install pytest pytest-flask
```

- [ ] **Step 2: Create `backend/tests/__init__.py`**

```python
```
(empty file)

- [ ] **Step 3: Create `backend/tests/conftest.py`**

```python
import pytest
from app import create_app, db as _db

@pytest.fixture(scope='session')
def app():
    app = create_app()
    app.config.update({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
    })
    with app.app_context():
        _db.create_all()
        yield app
        _db.drop_all()

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture
def db(app):
    with app.app_context():
        yield _db
        _db.session.rollback()
```

- [ ] **Step 4: Verify pytest runs (no tests yet = OK)**

Run from `backend/`:
```
pytest tests/ -v
```
Expected: `no tests ran` — exit 0.

---

## Task 2: Network models

**Files:**
- Modify: `backend/app/models.py` — append 4 models after `LabelTemplate`
- Create: `backend/tests/test_network_models.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_network_models.py`:
```python
import pytest
from app.models import NetworkSubnet, NetworkDevice, LocationSnapshot, LocationDevice

def test_subnet_to_dict(db):
    s = NetworkSubnet(label='Management', cidr='192.168.10.0/24', color='#7dd3fc')
    db.session.add(s)
    db.session.commit()
    d = s.to_dict()
    assert d['label'] == 'Management'
    assert d['cidr'] == '192.168.10.0/24'
    assert d['color'] == '#7dd3fc'
    assert d['active'] is True

def test_device_to_dict(db):
    dev = NetworkDevice(
        mac_address='AA:BB:CC:DD:EE:FF',
        label='GigaCore 12',
        device_type='luminex',
        last_ip='192.168.10.5',
        notes='House left truss',
    )
    db.session.add(dev)
    db.session.commit()
    d = dev.to_dict()
    assert d['macAddress'] == 'AA:BB:CC:DD:EE:FF'
    assert d['label'] == 'GigaCore 12'
    assert d['notes'] == 'House left truss'

def test_location_snapshot(db):
    snap = LocationSnapshot(name='Warner Bros Lot 3')
    db.session.add(snap)
    db.session.commit()
    assert snap.id is not None
    assert snap.to_dict()['name'] == 'Warner Bros Lot 3'
```

- [ ] **Step 2: Run tests — expect FAIL (models not defined)**

```
pytest tests/test_network_models.py -v
```
Expected: ImportError on `NetworkSubnet`.

- [ ] **Step 3: Add models to `backend/app/models.py`**

Append after the `LabelTemplate` class:

```python
from datetime import datetime

class NetworkSubnet(db.Model):
    __tablename__ = 'network_subnets'
    id             = db.Column(db.Integer, primary_key=True)
    label          = db.Column(db.String(100), nullable=False)
    cidr           = db.Column(db.String(50), nullable=False)
    interface_hint = db.Column(db.String(50), nullable=True)
    color          = db.Column(db.String(20), nullable=False, default='#7dd3fc')
    active         = db.Column(db.Boolean, nullable=False, default=True)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'label': self.label,
            'cidr': self.cidr,
            'interfaceHint': self.interface_hint,
            'color': self.color,
            'active': self.active,
        }


class NetworkDevice(db.Model):
    __tablename__ = 'network_devices'
    mac_address = db.Column(db.String(17), primary_key=True)
    label       = db.Column(db.String(100), nullable=True)
    device_type = db.Column(db.String(50), nullable=False, default='unknown')
    subnet_id   = db.Column(db.Integer, db.ForeignKey('network_subnets.id'), nullable=True)
    notes       = db.Column(db.Text, nullable=True)
    last_ip     = db.Column(db.String(15), nullable=True)
    last_seen   = db.Column(db.DateTime, nullable=True)
    vendor_data = db.Column(db.JSON, nullable=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'macAddress': self.mac_address,
            'label': self.label,
            'deviceType': self.device_type,
            'subnetId': self.subnet_id,
            'notes': self.notes,
            'lastIp': self.last_ip,
            'lastSeen': self.last_seen.isoformat() if self.last_seen else None,
            'vendorData': self.vendor_data,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
        }


class LocationSnapshot(db.Model):
    __tablename__ = 'location_snapshots'
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    devices    = db.relationship('LocationDevice', back_populates='snapshot',
                                  cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'deviceCount': len(self.devices),
        }


class LocationDevice(db.Model):
    __tablename__ = 'location_devices'
    id               = db.Column(db.Integer, primary_key=True)
    location_id      = db.Column(db.Integer, db.ForeignKey('location_snapshots.id'), nullable=False)
    mac_address      = db.Column(db.String(17), nullable=False)
    ip_at_time       = db.Column(db.String(15), nullable=True)
    online_at_time   = db.Column(db.Boolean, nullable=False, default=True)
    vendor_data_at_time = db.Column(db.JSON, nullable=True)
    snapshot         = db.relationship('LocationSnapshot', back_populates='devices')

    def to_dict(self):
        return {
            'id': self.id,
            'macAddress': self.mac_address,
            'ipAtTime': self.ip_at_time,
            'onlineAtTime': self.online_at_time,
            'vendorDataAtTime': self.vendor_data_at_time,
        }
```

- [ ] **Step 4: Run tests — expect PASS**

```
pytest tests/test_network_models.py -v
```
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/tests/
git commit -m "feat: add network monitoring models and pytest setup"
```

---

## Task 3: Database migration

**Files:**
- Auto-generated in `migrations/versions/`

- [ ] **Step 1: Generate migration**

Run from `backend/` with venv active and `.env` loaded (MySQL must be running):
```
flask db migrate -m "add network monitoring tables"
```
Expected: creates a new file in `migrations/versions/`.

- [ ] **Step 2: Apply migration**

```
flask db upgrade
```
Expected: `Running upgrade ... -> <hash>` with no errors.

- [ ] **Step 3: Commit**

```bash
git add migrations/
git commit -m "feat: migration for network_subnets, network_devices, location_snapshots, location_devices"
```

---

## Task 4: Vendor detection module

**Files:**
- Create: `backend/app/vendors/__init__.py`
- Create: `backend/tests/test_scanner.py` (first test only)

- [ ] **Step 1: Write OUI detection test**

Create `backend/tests/test_scanner.py`:
```python
from app.vendors import detect_vendor_type

def test_luminex_oui():
    assert detect_vendor_type('00:1C:A2:AA:BB:CC') == 'luminex'

def test_ubiquiti_oui():
    assert detect_vendor_type('78:8A:20:AA:BB:CC') == 'ubiquiti'

def test_unknown_oui():
    assert detect_vendor_type('FF:FF:FF:AA:BB:CC') == 'unknown'
```

- [ ] **Step 2: Run — expect FAIL**

```
pytest tests/test_scanner.py -v
```
Expected: ImportError.

- [ ] **Step 3: Create `backend/app/vendors/__init__.py`**

```python
# Maps MAC OUI prefixes (first 3 octets, uppercase) to device type strings.
# Add entries as new vendors are encountered on set.
_OUI_MAP = {
    '00:1C:A2': 'luminex',   # Luminex
    '70:A7:41': 'luminex',
    '78:8A:20': 'ubiquiti',  # Ubiquiti
    'DC:9F:DB': 'ubiquiti',
    'FC:EC:DA': 'ubiquiti',
    '24:A4:3C': 'ubiquiti',
    '80:2A:A8': 'ubiquiti',
    'B4:FB:E4': 'ubiquiti',
    '00:27:22': 'swisson',   # Swisson
    '20:B0:01': 'starlink',  # SpaceX/Starlink
}

def detect_vendor_type(mac: str) -> str:
    """Return vendor type string from MAC address OUI prefix."""
    oui = mac.upper()[:8]
    return _OUI_MAP.get(oui, 'unknown')


def enrich_device(ip: str, mac: str, device_type: str) -> dict:
    """
    Call the appropriate vendor API for enriched data.
    Returns a dict suitable for storing in vendor_data JSON column.
    Always returns a dict (never raises) — failures return {'error': str}.
    """
    try:
        if device_type == 'luminex':
            from .luminex import fetch_luminex_data
            return fetch_luminex_data(ip)
        elif device_type == 'ubiquiti':
            from .ubiquiti import fetch_ubiquiti_data
            return fetch_ubiquiti_data(ip)
        elif device_type == 'starlink':
            from .starlink import fetch_starlink_data
            return fetch_starlink_data(ip)
        elif device_type == 'swisson':
            from .swisson import fetch_swisson_data
            return fetch_swisson_data(ip)
        else:
            return {}
    except Exception as e:
        return {'error': str(e)}
```

- [ ] **Step 4: Run — expect PASS**

```
pytest tests/test_scanner.py -v
```
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/vendors/ backend/tests/test_scanner.py
git commit -m "feat: vendor OUI detection module"
```

---

## Task 5: Luminex vendor integration

**Files:**
- Create: `backend/app/vendors/luminex.py`

- [ ] **Step 1: Add Luminex tests to `test_scanner.py`**

Append to `backend/tests/test_scanner.py`:
```python
from unittest.mock import patch

def test_luminex_fetch_success():
    mock_response = {
        'system': {'model': 'GigaCore 12', 'firmware': '3.2.1', 'uptime': 22440},
        'ports': [{'active': True}, {'active': True}, {'active': False}]
    }
    with patch('app.vendors.luminex.requests.get') as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = mock_response
        from app.vendors.luminex import fetch_luminex_data
        result = fetch_luminex_data('192.168.10.5')
    assert result['model'] == 'GigaCore 12'
    assert result['firmware'] == '3.2.1'
    assert result['portsActive'] == 2
    assert result['portsTotal'] == 3

def test_luminex_fetch_timeout():
    import requests
    with patch('app.vendors.luminex.requests.get', side_effect=requests.Timeout()):
        from app.vendors.luminex import fetch_luminex_data
        result = fetch_luminex_data('192.168.10.5')
    assert 'error' in result
```

- [ ] **Step 2: Run — expect FAIL**

```
pytest tests/test_scanner.py::test_luminex_fetch_success -v
```
Expected: ImportError on `luminex`.

- [ ] **Step 3: Create `backend/app/vendors/luminex.py`**

```python
import requests

TIMEOUT = 3

def fetch_luminex_data(ip: str) -> dict:
    """Fetch system info from a Luminex GigaCore switch REST API."""
    try:
        resp = requests.get(f'http://{ip}/api/v1/system', timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        system = data.get('system', {})
        ports = data.get('ports', [])
        active_ports = sum(1 for p in ports if p.get('active'))
        return {
            'model': system.get('model', 'Luminex'),
            'firmware': system.get('firmware'),
            'uptimeSeconds': system.get('uptime'),
            'portsTotal': len(ports),
            'portsActive': active_ports,
        }
    except requests.Timeout:
        return {'error': 'timeout'}
    except requests.RequestException as e:
        return {'error': str(e)}
```

- [ ] **Step 4: Run — expect PASS**

```
pytest tests/test_scanner.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/vendors/luminex.py backend/tests/test_scanner.py
git commit -m "feat: Luminex GigaCore vendor integration"
```

---

## Task 6: Ubiquiti, Starlink, Swisson integrations

**Files:**
- Create: `backend/app/vendors/ubiquiti.py`
- Create: `backend/app/vendors/starlink.py`
- Create: `backend/app/vendors/swisson.py`

- [ ] **Step 1: Create `backend/app/vendors/ubiquiti.py`**

```python
import requests

TIMEOUT = 3

def fetch_ubiquiti_data(ip: str) -> dict:
    """
    Query the UniFi Dream Machine local API.
    The Dream Machine exposes /proxy/network/api/s/default/stat/health
    on port 443 (self-signed cert, verify=False).
    """
    try:
        resp = requests.get(
            f'https://{ip}/proxy/network/api/s/default/stat/health',
            timeout=TIMEOUT,
            verify=False,
        )
        resp.raise_for_status()
        data = resp.json().get('data', [{}])[0]
        return {
            'subsystem': data.get('subsystem'),
            'status': data.get('status'),
            'numAdopted': data.get('num_adopted'),
            'numDisconnected': data.get('num_disconnected'),
        }
    except requests.Timeout:
        return {'error': 'timeout'}
    except requests.RequestException as e:
        return {'error': str(e)}
```

- [ ] **Step 2: Create `backend/app/vendors/starlink.py`**

```python
import subprocess
import re

def fetch_starlink_data(ip: str) -> dict:
    """
    v1: ICMP ping only. Starlink dish uses gRPC (v2 enhancement).
    Returns online status and round-trip time.
    """
    try:
        result = subprocess.run(
            ['ping', '-n', '1', '-w', '1000', ip],
            capture_output=True, text=True, timeout=3
        )
        online = result.returncode == 0
        rtt = None
        for line in result.stdout.splitlines():
            m = re.search(r'(\d+)ms', line)
            if m:
                rtt = int(m.group(1))
        return {'online': online, 'rttMs': rtt, 'note': 'ping-only; gRPC stats in v2'}
    except subprocess.TimeoutExpired:
        return {'online': False, 'error': 'timeout'}
    except Exception as e:
        return {'online': False, 'error': str(e)}
```

- [ ] **Step 3: Create `backend/app/vendors/swisson.py`**

```python
import requests

TIMEOUT = 3

def fetch_swisson_data(ip: str) -> dict:
    """
    Query a Swisson XND node's web interface for basic status.
    API path varies by firmware — falls back to reachability check.
    """
    try:
        resp = requests.get(f'http://{ip}/api/status', timeout=TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            return {
                'model': data.get('model', 'Swisson XND'),
                'firmware': data.get('firmware'),
                'universes': data.get('universes'),
            }
        return {'reachable': True, 'note': 'status API path not confirmed for this firmware'}
    except requests.Timeout:
        return {'error': 'timeout'}
    except requests.RequestException as e:
        return {'error': str(e)}
```

- [ ] **Step 4: Verify vendors package imports cleanly**

```
python -c "from app.vendors import enrich_device; print('ok')"
```
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add backend/app/vendors/
git commit -m "feat: Ubiquiti, Starlink, Swisson vendor integrations"
```

---

## Task 7: ARP scanner + background thread

**Files:**
- Create: `backend/app/scanner.py`

- [ ] **Step 1: Add scanner tests to `test_scanner.py`**

Append to `backend/tests/test_scanner.py`:
```python
def test_arp_fallback_parses_windows_output(app):
    windows_arp = (
        "Interface: 192.168.10.100\n"
        "  Internet Address      Physical Address      Type\n"
        "  192.168.10.5          aa-bb-cc-dd-ee-ff     dynamic\n"
        "  192.168.10.6          11-22-33-44-55-66     dynamic\n"
    )
    with patch('subprocess.check_output', return_value=windows_arp):
        from app.scanner import _arp_fallback
        results = _arp_fallback('192.168.10.0/24')
    macs = [r['mac'] for r in results]
    assert 'AA:BB:CC:DD:EE:FF' in macs
    assert '11:22:33:44:55:66' in macs

def test_scan_updates_db_device(app):
    from app.scanner import _process_discovered_device
    from app.models import NetworkDevice
    with app.app_context():
        from app import db
        _process_discovered_device('192.168.10.5', 'AA:BB:CC:DD:EE:FF', subnet_id=None)
        dev = db.session.get(NetworkDevice, 'AA:BB:CC:DD:EE:FF')
        assert dev is not None
        assert dev.last_ip == '192.168.10.5'
```

- [ ] **Step 2: Run — expect FAIL**

```
pytest tests/test_scanner.py::test_arp_fallback_parses_windows_output -v
```
Expected: ImportError on `scanner`.

- [ ] **Step 3: Create `backend/app/scanner.py`**

```python
import re
import subprocess
import threading
import time
import ipaddress
from datetime import datetime

from . import db
from .models import NetworkDevice, NetworkSubnet
from .vendors import detect_vendor_type, enrich_device

_scan_lock = threading.Lock()
_last_scan_time = None


def _arp_fallback(cidr: str) -> list:
    """Parse OS ARP cache for hosts in the given subnet. No elevation needed."""
    network = ipaddress.ip_network(cidr, strict=False)
    results = []
    try:
        out = subprocess.check_output(['arp', '-a'], text=True, timeout=5)
        for line in out.splitlines():
            ip_m = re.search(r'(\d+\.\d+\.\d+\.\d+)', line)
            mac_m = re.search(
                r'([0-9a-fA-F]{2}[-:][0-9a-fA-F]{2}[-:][0-9a-fA-F]{2}'
                r'[-:][0-9a-fA-F]{2}[-:][0-9a-fA-F]{2}[-:][0-9a-fA-F]{2})',
                line
            )
            if ip_m and mac_m:
                try:
                    if ipaddress.ip_address(ip_m.group(1)) in network:
                        mac = mac_m.group(1).replace('-', ':').upper()
                        results.append({'ip': ip_m.group(1), 'mac': mac})
                except ValueError:
                    pass
    except Exception:
        pass
    return results


def _arp_scan(cidr: str) -> list:
    """ARP sweep a subnet. Uses scapy if available, falls back to arp -a."""
    try:
        from scapy.all import ARP, Ether, srp
        pkt = Ether(dst='ff:ff:ff:ff:ff:ff') / ARP(pdst=cidr)
        answered, _ = srp(pkt, timeout=2, verbose=False)
        return [{'ip': r.psrc, 'mac': r.hwsrc.upper()} for _, r in answered]
    except Exception:
        return _arp_fallback(cidr)


def _process_discovered_device(ip: str, mac: str, subnet_id) -> None:
    """Upsert a discovered device into the DB, enriching vendor data."""
    device_type = detect_vendor_type(mac)
    vendor_data = enrich_device(ip, mac, device_type)

    existing = db.session.get(NetworkDevice, mac)
    if existing:
        existing.last_ip = ip
        existing.last_seen = datetime.utcnow()
        existing.device_type = device_type
        existing.vendor_data = vendor_data
        existing.subnet_id = subnet_id
    else:
        db.session.add(NetworkDevice(
            mac_address=mac,
            device_type=device_type,
            last_ip=ip,
            last_seen=datetime.utcnow(),
            vendor_data=vendor_data,
            subnet_id=subnet_id,
        ))
    db.session.commit()


def run_scan_now(app) -> int:
    """Run a full scan of all active subnets. Returns count of devices found."""
    global _last_scan_time
    with _scan_lock:
        count = 0
        with app.app_context():
            subnets = NetworkSubnet.query.filter_by(active=True).all()
            for subnet in subnets:
                devices = _arp_scan(subnet.cidr)
                for d in devices:
                    _process_discovered_device(d['ip'], d['mac'], subnet.id)
                    count += 1
            _last_scan_time = datetime.utcnow()
        return count


def get_last_scan_time():
    return _last_scan_time


def start_scanner(app):
    """Start background ARP sweep thread. Call once from create_app()."""
    def _loop():
        while True:
            try:
                run_scan_now(app)
            except Exception as e:
                app.logger.error(f'Scanner error: {e}')
            time.sleep(30)

    t = threading.Thread(target=_loop, daemon=True, name='arp-scanner')
    t.start()
```

- [ ] **Step 4: Run tests — expect PASS**

```
pytest tests/test_scanner.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/scanner.py backend/tests/test_scanner.py
git commit -m "feat: ARP scanner with scapy + arp -a fallback"
```

---

## Task 8: Network routes

**Files:**
- Create: `backend/app/network_routes.py`
- Create: `backend/tests/test_network_routes.py`

- [ ] **Step 1: Write route tests**

Create `backend/tests/test_network_routes.py`:
```python
def test_create_and_list_subnet(client):
    resp = client.post('/api/network/subnets', json={
        'label': 'Management', 'cidr': '192.168.10.0/24', 'color': '#7dd3fc'
    })
    assert resp.status_code == 201
    data = resp.get_json()
    assert data['label'] == 'Management'
    subnet_id = data['id']

    resp = client.get('/api/network/subnets')
    assert resp.status_code == 200
    ids = [s['id'] for s in resp.get_json()]
    assert subnet_id in ids

def test_delete_subnet(client):
    resp = client.post('/api/network/subnets', json={
        'label': 'Test', 'cidr': '10.0.0.0/24', 'color': '#fff'
    })
    sid = resp.get_json()['id']
    resp = client.delete(f'/api/network/subnets/{sid}')
    assert resp.status_code == 204

def test_patch_device_notes(client):
    from app.models import NetworkDevice
    from app import db
    with client.application.app_context():
        dev = NetworkDevice(mac_address='11:22:33:44:55:66', device_type='unknown',
                             last_ip='10.0.0.1')
        db.session.add(dev)
        db.session.commit()
    resp = client.patch('/api/network/devices/11:22:33:44:55:66',
                        json={'notes': 'Camera village', 'label': 'GigaCore 26'})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['notes'] == 'Camera village'
    assert data['label'] == 'GigaCore 26'

def test_create_location_snapshot(client):
    resp = client.post('/api/network/locations', json={'name': 'Warner Bros Lot 3'})
    assert resp.status_code == 201
    assert resp.get_json()['name'] == 'Warner Bros Lot 3'

def test_scan_trigger(client):
    resp = client.post('/api/network/scan/trigger')
    assert resp.status_code == 202
```

- [ ] **Step 2: Run — expect FAIL**

```
pytest tests/test_network_routes.py -v
```
Expected: 404 errors (routes not registered).

- [ ] **Step 3: Create `backend/app/network_routes.py`**

```python
from datetime import datetime
from flask import Blueprint, jsonify, request, current_app
from . import db
from .models import NetworkSubnet, NetworkDevice, LocationSnapshot, LocationDevice
from .scanner import run_scan_now, get_last_scan_time
import threading

net = Blueprint('network', __name__)


# ── Subnets ──────────────────────────────────────────────────────────────── #

@net.route('/api/network/subnets', methods=['GET'])
def list_subnets():
    return jsonify([s.to_dict() for s in NetworkSubnet.query.all()])

@net.route('/api/network/subnets', methods=['POST'])
def create_subnet():
    data = request.get_json(force=True)
    label = data.get('label', '').strip()
    cidr = data.get('cidr', '').strip()
    if not label or not cidr:
        return jsonify({'error': 'label and cidr required'}), 400
    s = NetworkSubnet(
        label=label,
        cidr=cidr,
        interface_hint=data.get('interfaceHint'),
        color=data.get('color', '#7dd3fc'),
    )
    db.session.add(s)
    db.session.commit()
    return jsonify(s.to_dict()), 201

@net.route('/api/network/subnets/<int:subnet_id>', methods=['DELETE'])
def delete_subnet(subnet_id):
    s = NetworkSubnet.query.get_or_404(subnet_id)
    db.session.delete(s)
    db.session.commit()
    return '', 204


# ── Devices ───────────────────────────────────────────────────────────────── #

@net.route('/api/network/devices', methods=['GET'])
def list_devices():
    devices = NetworkDevice.query.order_by(NetworkDevice.last_seen.desc()).all()
    return jsonify([d.to_dict() for d in devices])

@net.route('/api/network/devices/<string:mac>', methods=['PATCH'])
def update_device(mac):
    dev = NetworkDevice.query.get_or_404(mac)
    data = request.get_json(force=True)
    if 'notes' in data:
        dev.notes = data['notes']
    if 'label' in data:
        dev.label = data['label']
    db.session.commit()
    return jsonify(dev.to_dict())

@net.route('/api/network/devices/<string:mac>', methods=['DELETE'])
def delete_device(mac):
    dev = NetworkDevice.query.get_or_404(mac)
    db.session.delete(dev)
    db.session.commit()
    return '', 204


# ── Scan ─────────────────────────────────────────────────────────────────── #

@net.route('/api/network/scan/trigger', methods=['POST'])
def trigger_scan():
    app = current_app._get_current_object()
    threading.Thread(target=run_scan_now, args=(app,), daemon=True).start()
    last = get_last_scan_time()
    return jsonify({
        'status': 'scan started',
        'lastScan': last.isoformat() if last else None,
    }), 202

@net.route('/api/network/scan/status', methods=['GET'])
def scan_status():
    last = get_last_scan_time()
    return jsonify({'lastScan': last.isoformat() if last else None})


# ── Locations ─────────────────────────────────────────────────────────────── #

@net.route('/api/network/locations', methods=['GET'])
def list_locations():
    locs = LocationSnapshot.query.order_by(LocationSnapshot.created_at.desc()).all()
    return jsonify([l.to_dict() for l in locs])

@net.route('/api/network/locations', methods=['POST'])
def create_location():
    data = request.get_json(force=True)
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'name required'}), 400
    snap = LocationSnapshot(name=name)
    db.session.add(snap)
    db.session.flush()
    devices = NetworkDevice.query.all()
    for dev in devices:
        db.session.add(LocationDevice(
            location_id=snap.id,
            mac_address=dev.mac_address,
            ip_at_time=dev.last_ip,
            online_at_time=(dev.last_seen is not None),
            vendor_data_at_time=dev.vendor_data,
        ))
    db.session.commit()
    return jsonify(snap.to_dict()), 201

@net.route('/api/network/locations/<int:loc_id>', methods=['GET'])
def get_location(loc_id):
    snap = LocationSnapshot.query.get_or_404(loc_id)
    return jsonify({
        **snap.to_dict(),
        'devices': [d.to_dict() for d in snap.devices],
    })

@net.route('/api/network/locations/<int:loc_id>', methods=['DELETE'])
def delete_location(loc_id):
    snap = LocationSnapshot.query.get_or_404(loc_id)
    db.session.delete(snap)
    db.session.commit()
    return '', 204
```

- [ ] **Step 4: Run tests — expect PASS**

```
pytest tests/test_network_routes.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/network_routes.py backend/tests/test_network_routes.py
git commit -m "feat: network monitoring API routes (subnets, devices, scan, locations)"
```

---

## Task 9: Register blueprint + start scanner

**Files:**
- Modify: `backend/app/__init__.py`

- [ ] **Step 1: Update `__init__.py`**

Replace the entire file content:
```python
import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
import logging

db = SQLAlchemy()
migrate = Migrate()

def create_app():
    app = Flask(__name__)
    cfg = 'config.DesktopConfig' if os.getenv('FLASK_CONFIG') == 'desktop' else 'config.DevelopmentConfig'
    app.config.from_object(cfg)

    db.init_app(app)
    migrate.init_app(app, db)

    from .routes import bp as routes_bp
    app.register_blueprint(routes_bp)

    from .network_routes import net as network_bp
    app.register_blueprint(network_bp)

    if not app.config.get('TESTING'):
        from .scanner import start_scanner
        start_scanner(app)

    app.logger.setLevel(logging.INFO)
    return app
```

- [ ] **Step 2: Verify all tests still pass**

```
pytest tests/ -v
```
Expected: all PASS — no regressions.

- [ ] **Step 3: Smoke-test the API**

With Flask running (`flask run`):
```
curl http://localhost:5000/api/network/subnets
```
Expected: `[]`

- [ ] **Step 4: Commit**

```bash
git add backend/app/__init__.py
git commit -m "feat: register network blueprint and start background scanner"
```

---

## Task 10: Frontend — NetworkMonitor shell (Layout B)

**Files:**
- Modify: `app/src/pages/NetworkMonitor.jsx` — full rewrite

**Note:** The existing file contains a DMX channel canvas viewer. This is replaced entirely. It is not referenced from any other page and is safe to replace.

- [ ] **Step 1: Replace `app/src/pages/NetworkMonitor.jsx`**

```jsx
import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import NetworkSidebar from '../components/network/NetworkSidebar';
import NetworkDeviceList from '../components/network/NetworkDeviceList';
import NetworkDeviceDetail from '../components/network/NetworkDeviceDetail';
import SaveLocationModal from '../components/network/SaveLocationModal';
import SubnetSettings from '../components/network/SubnetSettings';

export default function NetworkMonitor() {
  const [subnets, setSubnets] = useState([]);
  const [devices, setDevices] = useState([]);
  const [locations, setLocations] = useState([]);
  const [selectedSubnetId, setSelectedSubnetId] = useState(null);
  const [selectedLocationId, setSelectedLocationId] = useState(null);
  const [selectedMac, setSelectedMac] = useState(null);
  const [scanning, setScanning] = useState(false);
  const [lastScan, setLastScan] = useState(null);
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [showSubnetSettings, setShowSubnetSettings] = useState(false);

  const fetchAll = useCallback(async () => {
    const [subnetRes, deviceRes, locationRes, statusRes] = await Promise.all([
      axios.get('/api/network/subnets'),
      axios.get('/api/network/devices'),
      axios.get('/api/network/locations'),
      axios.get('/api/network/scan/status'),
    ]);
    setSubnets(subnetRes.data);
    setDevices(deviceRes.data);
    setLocations(locationRes.data);
    setLastScan(statusRes.data.lastScan);
  }, []);

  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, 15000);
    return () => clearInterval(interval);
  }, [fetchAll]);

  const handleScanNow = async () => {
    setScanning(true);
    await axios.post('/api/network/scan/trigger');
    setTimeout(async () => {
      await fetchAll();
      setScanning(false);
    }, 4000);
  };

  const handleSaveLocation = async (name) => {
    await axios.post('/api/network/locations', { name });
    setShowSaveModal(false);
    fetchAll();
  };

  const handleUpdateDevice = async (mac, patch) => {
    const res = await axios.patch(`/api/network/devices/${mac}`, patch);
    setDevices(prev => prev.map(d => d.macAddress === mac ? res.data : d));
  };

  const visibleDevices = selectedSubnetId
    ? devices.filter(d => d.subnetId === selectedSubnetId)
    : devices;

  const selectedDevice = devices.find(d => d.macAddress === selectedMac) || null;

  const secondsAgo = lastScan
    ? Math.round((Date.now() - new Date(lastScan).getTime()) / 1000)
    : null;

  return (
    <div className="flex flex-col h-screen bg-gray-950 text-gray-100">
      <div className="flex items-center justify-between px-4 py-2 bg-gray-900 border-b border-gray-800 text-sm">
        <div className="flex items-center gap-3">
          <span className="font-semibold text-white">Network Monitor</span>
          {scanning && <span className="text-blue-400 animate-pulse">● scanning…</span>}
          {!scanning && secondsAgo !== null && (
            <span className="text-gray-500">Last scan: {secondsAgo}s ago</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button onClick={handleScanNow} disabled={scanning}
            className="px-3 py-1 bg-gray-700 hover:bg-gray-600 disabled:opacity-40 rounded text-xs">
            Scan Now
          </button>
          <button onClick={() => setShowSaveModal(true)}
            className="px-3 py-1 bg-blue-700 hover:bg-blue-600 rounded text-xs">
            ⊞ Save Location
          </button>
          <button onClick={() => setShowSubnetSettings(true)}
            className="px-3 py-1 bg-gray-700 hover:bg-gray-600 rounded text-xs">
            ⚙ Subnets
          </button>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        <NetworkSidebar
          subnets={subnets}
          locations={locations}
          selectedSubnetId={selectedSubnetId}
          selectedLocationId={selectedLocationId}
          onSelectSubnet={(id) => { setSelectedSubnetId(id); setSelectedLocationId(null); }}
          onSelectLocation={(id) => { setSelectedLocationId(id); setSelectedSubnetId(null); }}
          onSaveLocation={() => setShowSaveModal(true)}
        />
        <NetworkDeviceList
          devices={visibleDevices}
          selectedMac={selectedMac}
          onSelect={setSelectedMac}
        />
        <NetworkDeviceDetail
          device={selectedDevice}
          locations={locations}
          onUpdate={handleUpdateDevice}
        />
      </div>

      {showSaveModal && (
        <SaveLocationModal
          onSave={handleSaveLocation}
          onClose={() => setShowSaveModal(false)}
        />
      )}
      {showSubnetSettings && (
        <SubnetSettings
          subnets={subnets}
          onClose={() => { setShowSubnetSettings(false); fetchAll(); }}
        />
      )}
    </div>
  );
}
```

---

## Task 11: Frontend components

**Files:**
- Create: `app/src/components/network/NetworkSidebar.jsx`
- Create: `app/src/components/network/NetworkDeviceList.jsx`
- Create: `app/src/components/network/NetworkDeviceDetail.jsx`
- Create: `app/src/components/network/SaveLocationModal.jsx`
- Create: `app/src/components/network/SubnetSettings.jsx`

- [ ] **Step 1: Create `NetworkSidebar.jsx`**

```jsx
import React from 'react';

export default function NetworkSidebar({
  subnets, locations,
  selectedSubnetId, selectedLocationId,
  onSelectSubnet, onSelectLocation, onSaveLocation,
}) {
  return (
    <div className="w-40 bg-gray-900 border-r border-gray-800 flex flex-col text-xs overflow-y-auto flex-shrink-0">
      <div className="px-3 pt-3 pb-1 text-gray-500 uppercase tracking-widest text-[10px]">
        Networks
      </div>
      <div
        onClick={() => onSelectSubnet(null)}
        className={`px-3 py-1.5 cursor-pointer rounded mx-1 mb-0.5 ${
          selectedSubnetId === null && selectedLocationId === null
            ? 'bg-blue-900 text-blue-300' : 'text-gray-400 hover:bg-gray-800'
        }`}
      >
        ● All devices
      </div>
      {subnets.map(s => (
        <div key={s.id} onClick={() => onSelectSubnet(s.id)}
          className={`px-3 py-1.5 cursor-pointer rounded mx-1 mb-0.5 ${
            selectedSubnetId === s.id ? 'bg-blue-900 text-blue-300' : 'hover:bg-gray-800'
          }`}
          style={{ color: selectedSubnetId === s.id ? undefined : s.color }}
        >
          ● {s.label}
        </div>
      ))}

      <div className="px-3 pt-4 pb-1 text-gray-500 uppercase tracking-widest text-[10px] border-t border-gray-800 mt-2">
        Locations
      </div>
      {locations.map(loc => (
        <div key={loc.id} onClick={() => onSelectLocation(loc.id)}
          className={`px-3 py-1.5 cursor-pointer rounded mx-1 mb-0.5 truncate ${
            selectedLocationId === loc.id ? 'bg-blue-900 text-blue-300' : 'text-gray-400 hover:bg-gray-800'
          }`}
          title={loc.name}
        >
          📍 {loc.name}
        </div>
      ))}
      <div onClick={onSaveLocation}
        className="px-3 py-1.5 cursor-pointer text-gray-600 hover:text-gray-400 italic mx-1 mt-1">
        + Save current…
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create `NetworkDeviceList.jsx`**

```jsx
import React from 'react';

function isOnline(device) {
  if (!device.lastSeen) return false;
  return (Date.now() - new Date(device.lastSeen).getTime()) / 1000 < 90;
}

function statusOrder(device) {
  return isOnline(device) ? 0 : 1;
}

export default function NetworkDeviceList({ devices, selectedMac, onSelect }) {
  const sorted = [...devices].sort((a, b) => statusOrder(a) - statusOrder(b));

  return (
    <div className="w-56 bg-gray-950 border-r border-gray-800 flex flex-col text-xs overflow-y-auto flex-shrink-0">
      <div className="px-3 py-2 text-gray-500 border-b border-gray-800">
        {devices.length} device{devices.length !== 1 ? 's' : ''} ·{' '}
        <span className="text-green-400">{devices.filter(isOnline).length} online</span>
        {devices.filter(d => !isOnline(d)).length > 0 && (
          <> · <span className="text-red-400">{devices.filter(d => !isOnline(d)).length} offline</span></>
        )}
      </div>

      {sorted.map(dev => {
        const online = isOnline(dev);
        const selected = dev.macAddress === selectedMac;
        const ageSeconds = dev.lastSeen
          ? Math.round((Date.now() - new Date(dev.lastSeen).getTime()) / 1000) : null;

        return (
          <div key={dev.macAddress} onClick={() => onSelect(dev.macAddress)}
            className={`px-3 py-2 cursor-pointer border-b border-gray-900 ${
              selected ? 'bg-blue-900/40' : online ? 'hover:bg-gray-900' : 'bg-red-950/30 hover:bg-red-950/50'
            }`}
          >
            <div className="flex items-center justify-between">
              <span className={online ? 'text-white' : 'text-red-400'}>
                {online ? '🟢' : '🔴'} {dev.label || dev.lastIp || dev.macAddress}
              </span>
              {online && (
                <a href={`http://${dev.lastIp}`} target="_blank" rel="noreferrer"
                  onClick={e => e.stopPropagation()}
                  className="text-blue-400 hover:text-blue-300 ml-1" title="Open device GUI">↗</a>
              )}
            </div>
            {dev.lastIp && <div className="text-blue-400 mt-0.5">{dev.lastIp}</div>}
            {!online && ageSeconds !== null && (
              <div className="text-red-500 mt-0.5">
                offline · {ageSeconds < 3600
                  ? `${Math.round(ageSeconds / 60)}m ago`
                  : `${Math.round(ageSeconds / 3600)}h ago`}
              </div>
            )}
            {dev.notes && (
              <div className="text-gray-600 truncate mt-0.5">"{dev.notes}"</div>
            )}
            {!dev.label && <div className="text-amber-500 mt-0.5">⚠ unlabeled</div>}
          </div>
        );
      })}

      {devices.length === 0 && (
        <div className="px-3 py-4 text-gray-600 text-center">
          No devices found.<br />Hit Scan Now to discover.
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Create `NetworkDeviceDetail.jsx`**

```jsx
import React, { useState, useEffect } from 'react';

function isOnline(device) {
  if (!device?.lastSeen) return false;
  return (Date.now() - new Date(device.lastSeen).getTime()) / 1000 < 90;
}

export default function NetworkDeviceDetail({ device, locations, onUpdate }) {
  const [notes, setNotes] = useState('');
  const [label, setLabel] = useState('');

  useEffect(() => {
    setNotes(device?.notes || '');
    setLabel(device?.label || '');
  }, [device?.macAddress]);

  if (!device) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-600 text-sm">
        Select a device to see details
      </div>
    );
  }

  const online = isOnline(device);
  const vd = device.vendorData || {};

  const handleBlurNotes = () => {
    if (notes !== device.notes) onUpdate(device.macAddress, { notes });
  };
  const handleBlurLabel = () => {
    if (label !== device.label) onUpdate(device.macAddress, { label });
  };

  const seenAt = locations.filter(loc =>
    loc.devices?.some(d => d.macAddress === device.macAddress)
  );

  return (
    <div className="flex-1 bg-gray-950 p-4 overflow-y-auto text-sm">
      <div className="flex items-start justify-between mb-4">
        <div>
          <input value={label} onChange={e => setLabel(e.target.value)}
            onBlur={handleBlurLabel}
            placeholder="Device label (click to edit)"
            className="bg-transparent text-white text-base font-bold border-b border-transparent hover:border-gray-600 focus:border-blue-500 outline-none w-full" />
          {device.lastIp && (
            <a href={`http://${device.lastIp}`} target="_blank" rel="noreferrer"
              className="text-blue-400 hover:underline text-xs mt-1 block">
              http://{device.lastIp} ↗ Open device GUI
            </a>
          )}
        </div>
        <span className={`text-xs px-2 py-0.5 rounded ${online ? 'bg-green-900 text-green-400' : 'bg-red-900 text-red-400'}`}>
          {online ? '● ONLINE' : '● OFFLINE'}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2 mb-4">
        {[
          ['MAC ADDRESS', device.macAddress],
          ['DEVICE TYPE', device.deviceType],
          ['FIRMWARE', vd.firmware],
          ['UPTIME', vd.uptimeSeconds
            ? `${Math.floor(vd.uptimeSeconds / 3600)}h ${Math.floor((vd.uptimeSeconds % 3600) / 60)}m`
            : null],
          ['PORTS', vd.portsTotal
            ? `${vd.portsTotal} · ${vd.portsActive} up · ${vd.portsTotal - vd.portsActive} dn`
            : null],
          ['LAST SEEN', device.lastSeen ? new Date(device.lastSeen).toLocaleTimeString() : 'never'],
        ].filter(([, val]) => val).map(([key, val]) => (
          <div key={key} className="bg-gray-900 rounded p-2">
            <div className="text-gray-500 text-[10px] uppercase tracking-wider">{key}</div>
            <div className="text-gray-200 text-xs mt-0.5 font-mono break-all">{val}</div>
          </div>
        ))}
      </div>

      <div className="bg-gray-900 rounded p-3 mb-4">
        <div className="text-gray-500 text-[10px] uppercase tracking-wider mb-2">Notes</div>
        <textarea value={notes} onChange={e => setNotes(e.target.value)}
          onBlur={handleBlurNotes} placeholder="Click to add notes…" rows={3}
          className="w-full bg-gray-950 border border-gray-800 rounded p-2 text-gray-200 text-xs resize-none outline-none focus:border-blue-600" />
        <div className="text-gray-600 text-[10px] mt-1">
          Saved to MAC address · persists across locations and IP changes
        </div>
      </div>

      {seenAt.length > 0 && (
        <div className="bg-gray-900 rounded p-3">
          <div className="text-gray-500 text-[10px] uppercase tracking-wider mb-2">Seen at Locations</div>
          {seenAt.map(loc => {
            const entry = loc.devices?.find(d => d.macAddress === device.macAddress);
            return (
              <div key={loc.id} className="text-xs text-gray-400 py-1 border-b border-gray-800 last:border-0">
                📍 {loc.name}
                {entry?.ipAtTime && <span className="text-gray-600"> · IP was {entry.ipAtTime}</span>}
                <span className="text-gray-600"> · {new Date(loc.createdAt).toLocaleDateString()}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Create `SaveLocationModal.jsx`**

```jsx
import React, { useState } from 'react';

export default function SaveLocationModal({ onSave, onClose }) {
  const [name, setName] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    if (name.trim()) onSave(name.trim());
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-gray-900 rounded-lg p-6 w-80 shadow-2xl border border-gray-700">
        <h2 className="text-white font-semibold mb-4">Save Location Snapshot</h2>
        <form onSubmit={handleSubmit}>
          <input autoFocus value={name} onChange={e => setName(e.target.value)}
            placeholder="e.g. Warner Bros Lot 3 - Stage A"
            className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-white text-sm outline-none focus:border-blue-500 mb-4" />
          <div className="flex gap-2 justify-end">
            <button type="button" onClick={onClose}
              className="px-4 py-1.5 text-sm text-gray-400 hover:text-white">Cancel</button>
            <button type="submit" disabled={!name.trim()}
              className="px-4 py-1.5 text-sm bg-blue-700 hover:bg-blue-600 disabled:opacity-40 rounded text-white">
              Save
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Create `SubnetSettings.jsx`**

```jsx
import React, { useState } from 'react';
import axios from 'axios';

const COLORS = ['#7dd3fc', '#86efac', '#fde68a', '#c4b5fd', '#f9a8d4', '#fb923c'];

export default function SubnetSettings({ subnets, onClose }) {
  const [label, setLabel] = useState('');
  const [cidr, setCidr] = useState('');
  const [color, setColor] = useState(COLORS[0]);

  const handleAdd = async (e) => {
    e.preventDefault();
    if (!label.trim() || !cidr.trim()) return;
    await axios.post('/api/network/subnets', { label: label.trim(), cidr: cidr.trim(), color });
    setLabel(''); setCidr('');
    onClose();
  };

  const handleDelete = async (id) => {
    await axios.delete(`/api/network/subnets/${id}`);
    onClose();
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-gray-900 rounded-lg p-6 w-96 shadow-2xl border border-gray-700">
        <h2 className="text-white font-semibold mb-4">Subnet Settings</h2>
        <div className="mb-4 space-y-1">
          {subnets.map(s => (
            <div key={s.id} className="flex items-center justify-between bg-gray-800 rounded px-3 py-2">
              <div>
                <span style={{ color: s.color }} className="mr-2">●</span>
                <span className="text-white text-sm">{s.label}</span>
                <span className="text-gray-500 text-xs ml-2 font-mono">{s.cidr}</span>
              </div>
              <button onClick={() => handleDelete(s.id)}
                className="text-gray-600 hover:text-red-400 text-xs">✕</button>
            </div>
          ))}
          {subnets.length === 0 && (
            <p className="text-gray-500 text-sm">No subnets configured yet.</p>
          )}
        </div>
        <form onSubmit={handleAdd} className="space-y-2 border-t border-gray-700 pt-4">
          <div className="text-gray-400 text-xs mb-2">Add subnet</div>
          <input value={label} onChange={e => setLabel(e.target.value)}
            placeholder="Label (e.g. Management)"
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-white text-sm outline-none focus:border-blue-500" />
          <input value={cidr} onChange={e => setCidr(e.target.value)}
            placeholder="CIDR (e.g. 192.168.10.0/24)"
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-white text-sm font-mono outline-none focus:border-blue-500" />
          <div className="flex gap-2">
            {COLORS.map(c => (
              <button key={c} type="button" onClick={() => setColor(c)}
                style={{ background: c }}
                className={`w-6 h-6 rounded-full border-2 ${color === c ? 'border-white' : 'border-transparent'}`} />
            ))}
          </div>
          <div className="flex gap-2 justify-end pt-1">
            <button type="button" onClick={onClose}
              className="px-4 py-1.5 text-sm text-gray-400 hover:text-white">Close</button>
            <button type="submit" disabled={!label.trim() || !cidr.trim()}
              className="px-4 py-1.5 text-sm bg-blue-700 hover:bg-blue-600 disabled:opacity-40 rounded text-white">
              Add
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Verify full page end-to-end**

With both servers running, open `http://localhost:5173/network`:
- Sidebar renders with "All devices"
- Click ⚙ Subnets → add `192.168.1.0/24` labeled `Test`
- Click Scan Now → spinner animates for ~4s → device list refreshes
- Click a discovered device → detail panel shows MAC, IP, notes field
- Edit notes → click away → notes persist on refresh
- Click ⊞ Save Location → name it → appears in sidebar Locations

- [ ] **Step 7: Commit**

```bash
git add app/src/pages/NetworkMonitor.jsx app/src/components/network/
git commit -m "feat: network monitoring dashboard frontend (Layout B)"
```

---

## Task 12: Add scapy to requirements

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Install and pin scapy**

```
pip install scapy
pip freeze | grep scapy
```
Note the exact version (e.g. `scapy==2.6.1`).

- [ ] **Step 2: Add to `backend/requirements.txt`**

Append:
```
# Requires "Run as Administrator" on Windows for ARP scanning.
# Falls back to `arp -a` parsing automatically if elevation is unavailable.
scapy==2.6.1
```
(use the exact version from step 1)

- [ ] **Step 3: Commit**

```bash
git add backend/requirements.txt
git commit -m "deps: add scapy for ARP network scanning"
```

---

## Self-Review

**Spec coverage:**

| Spec Requirement | Task |
|---|---|
| ARP sweep every 30s + manual trigger | Tasks 7, 8 |
| Vendor API enrichment: Luminex, Ubiquiti, Starlink, Swisson | Tasks 5, 6 |
| MAC-keyed notes + labels persisting across IP changes | Tasks 2, 8, 11 |
| Location snapshots (save, list, view) | Tasks 8, 11 |
| Subnet configuration UI | Task 11 |
| Sidebar + device list + detail panel (Layout B) | Tasks 10–11 |
| Offline devices stay in list with "last seen X ago" | Task 11 |
| Unlabeled device ⚠ badge | Task 11 |
| IP ↗ link to device GUI | Tasks 11 |
| scapy with arp -a fallback | Task 7 |
| 4 DB tables + migration | Tasks 2, 3 |
| All /api/network/* routes | Task 8 |

All spec requirements covered. ✓

**Placeholder scan:** No TBDs. Swisson API path noted as firmware-dependent — accurate, not a placeholder. Starlink v1 as ping-only with v2 note — accurate, not a placeholder. ✓

**Type consistency:** `macAddress` used in all `to_dict()` returns and all React props. `lastSeen` consistent throughout. `vendorData` consistent. `subnetId` consistent. ✓
