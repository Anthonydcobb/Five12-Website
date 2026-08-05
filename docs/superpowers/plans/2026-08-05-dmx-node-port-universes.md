# DMX Node Port/Universe Table Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Selecting a Swisson or ACPD DMX node in the Network tab shows a per-port table of universe, protocol, direction and status, live as of the moment you clicked.

**Architecture:** One reader on the nodes' `/model/status` JSON endpoint, added to the `_enrich_model_device_api` path that `swisson` and `acpd` already share, storing a `ports` list in `vendor_data`. A read-only Flask route re-reads it live on demand and falls back to the stored copy. A new React component paints the cached rows instantly on selection, then swaps in the live result.

**Tech Stack:** Flask + SQLAlchemy backend, `requests` for device HTTP, pytest. React 18 frontend, axios, vitest + @testing-library/react.

**Spec:** `docs/superpowers/specs/2026-08-05-dmx-node-port-universes-design.md`

## Global Constraints

- **Read-only.** No code in this plan writes to a DMX node, and the live route never writes to the database.
- **Never guess an enum.** Only these codes are confirmed: `protocol` 1 = `Art-Net`, 2 = `sACN`; `direction` 1 = `Output`; `status` 3 = `OK`. Any other code renders as the literal string `code N`. Do not add speculative mappings.
- **Failure returns `{}` or an absent key, never an exception.** `enrich_device` runs inside the scanner sweep; one dead node must not take the sweep down, and a missed poll must not erase a stored patch.
- **Do not modify** `app/src/pages/Devices.jsx`, the Stardust output cards, or the existing `UNIVERSES OUTPUTTING` chip row in `NetworkMonitor.jsx`. They are out of scope.
- HTTP timeout to devices is **3 seconds**, matching `_enrich_model_device_api`.
- Backend tests run from `C:\dev\Five12-TheApp\backend`; frontend tests from `C:\dev\Five12-TheApp\app`.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/vendors/__init__.py` (modify) | `read_port_status(ip)` — fetch and decode `/model/status`. Merged into `_enrich_model_device_api`. |
| `backend/tests/test_vendors.py` (modify) | Reader tests, using the existing `_Resp` mock pattern. |
| `backend/app/network_routes.py` (modify) | `GET /devices/<mac>/ports` — live read with cached fallback. |
| `backend/tests/test_device_ports.py` (create) | Route tests, using the existing `client` / `db` fixtures. |
| `app/src/components/PortTable.jsx` (create) | The table, plus its own fetch lifecycle. |
| `app/src/components/PortTable.test.jsx` (create) | Component tests. |
| `app/src/pages/NetworkMonitor.jsx` (modify) | Render `<PortTable>` inside `DeviceDetail`. |

---

### Task 1: The `/model/status` reader

**Files:**
- Modify: `backend/app/vendors/__init__.py` (add near `_enrich_model_device_api`, around line 273)
- Test: `backend/tests/test_vendors.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `read_port_status(ip: str) -> dict` — returns `{'ports': [...]}` or `{}`. Each port dict is `{'port': int (1-based), 'universe': int, 'protocol': str, 'direction': str, 'status': str}`. Task 2 imports this function by name. Task 3 consumes the same shape as JSON.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_vendors.py`:

```python
# Verbatim GET http://10.31.8.51/model/status on 2026-08-05, the Swisson
# XND-8. Universes 21/42/91/104 on ports 1-4 matched the device's own web
# GUI in a screenshot taken at the same moment.
XND8_MODEL_STATUS = {
    'modelName': 'XND-8',
    'locate': False,
    'longArtNetName': 'SWISSON XND-8',
    'artNetMode': 1,
    'addressDisplayMode': 0,
    'ports': [
        {'status': 3, 'direction': 1, 'protocol': 2, 'universe': 21},
        {'status': 3, 'direction': 1, 'protocol': 2, 'universe': 42},
        {'status': 3, 'direction': 1, 'protocol': 2, 'universe': 91},
        {'status': 3, 'direction': 1, 'protocol': 2, 'universe': 104},
        {'status': 3, 'direction': 1, 'protocol': 2, 'universe': 44},
        {'status': 3, 'direction': 1, 'protocol': 2, 'universe': 41},
        {'status': 3, 'direction': 1, 'protocol': 2, 'universe': 41},
        {'status': 3, 'direction': 1, 'protocol': 2, 'universe': 1},
    ],
}

# Verbatim GET http://10.9.15.101/model/status on 2026-08-05. Same contract,
# four ports instead of eight — which is why one reader serves both vendors.
ACPD_MODEL_STATUS = {
    'modelName': 'PDXND-4-1',
    'locate': False,
    'longArtNetName': 'ACPD NODE ENET/DMX (PDXND-4-1)',
    'artNetMode': 1,
    'addressDisplayMode': 0,
    'ports': [
        {'status': 3, 'direction': 1, 'protocol': 2, 'universe': 1},
        {'status': 3, 'direction': 1, 'protocol': 2, 'universe': 2},
        {'status': 3, 'direction': 1, 'protocol': 2, 'universe': 3},
        {'status': 3, 'direction': 1, 'protocol': 2, 'universe': 4},
    ],
}


def test_port_status_numbers_ports_from_one():
    """Array index is the port number, zero-based — the operator reads
    "Port 1" off the node's front panel, so the API must say 1, not 0."""
    with patch('app.vendors.requests.get', return_value=_Resp(XND8_MODEL_STATUS)):
        ports = vendors.read_port_status('10.31.8.51')['ports']

    assert len(ports) == 8
    assert [p['port'] for p in ports] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert [p['universe'] for p in ports] == [21, 42, 91, 104, 44, 41, 41, 1]


def test_port_status_decodes_confirmed_enums():
    with patch('app.vendors.requests.get', return_value=_Resp(XND8_MODEL_STATUS)):
        port1 = vendors.read_port_status('10.31.8.51')['ports'][0]

    assert port1['protocol'] == 'sACN'
    assert port1['direction'] == 'Output'
    assert port1['status'] == 'OK'


def test_port_status_reads_the_acpd_identically():
    """Both vendors serve this contract, so one reader covers all 16 nodes."""
    with patch('app.vendors.requests.get', return_value=_Resp(ACPD_MODEL_STATUS)):
        ports = vendors.read_port_status('10.9.15.101')['ports']

    assert len(ports) == 4
    assert [p['universe'] for p in ports] == [1, 2, 3, 4]


def test_an_unseen_code_is_shown_raw_not_guessed():
    """Every one of the 68 ports on the rig reads status 3 / direction 1 /
    protocol 2, so input, disabled and dead ports are genuinely undecoded. A
    confidently wrong status on a troubleshooting screen is worse than a raw
    number, because the operator stops looking at it."""
    payload = {'ports': [{'status': 9, 'direction': 7, 'protocol': 5, 'universe': 12}]}
    with patch('app.vendors.requests.get', return_value=_Resp(payload)):
        port1 = vendors.read_port_status('10.31.8.51')['ports'][0]

    assert port1['status'] == 'code 9'
    assert port1['direction'] == 'code 7'
    assert port1['protocol'] == 'code 5'
    assert port1['universe'] == 12       # the row is still emitted


def test_port_status_survives_an_unreachable_node():
    """The scanner enriches inside the sweep; one dead node cannot raise."""
    with patch('app.vendors.requests.get', side_effect=OSError('unreachable')):
        assert vendors.read_port_status('10.31.8.51') == {}


def test_port_status_ignores_a_body_without_ports():
    """A node answering some other JSON must yield {} rather than a KeyError,
    so the caller's `if vendor_data:` guard keeps the last known patch."""
    with patch('app.vendors.requests.get', return_value=_Resp({'modelName': 'XND-8'})):
        assert vendors.read_port_status('10.31.8.51') == {}


def test_enrichment_attaches_ports_to_vendor_data():
    """This is what puts the table in the Network tab — reached through the
    same enricher both vendors already share for /model/device."""
    with patch('app.vendors.requests.get', return_value=_Resp(XND8_MODEL_STATUS)):
        data = vendors.enrich_device('10.31.8.51', '28:36:38:C0:39:C0', 'swisson')

    assert [p['universe'] for p in data['ports']] == [21, 42, 91, 104, 44, 41, 41, 1]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run from `C:\dev\Five12-TheApp\backend`:

```bash
python -m pytest tests/test_vendors.py -v
```

Expected: the seven new tests FAIL with `AttributeError: module 'app.vendors' has no attribute 'read_port_status'`. The eleven pre-existing tests still PASS.

- [ ] **Step 3: Write the implementation**

In `backend/app/vendors/__init__.py`, add immediately above `_enrich_model_device_api`:

```python
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


def read_port_status(ip: str) -> dict:
    """Per-port universe/protocol/direction/status from /model/status.

    Served identically by the Swisson XND-8 (8 ports) and the ACPD PDXND-4-1
    (4 ports) — the same shared contract as /model/device. Array index is the
    port number, zero-based, so it is reported here 1-based.

    Note /model/port is NOT a per-port endpoint: it ignores ?index=, ?port=
    and ?portIndex=, always returns one record, and reports a protocol that
    contradicts this one. Do not cross-reference the two.

    Returns {} on any failure, so the scanner's `if vendor_data:` guard leaves
    a previously stored patch intact — one missed poll must not erase it.
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
    return {'ports': [
        {
            'port': i + 1,
            'universe': p.get('universe'),
            'protocol': _port_enum(_PORT_PROTOCOL, p.get('protocol')),
            'direction': _port_enum(_PORT_DIRECTION, p.get('direction')),
            'status': _port_enum(_PORT_STATUS, p.get('status')),
        }
        for i, p in enumerate(ports)
    ]}
```

Then replace the body of `_enrich_model_device_api` so it merges the port read in. The two endpoints are independent — a node that answers one but not the other must still contribute what it has:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/test_vendors.py -v
```

Expected: all 18 PASS. The pre-existing `test_acpd_enrichment_reads_the_device_report` and `test_acpd_enrichment_survives_an_unreachable_node` must still pass unchanged — the first patches `requests.get` for every call, so the extra `/model/status` read receives a body with no `ports` key and correctly contributes nothing.

- [ ] **Step 5: Run the whole backend suite for regressions**

```bash
python -m pytest tests/ -q
```

Expected: no new failures. `test_clear_offline.py` monkeypatches `enrich_device` wholesale and is unaffected.

- [ ] **Step 6: Commit**

```bash
git add backend/app/vendors/__init__.py backend/tests/test_vendors.py
git commit -m "feat(network): read per-port universes from /model/status"
```

---

### Task 2: Live read route

**Files:**
- Modify: `backend/app/network_routes.py` (add after `update_device`, around line 195)
- Test: `backend/tests/test_device_ports.py` (create)

**Interfaces:**
- Consumes: `vendors.read_port_status(ip) -> dict` from Task 1.
- Produces: `GET /api/network/devices/<mac>/ports` returning `{'ports': [...], 'live': bool, 'asOf': str|None}`. Task 3 consumes this JSON.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_device_ports.py`:

```python
"""Live per-port read with a cached fallback.

The universe on a port changes exactly when somebody is standing at the node
repatching it, and enrichment only runs on the 300s discovery sweep. A table
that is five minutes behind is wrong at the one moment it is being read, so
this route re-reads the node on demand — but keeps showing the last known
patch when the node has gone away, rather than blanking.
"""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app.models import NetworkDevice


PORTS = [
    {'port': 1, 'universe': 21, 'protocol': 'sACN', 'direction': 'Output', 'status': 'OK'},
    {'port': 2, 'universe': 42, 'protocol': 'sACN', 'direction': 'Output', 'status': 'OK'},
]


@pytest.fixture
def node(db):
    row = NetworkDevice(
        mac_address='28:36:38:C0:39:C0',
        device_type='swisson',
        last_ip='10.31.8.51',
        last_seen=datetime.utcnow() - timedelta(seconds=30),
        vendor_data={'model': 'XND-8', 'ports': PORTS},
    )
    db.session.add(row)
    db.session.commit()
    yield row
    db.session.delete(row)
    db.session.commit()


def test_a_reachable_node_is_read_live(client, node):
    fresh = [dict(PORTS[0], universe=77), PORTS[1]]
    with patch('app.vendors.read_port_status', return_value={'ports': fresh}):
        res = client.get(f'/api/network/devices/{node.mac_address}/ports')

    assert res.status_code == 200
    body = res.get_json()
    assert body['live'] is True
    assert body['ports'][0]['universe'] == 77


def test_a_live_read_does_not_overwrite_stored_vendor_data(client, db, node):
    """Read path only. A live value disagreeing with the sweep is not evidence
    the sweep was wrong, and writing here would race the scanner."""
    fresh = [dict(PORTS[0], universe=77), PORTS[1]]
    with patch('app.vendors.read_port_status', return_value={'ports': fresh}):
        client.get(f'/api/network/devices/{node.mac_address}/ports')

    db.session.refresh(node)
    assert node.vendor_data['ports'][0]['universe'] == 21


def test_an_unreachable_node_falls_back_to_the_stored_patch(client, node):
    """The last known patch is still useful — better than an empty panel."""
    with patch('app.vendors.read_port_status', return_value={}):
        res = client.get(f'/api/network/devices/{node.mac_address}/ports')

    body = res.get_json()
    assert body['live'] is False
    assert body['ports'][0]['universe'] == 21
    assert body['asOf'].endswith('Z')


def test_an_unreachable_node_with_nothing_stored_returns_an_empty_list(client, db):
    row = NetworkDevice(mac_address='AA:BB:CC:00:00:09', last_ip='10.0.0.9')
    db.session.add(row)
    db.session.commit()
    try:
        with patch('app.vendors.read_port_status', return_value={}):
            res = client.get('/api/network/devices/AA:BB:CC:00:00:09/ports')
        assert res.status_code == 200
        assert res.get_json() == {'ports': [], 'live': False, 'asOf': None}
    finally:
        db.session.delete(row)
        db.session.commit()


def test_a_device_with_no_ip_is_not_probed(client, db):
    """Never call requests.get(None) — a device known only by MAC has no
    address to read."""
    row = NetworkDevice(mac_address='AA:BB:CC:00:00:0A', vendor_data={'ports': PORTS})
    db.session.add(row)
    db.session.commit()
    try:
        with patch('app.vendors.read_port_status') as reader:
            res = client.get('/api/network/devices/AA:BB:CC:00:00:0A/ports')
        reader.assert_not_called()
        assert res.get_json()['live'] is False
        assert res.get_json()['ports'][0]['universe'] == 21
    finally:
        db.session.delete(row)
        db.session.commit()


def test_an_unknown_mac_is_404(client):
    res = client.get('/api/network/devices/FF:FF:FF:FF:FF:FF/ports')
    assert res.status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python -m pytest tests/test_device_ports.py -v
```

Expected: all seven FAIL with 404 responses (the route does not exist yet); the `test_an_unknown_mac_is_404` case may pass incidentally — that is fine, it must still pass at the end.

- [ ] **Step 3: Write the implementation**

Add to `backend/app/network_routes.py`, after `update_device`:

```python
@net.get('/devices/<mac>/ports')
def device_ports(mac):
    """Per-port patch for a DMX node, read live, falling back to the sweep.

    Enrichment only runs on the 300s discovery sweep, so the stored copy can be
    five minutes behind — and it is out of date at exactly the moment an
    operator is repatching the node and looking at this panel. So the node is
    re-read on demand.

    Strictly read-only: it never writes vendor_data. A live value that
    disagrees with the stored one is not evidence the sweep was wrong, and
    writing here would race the scanner.
    """
    from . import vendors

    device = db.session.get(NetworkDevice, mac)
    if device is None:
        return jsonify({'error': 'not found'}), 404

    if device.last_ip:
        live = vendors.read_port_status(device.last_ip)
        if live.get('ports'):
            return jsonify({'ports': live['ports'], 'live': True})

    return jsonify({
        'ports': (device.vendor_data or {}).get('ports') or [],
        'live': False,
        'asOf': _utc_iso(device.last_seen),
    })
```

Two import notes:

- Use `from . import vendors` then `vendors.read_port_status(...)`, **not** `from .vendors import read_port_status`. The tests patch `app.vendors.read_port_status`, which only takes effect through the module attribute.
- `_utc_iso` is defined at `backend/app/models.py:228`. Add it to the existing top-level import on line 5 rather than importing it inside the function:

```python
from .models import NetworkSubnet, NetworkDevice, LocationSnapshot, LocationDevice, _utc_iso
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/test_device_ports.py -v
```

Expected: 7 PASS.

- [ ] **Step 5: Run the whole backend suite**

```bash
python -m pytest tests/ -q
```

Expected: no new failures.

- [ ] **Step 6: Commit**

```bash
git add backend/app/network_routes.py backend/tests/test_device_ports.py
git commit -m "feat(network): add live per-port read endpoint"
```

---

### Task 3: The PortTable component

**Files:**
- Create: `app/src/components/PortTable.jsx`
- Create: `app/src/components/PortTable.test.jsx`
- Modify: `app/src/pages/NetworkMonitor.jsx` (import at line 3; render inside `DeviceDetail`)

**Interfaces:**
- Consumes: `GET /api/network/devices/<mac>/ports` from Task 2.
- Produces: `<PortTable device={device} />`, default export. `device` is the `NetworkMonitor` device object (`macAddress`, `vendorData.ports`).

- [ ] **Step 1: Write the failing tests**

Create `app/src/components/PortTable.test.jsx`:

```jsx
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import axios from 'axios'
import PortTable from './PortTable'

vi.mock('axios')

const CACHED = [
  { port: 1, universe: 21, protocol: 'sACN', direction: 'Output', status: 'OK' },
  { port: 2, universe: 42, protocol: 'sACN', direction: 'Output', status: 'OK' },
]

const DEVICE = {
  macAddress: '28:36:38:C0:39:C0',
  lastSeen: new Date().toISOString(),
  vendorData: { model: 'XND-8', ports: CACHED },
}

beforeEach(() => {
  vi.resetAllMocks()
})

describe('PortTable', () => {
  it('paints the cached patch before the live read resolves', () => {
    axios.get.mockReturnValue(new Promise(() => {}))   // never settles
    render(<PortTable device={DEVICE} />)
    expect(screen.getByText('21')).toBeInTheDocument()
    expect(screen.getByText('42')).toBeInTheDocument()
  })

  it('replaces the cached patch with the live one', async () => {
    axios.get.mockResolvedValue({ data: {
      live: true,
      ports: [{ ...CACHED[0], universe: 77 }, CACHED[1]],
    } })
    render(<PortTable device={DEVICE} />)
    expect(await screen.findByText('77')).toBeInTheDocument()
    expect(screen.queryByText('21')).not.toBeInTheDocument()
  })

  it('marks the patch stale when the node did not answer', async () => {
    axios.get.mockResolvedValue({ data: {
      live: false, ports: CACHED, asOf: new Date(Date.now() - 240_000).toISOString(),
    } })
    render(<PortTable device={DEVICE} />)
    expect(await screen.findByText(/4m ago/)).toBeInTheDocument()
  })

  it('keeps the cached patch when the request errors', async () => {
    axios.get.mockRejectedValue(new Error('network'))
    render(<PortTable device={DEVICE} />)
    await waitFor(() => expect(axios.get).toHaveBeenCalled())
    expect(screen.getByText('21')).toBeInTheDocument()
  })

  it('renders nothing for a device with no ports', () => {
    const { container } = render(
      <PortTable device={{ macAddress: 'AA:BB:CC:00:00:01', vendorData: {} }} />
    )
    expect(container).toBeEmptyDOMElement()
    expect(axios.get).not.toHaveBeenCalled()
  })

  it('shows an undecoded status as its raw code rather than blank', async () => {
    axios.get.mockResolvedValue({ data: {
      live: true,
      ports: [{ port: 1, universe: 5, protocol: 'sACN', direction: 'Output', status: 'code 9' }],
    } })
    render(<PortTable device={DEVICE} />)
    expect(await screen.findByText('code 9')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run from `C:\dev\Five12-TheApp\app`:

```bash
npx vitest run src/components/PortTable.test.jsx
```

Expected: FAIL — `Failed to resolve import "./PortTable"`.

- [ ] **Step 3: Write the component**

Create `app/src/components/PortTable.jsx`:

```jsx
import React, { useState, useEffect } from 'react';
import axios from 'axios';

// Same UTC handling as NetworkMonitor.jsx: a timestamp with no offset must be
// read as UTC, never as local, or the elapsed time comes out negative.
function timeAgo(iso) {
  if (!iso) return 'unknown';
  const hasZone = /[Zz]$|[+-]\d{2}:?\d{2}$/.test(iso);
  const secs = Math.floor((Date.now() - new Date(hasZone ? iso : `${iso}Z`)) / 1000);
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  return `${Math.floor(secs / 3600)}h ago`;
}

const CELL = { padding: '3px 8px', fontSize: 12, textAlign: 'left' };
const HEAD = { ...CELL, color: 'var(--color-text-muted)', fontSize: 10, letterSpacing: 1 };

export default function PortTable({ device }) {
  const cached = device.vendorData?.ports;
  const [ports, setPorts] = useState(cached || []);
  const [stale, setStale] = useState(null);

  useEffect(() => {
    // Paint the cached patch immediately on selection, then correct it. The
    // stored copy comes from the 300s sweep, so it is exactly what is wrong
    // while somebody is repatching the node in front of you.
    setPorts(device.vendorData?.ports || []);
    setStale(null);
    if (!device.vendorData?.ports?.length) return;

    let cancelled = false;
    axios.get(`/api/network/devices/${device.macAddress}/ports`)
      .then(res => {
        if (cancelled) return;
        if (res.data.ports?.length) setPorts(res.data.ports);
        setStale(res.data.live ? null : res.data.asOf || null);
      })
      // Keep showing the cached patch. A failed refresh is not a reason to
      // throw away the last thing we knew.
      .catch(() => {});
    return () => { cancelled = true; };
  }, [device.macAddress]);

  if (!cached?.length) return null;

  return (
    <div style={{ background: 'var(--color-surface)', borderRadius: 4, padding: 8, marginBottom: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4 }}>
        <div style={{ color: 'var(--color-text-muted)', fontSize: 11, letterSpacing: 1 }}>PORTS</div>
        {stale !== null && (
          <div style={{ color: 'var(--color-warn)', fontSize: 10 }}>
            node did not answer · as of {timeAgo(stale)}
          </div>
        )}
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={HEAD}>PORT</th>
            <th style={HEAD}>UNIVERSE</th>
            <th style={HEAD}>PROTOCOL</th>
            <th style={HEAD}>DIRECTION</th>
            <th style={HEAD}>STATUS</th>
          </tr>
        </thead>
        <tbody>
          {ports.map(p => (
            <tr key={p.port} style={{ borderTop: '1px solid var(--color-border)' }}>
              <td style={{ ...CELL, color: 'var(--color-text-muted)', fontVariantNumeric: 'tabular-nums' }}>{p.port}</td>
              <td style={{ ...CELL, color: 'var(--color-gel)', fontVariantNumeric: 'tabular-nums' }}>{p.universe}</td>
              <td style={{ ...CELL, color: 'var(--color-text)' }}>{p.protocol}</td>
              <td style={{ ...CELL, color: 'var(--color-text)' }}>{p.direction}</td>
              {/* Green ONLY for a confirmed OK. An unmapped code such as
                  'code 9' renders neutral — we can no more claim a state is
                  bad than claim it is good. */}
              <td style={{ ...CELL, color: p.status === 'OK' ? 'var(--color-online)' : 'var(--color-text-muted)' }}>
                {p.status}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
npx vitest run src/components/PortTable.test.jsx
```

Expected: 6 PASS.

- [ ] **Step 5: Wire it into the Network tab**

In `app/src/pages/NetworkMonitor.jsx`, add the import after line 3:

```jsx
import PortTable from '../components/PortTable';
```

Then in `DeviceDetail`, insert the component between the `universes` block and the `NOTES` panel — i.e. immediately after the closing `)}` of the `{universes && (...)}` block, before `<div ...>NOTES`:

```jsx
      <PortTable device={device} />
```

Do not alter the `universes` block itself. Stardust reports a flat universe list with no port mapping and keeps that panel.

- [ ] **Step 6: Run the full frontend suite for regressions**

```bash
npm test
```

Expected: no new failures.

- [ ] **Step 7: Commit**

```bash
git add app/src/components/PortTable.jsx app/src/components/PortTable.test.jsx app/src/pages/NetworkMonitor.jsx
git commit -m "feat(network): show per-port universe table on DMX nodes"
```

---

### Task 4: Verify on the actual rig

Tests prove the parsing. They cannot prove the app can reach a node — the app and the test suite run under different Python interpreters, and every node here is on a 10.x address that leaves via the show NIC.

**Files:**
- Modify: `docs/superpowers/specs/2026-08-05-dmx-node-port-universes-design.md` (status line)

- [ ] **Step 1: Confirm the endpoint still answers from this machine**

```bash
curl -s -m 4 http://10.31.8.51/model/status
```

Expected: JSON with an eight-entry `ports` array. If this fails, stop — the show NIC path is down and nothing below will work.

- [ ] **Step 2: Confirm the route answers from the running backend**

With the app running:

```bash
curl -s http://localhost:5000/api/network/devices/28:36:38:C0:39:C0/ports
```

Expected: `{"live": true, "ports": [...]}` with eight entries. `"live": false` means the backend process cannot reach the node even though step 1 could — that is the app-vs-test interpreter/NIC difference, and it is the finding this task exists to catch.

- [ ] **Step 3: Confirm it on screen**

Open the Network tab, select the Swisson XND-8, and check the PORTS table shows ports 1–8 with universes matching the node's own web GUI at `http://10.31.8.51`. Then select an ACPD node and confirm four rows.

- [ ] **Step 4: Confirm the out-of-scope panels are untouched**

Select a Stardust unit. Its `UNIVERSES OUTPUTTING` chip row must render exactly as before and show no PORTS table. Open the Devices tab and confirm it is unchanged.

- [ ] **Step 5: Update the spec status and commit**

Change the spec's status line to `implemented 2026-08-05` and record anything step 2 revealed.

```bash
git add docs/superpowers/specs/2026-08-05-dmx-node-port-universes-design.md
git commit -m "docs: mark DMX port table spec implemented"
```

---

## Notes for the implementer

- **The enum table is the whole point of the honesty here.** If you find yourself adding `_PORT_STATUS = {0: 'No Signal', 1: 'Error', ...}` because it seems obvious, stop. Nobody has seen those codes on this hardware. `code 0` on screen is a question the operator can answer in ten seconds at the node; a wrong label is one they will never think to ask.
- **`/model/port` looks useful and is not.** It ignores every index parameter and reports a protocol that contradicts `/model/status`.
- **Do not add a polling interval to `PortTable`.** It refreshes on selection. A timer here would hit every node in the rack on a loop for a panel nobody is looking at.
