# GigaCore Port-to-Device Map Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show which device is on which port of a Luminex GigaCore switch, and on every other device show which switch port it sits behind — without ever writing to a switch.

**Architecture:** Four read-only SNMP walks per switch build a port→MACs map stored in `vendor_data` on the 300s sweep. A pure function inverts the stored maps of all switches to answer "where is this device". Two routes serve them; two React components render them, reusing the cached-then-live pattern from the DMX `PortTable`.

**Tech Stack:** Flask + SQLAlchemy, `puresnmp` (SNMP v2c, community `public`), pytest. React 18, axios, vitest + @testing-library/react.

**Spec:** `docs/superpowers/specs/2026-08-06-gigacore-port-device-map-design.md`

## Global Constraints

- **SNMP GET and WALK only. No SET, ever** — not behind a flag, not in a helper. The rig is live and a config change would be visible on stage. Task 1 pins this with a test.
- **No HTTP writes to a switch.** Their web GUIs answer 401 and stay untouched.
- **The routes never write to the database.** The scanner concurrently updates the same rows.
- **Only a port with exactly one MAC behind it may be described as a device's location.** More than one means "behind", never "on" — a forwarding database records where a MAC was *last seen*, not what is plugged in where. Reporting an uplink port as a patch point is the defect this feature exists to avoid.
- **A MAC absent from the app's device table renders as a raw MAC.** Never invent a name.
- FDB counts are a live snapshot — CARL's port 12 read 79 MACs once and 74 minutes later. **Every test fixture is a captured payload; no test may assert a live switch still reports a given number.**
- Do not modify `PortTable.jsx`, the `UNIVERSES OUTPUTTING` chip row, `Devices.jsx`, or Stardust code.
- Do not touch `_gigacore_read` / `_gigacore_write` in `routes.py` — a separate, speculative write path, out of scope.
- Backend tests run from `C:\dev\Five12-TheApp\backend`; frontend from `C:\dev\Five12-TheApp\app`.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/vendors/__init__.py` (modify) | `_snmp_walk_suffix` (new helper), `read_switch_ports(ip)`, `find_switch_port(mac, switches)` |
| `backend/tests/test_switch_ports.py` (create) | Reader + helper + read-only pin |
| `backend/tests/test_switch_lookup.py` (create) | Reverse-index tests (pure, no I/O) |
| `backend/app/network_routes.py` (modify) | `GET /devices/<mac>/switch-ports`, `GET /devices/<mac>/uplink` |
| `backend/tests/test_switch_routes.py` (create) | Route tests |
| `app/src/components/SwitchPortTable.jsx` (create) | Switch-side port table |
| `app/src/components/SwitchPortTable.test.jsx` (create) | Its tests |
| `app/src/components/UplinkLine.jsx` (create) | Device-side "behind CARL · Port 5" line |
| `app/src/components/UplinkLine.test.jsx` (create) | Its tests |
| `app/src/pages/NetworkMonitor.jsx` (modify) | Render both in `DeviceDetail` |

---

### Task 1: SNMP suffix walk + switch port reader

**Files:**
- Modify: `backend/app/vendors/__init__.py` (add after `_snmp_walk_map`, line 174)
- Test: `backend/tests/test_switch_ports.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `_snmp_walk_suffix(ip: str, oid: str) -> dict` — keys are the **full** remaining OID suffix as a string.
  - `read_switch_ports(ip: str) -> dict` — `{'switchPorts': [...], 'switchPortsAsOf': str}` or `{}`. Each entry: `{'port': int, 'name': str, 'link': str, 'macs': [str], 'deviceCount': int}`. Tasks 2–4 depend on these exact key names.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_switch_ports.py`:

```python
"""Read-only per-port device map for Luminex GigaCore switches.

The fixtures are verbatim SNMP payloads captured from the GigaCore12 at
172.16.1.21 ("CARL") on 2026-08-06, not composed by hand. The forwarding
database is a LIVE, ageing table — CARL's uplink read 79 MACs in one probe
and 74 minutes later — so these are frozen captures and no test here may
assert that a real switch still reports a given number.
"""

from unittest.mock import patch

from app import vendors


# dot1dTpFdbPort, 1.3.6.1.2.1.17.4.3.1.2 — OID suffix is the six octets of
# the MAC in decimal; the value is the BRIDGE port number (not ifIndex).
GIGACORE_FDB = {
    '0.25.124.2.224.91': 5,        # 00:19:7C:02:E0:5B  Bolero antenna
    '0.25.124.2.225.86': 6,        # 00:19:7C:02:E1:56  Bolero antenna
    '0.25.124.21.228.151': 11,     # 00:19:7C:15:E4:97  not in the device table
    '0.224.76.48.126.254': 1,      # 00:E0:4C:30:7E:FE
    '4.17.25.144.1.192': 12,       # 04:11:19:90:01:C0  ACPD, via the uplink
    '40.54.56.192.57.192': 12,     # 28:36:38:C0:39:C0  Swisson, via the uplink
    # Bridge port 0 is the switch's OWN management MAC. It has no
    # dot1dBasePortIfIndex entry and is not a physical port.
    '208.105.158.4.120.114': 0,    # D0:69:9E:04:78:72  CARL itself
}

# dot1dBasePortIfIndex — bridge port -> ifIndex. Note there is no entry for 0.
GIGACORE_BP2IF = {str(i): i for i in range(1, 13)}

# ifDescr — BYTES, and the real device pads to a fixed width: b'Port  1'.
GIGACORE_IFDESCR = {str(i): f'Port {i:>2}'.encode() for i in range(1, 13)}

# ifOperStatus — 1 is up, 2 is down.
GIGACORE_IFOPER = {str(i): (1 if i in (1, 5, 6, 11, 12) else 2) for i in range(1, 13)}


def _fake_walks(fdb=None):
    """Dispatch a walk by OID, the way a real switch would."""
    tables = {
        '1.3.6.1.2.1.17.4.3.1.2': GIGACORE_FDB if fdb is None else fdb,
        '1.3.6.1.2.1.17.1.4.1.2': GIGACORE_BP2IF,
        '1.3.6.1.2.1.2.2.1.2': GIGACORE_IFDESCR,
        '1.3.6.1.2.1.2.2.1.8': GIGACORE_IFOPER,
    }
    def walk(ip, oid):
        return dict(tables[oid])
    return walk


def test_suffix_walk_keeps_the_whole_mac():
    """_snmp_walk_map keys on the LAST OID arc, which is right for interface
    tables indexed by one integer and destroys the FDB, whose index is the six
    octets of a MAC — it would return '91' where the answer is a device."""
    rows = [('1.3.6.1.2.1.17.4.3.1.2.0.25.124.2.224.91', 5)]

    class _Row:
        def __init__(self, oid, value):
            self.oid, self.value = oid, value

    with patch('app.vendors.puresnmp.walk', return_value=[_Row(*r) for r in rows]):
        out = vendors._snmp_walk_suffix('172.16.1.21', '1.3.6.1.2.1.17.4.3.1.2')

    assert out == {'0.25.124.2.224.91': 5}


def test_a_single_mac_port_names_one_device():
    with patch('app.vendors._snmp_walk_suffix', side_effect=lambda ip, oid: _fake_walks()(ip, oid)), \
         patch('app.vendors._snmp_walk_map', side_effect=lambda ip, oid: _fake_walks()(ip, oid)):
        ports = vendors.read_switch_ports('172.16.1.21')['switchPorts']

    p5 = next(p for p in ports if p['port'] == 5)
    assert p5['macs'] == ['00:19:7C:02:E0:5B']
    assert p5['deviceCount'] == 1
    assert p5['name'] == 'Port 5'          # collapsed from b'Port  5'
    assert p5['link'] == 'up'


def test_an_uplink_port_keeps_every_mac_and_its_count():
    """The count is what lets the UI refuse to call this a patch point."""
    with patch('app.vendors._snmp_walk_suffix', side_effect=lambda ip, oid: _fake_walks()(ip, oid)), \
         patch('app.vendors._snmp_walk_map', side_effect=lambda ip, oid: _fake_walks()(ip, oid)):
        ports = vendors.read_switch_ports('172.16.1.21')['switchPorts']

    p12 = next(p for p in ports if p['port'] == 12)
    assert p12['deviceCount'] == 2
    assert sorted(p12['macs']) == ['04:11:19:90:01:C0', '28:36:38:C0:39:C0']


def test_the_switchs_own_mac_is_not_given_a_port():
    """Bridge port 0 has no dot1dBasePortIfIndex entry — it is the switch's
    management MAC, not a physical port. Rendering it as a mystery port would
    invent hardware that does not exist."""
    with patch('app.vendors._snmp_walk_suffix', side_effect=lambda ip, oid: _fake_walks()(ip, oid)), \
         patch('app.vendors._snmp_walk_map', side_effect=lambda ip, oid: _fake_walks()(ip, oid)):
        ports = vendors.read_switch_ports('172.16.1.21')['switchPorts']

    every_mac = [m for p in ports for m in p['macs']]
    assert 'D0:69:9E:04:78:72' not in every_mac
    assert all(p['port'] != 0 for p in ports)


def test_every_physical_port_appears_even_with_nothing_on_it():
    """An empty port is a fact worth showing — it is how you find a free one."""
    with patch('app.vendors._snmp_walk_suffix', side_effect=lambda ip, oid: _fake_walks()(ip, oid)), \
         patch('app.vendors._snmp_walk_map', side_effect=lambda ip, oid: _fake_walks()(ip, oid)):
        ports = vendors.read_switch_ports('172.16.1.21')['switchPorts']

    assert [p['port'] for p in ports] == list(range(1, 13))
    p2 = next(p for p in ports if p['port'] == 2)
    assert p2['macs'] == [] and p2['deviceCount'] == 0 and p2['link'] == 'down'


def test_the_read_is_stamped_with_its_own_time():
    with patch('app.vendors._snmp_walk_suffix', side_effect=lambda ip, oid: _fake_walks()(ip, oid)), \
         patch('app.vendors._snmp_walk_map', side_effect=lambda ip, oid: _fake_walks()(ip, oid)):
        data = vendors.read_switch_ports('172.16.1.21')

    assert data['switchPortsAsOf'].endswith('Z')


def test_an_unreachable_switch_yields_empty_not_an_exception():
    """172.16.1.12 answers neither SNMP nor HTTP. This runs inside the sweep;
    one dead switch must not take it down, and the scanner's merge keeps the
    last good map only if we return {} rather than a partial one."""
    with patch('app.vendors._snmp_walk_suffix', side_effect=OSError('timeout')):
        assert vendors.read_switch_ports('172.16.1.12') == {}


def test_a_switch_with_no_bridge_table_yields_empty():
    with patch('app.vendors._snmp_walk_suffix', return_value={}), \
         patch('app.vendors._snmp_walk_map', return_value={}):
        assert vendors.read_switch_ports('172.16.1.21') == {}


def test_the_vendors_module_issues_no_snmp_writes():
    """BINDING: the rig is live. This module may GET and WALK, never SET.

    Asserted against the module's own source so that ADDING a write fails the
    suite, rather than relying on nobody having called one during a test run.
    """
    import inspect
    src = inspect.getsource(vendors)
    for forbidden in ('puresnmp.set', 'puresnmp.multiset', '.bulkset('):
        assert forbidden not in src, f'SNMP write {forbidden!r} in vendors'
```

- [ ] **Step 2: Run the tests to verify they fail**

From `C:\dev\Five12-TheApp\backend`:

```bash
python -m pytest tests/test_switch_ports.py -v
```

Expected: FAIL with `AttributeError: module 'app.vendors' has no attribute '_snmp_walk_suffix'`. The read-only pin test should PASS already — it must still pass at the end.

- [ ] **Step 3: Write the implementation**

In `backend/app/vendors/__init__.py`, immediately after `_snmp_walk_map` (line 174):

```python
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
        o = str(getattr(row, 'oid', row[0]))
        val = getattr(row, 'value', row[1])
        out[o[len(prefix):] if o.startswith(prefix) else o] = val
    return out


def _mac_from_oid_suffix(suffix: str) -> str | None:
    """'0.25.124.2.224.91' -> '00:19:7C:02:E0:5B'. None if it isn't six octets."""
    parts = suffix.split('.')
    if len(parts) != 6:
        return None
    try:
        return ':'.join(f'{int(p):02X}' for p in parts)
    except ValueError:
        return None


def read_switch_ports(ip: str) -> dict:
    """Which MACs are behind each physical port of a managed switch.

    Four standard read-only walks — BRIDGE-MIB forwarding database, the
    bridge-port to ifIndex map, and MIB-II's ifDescr and ifOperStatus.
    [VERIFIED 2026-08-06] against five GigaCore12s, ~2s each.

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

    by_port = {int(bp): [] for bp in bp2if}
    for suffix, bridge_port in fdb.items():
        # Bridge ports absent from dot1dBasePortIfIndex are not physical
        # ports — port 0 is the switch's own management MAC. Assigning it a
        # port number would invent hardware.
        if str(bridge_port) not in bp2if:
            continue
        mac = _mac_from_oid_suffix(suffix)
        if mac:
            by_port[int(bridge_port)].append(mac)

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
```

`_utc_iso` and `datetime` are already imported in this module (added for `read_port_status`). Confirm before adding duplicates.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/test_switch_ports.py -v
```

Expected: 9 PASS.

- [ ] **Step 5: Confirm the shared helper did not change behaviour**

```bash
python -m pytest tests/test_vendors.py tests/ -q
```

Expected: no new failures. `_snmp_walk_map` must be untouched — the Netgear and Luminex enrichers depend on it.

- [ ] **Step 6: Commit**

```bash
git add backend/app/vendors/__init__.py backend/tests/test_switch_ports.py
git commit -m "feat(network): read per-port device map from a managed switch"
```

---

### Task 2: The reverse index

**Files:**
- Modify: `backend/app/vendors/__init__.py` (add after `read_switch_ports`)
- Test: `backend/tests/test_switch_lookup.py` (create)

**Interfaces:**
- Consumes: the `switchPorts` shape from Task 1.
- Produces: `find_switch_port(mac: str, switches: list) -> dict | None`. `switches` is a list of `{'mac': str, 'label': str, 'switchPorts': [...]}`. Returns `{'switchMac', 'switchLabel', 'port', 'portName', 'deviceCount'}` or `None`. Pure — no I/O, no database.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_switch_lookup.py`:

```python
"""Where is this device? — inverted from the switches' stored port maps.

The numbers below are the real measured situation on 2026-08-06. A device
appears in the forwarding database of EVERY switch on its path, so picking the
right one matters, and admitting when the best answer is still not an
attachment point matters more.
"""

from app import vendors


# Bolero Antenna #1 really is in CARL port 5 — one MAC behind that port.
# It ALSO appears behind two uplinks, with 73 and 74 other devices.
ANTENNA_1 = '00:19:7C:02:E0:5B'
# Bolero Antenna #3's best candidate is an uplink with 73 devices behind it.
# It is plugged into something else — most likely the switch that is offline.
ANTENNA_3 = '00:19:7C:15:E4:97'

SWITCHES = [
    {'mac': 'D0:69:9E:04:78:72', 'label': 'Luminex (CARL)', 'switchPorts': [
        {'port': 5, 'name': 'Port 5', 'link': 'up',
         'macs': [ANTENNA_1], 'deviceCount': 1},
        {'port': 12, 'name': 'Port 12', 'link': 'up',
         'macs': [ANTENNA_3] + [f'AA:BB:CC:00:00:{i:02X}' for i in range(73)],
         'deviceCount': 74},
    ]},
    {'mac': 'D0:69:9E:04:77:C8', 'label': 'Luminex', 'switchPorts': [
        {'port': 12, 'name': 'Port 12', 'link': 'up',
         'macs': [ANTENNA_1, ANTENNA_3] + [f'AA:BB:CC:00:00:{i:02X}' for i in range(71)],
         'deviceCount': 73},
    ]},
]


def test_a_directly_attached_device_resolves_to_its_real_port():
    hit = vendors.find_switch_port(ANTENNA_1, SWITCHES)
    assert hit['switchLabel'] == 'Luminex (CARL)'
    assert hit['port'] == 5
    assert hit['deviceCount'] == 1          # what proves it is direct


def test_a_device_seen_only_through_uplinks_reports_the_count_not_a_patch_point():
    """Antenna #3 is NOT in port 12 — 73 other devices share that port, so it
    is a path. The count is returned so the caller can say "behind", never
    "on". Losing it here is what would make the UI lie."""
    hit = vendors.find_switch_port(ANTENNA_3, SWITCHES)
    assert hit['deviceCount'] == 73
    assert hit['port'] == 12
    assert hit['switchMac'] == 'D0:69:9E:04:77:C8'   # the 73, not the 74


def test_a_device_no_switch_has_seen_returns_none():
    assert vendors.find_switch_port('00:00:00:00:00:01', SWITCHES) is None


def test_the_lookup_is_case_insensitive():
    """MACs reach us from SNMP uppercase and from the device table in mixed
    case; a case mismatch would silently report every device as unseen."""
    assert vendors.find_switch_port(ANTENNA_1.lower(), SWITCHES)['port'] == 5


def test_a_switch_with_no_stored_map_is_skipped_not_crashed():
    switches = [{'mac': 'D0:69:9E:04:75:B9', 'label': 'Luminex'}] + SWITCHES
    assert vendors.find_switch_port(ANTENNA_1, switches)['port'] == 5
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python -m pytest tests/test_switch_lookup.py -v
```

Expected: FAIL, `module 'app.vendors' has no attribute 'find_switch_port'`.

- [ ] **Step 3: Write the implementation**

Append to `backend/app/vendors/__init__.py`:

```python
def find_switch_port(mac: str, switches: list) -> dict | None:
    """The closest switch port that has seen `mac`, with the count that says
    how much that means.

    A forwarding database records where a MAC was last seen, so a device shows
    up behind every switch on its path. The port with the FEWEST devices
    behind it is the closest — and only a count of exactly one proves direct
    attachment. [MEASURED 2026-08-06] Bolero Antenna #1 resolves to a
    one-device port and really is plugged there; Antenna #3's best candidate
    is an uplink with 73 others, and it is plugged into something else
    entirely. So the count is returned, always, and the caller words its
    answer from it.

    Pure: no I/O, no database, no SNMP. Give it the stored maps.
    """
    want = (mac or '').upper()
    best = None
    for sw in switches:
        for port in sw.get('switchPorts') or []:
            if want not in {m.upper() for m in port.get('macs') or []}:
                continue
            count = port.get('deviceCount', len(port.get('macs') or []))
            if best is None or count < best['deviceCount']:
                best = {
                    'switchMac': sw.get('mac'),
                    'switchLabel': sw.get('label'),
                    'port': port.get('port'),
                    'portName': port.get('name'),
                    'deviceCount': count,
                }
    return best
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/test_switch_lookup.py -v
```

Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/vendors/__init__.py backend/tests/test_switch_lookup.py
git commit -m "feat(network): resolve a device to its closest known switch port"
```

---

### Task 3: The two routes

**Files:**
- Modify: `backend/app/network_routes.py` (add after `device_ports`, around line 250)
- Test: `backend/tests/test_switch_routes.py` (create)

**Interfaces:**
- Consumes: `vendors.read_switch_ports(ip)`, `vendors.find_switch_port(mac, switches)`.
- Produces:
  - `GET /api/network/devices/<mac>/switch-ports` → `{'switchPorts': [...], 'live': bool, 'asOf': str|None}`
  - `GET /api/network/devices/<mac>/uplink` → `{'found': True, 'switchMac', 'switchLabel', 'port', 'portName', 'deviceCount'}` or `{'found': False}`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_switch_routes.py`:

```python
"""Switch port map and reverse lookup routes.

Both are strictly read-only toward the database: the scanner concurrently
updates these rows, and a live value disagreeing with the stored one is not
evidence the sweep was wrong.
"""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app.models import NetworkDevice


PORTS = [
    {'port': 5, 'name': 'Port 5', 'link': 'up',
     'macs': ['00:19:7C:02:E0:5B'], 'deviceCount': 1},
    {'port': 12, 'name': 'Port 12', 'link': 'up',
     'macs': ['00:19:7C:15:E4:97', '04:11:19:90:01:C0'], 'deviceCount': 2},
]


@pytest.fixture
def switch(db):
    row = NetworkDevice(
        mac_address='D0:69:9E:04:78:72',
        device_type='luminex',
        label='Luminex (CARL)',
        last_ip='172.16.1.21',
        last_seen=datetime.utcnow() - timedelta(seconds=30),
        vendor_data={'model': 'GigaCore12 GigaBit Ethernet Switch',
                     'switchPorts': PORTS,
                     'switchPortsAsOf': '2026-08-06T13:15:16.000000Z'},
    )
    db.session.add(row)
    db.session.commit()
    yield row
    db.session.delete(row)
    db.session.commit()


def test_a_reachable_switch_is_read_live(client, switch):
    fresh = [dict(PORTS[0], macs=['AA:BB:CC:00:00:01'])]
    with patch('app.vendors.read_switch_ports', return_value={'switchPorts': fresh}):
        res = client.get(f'/api/network/devices/{switch.mac_address}/switch-ports')

    body = res.get_json()
    assert body['live'] is True
    assert body['switchPorts'][0]['macs'] == ['AA:BB:CC:00:00:01']
    assert body['asOf'].endswith('Z')


def test_an_unreachable_switch_falls_back_to_the_stored_map(client, switch):
    with patch('app.vendors.read_switch_ports', return_value={}):
        res = client.get(f'/api/network/devices/{switch.mac_address}/switch-ports')

    body = res.get_json()
    assert body['live'] is False
    assert body['switchPorts'][0]['port'] == 5
    # The map's OWN timestamp, never last_seen: last_seen is the ICMP clock,
    # refreshed every 20s by a keep-alive that does not walk SNMP.
    assert body['asOf'] == '2026-08-06T13:15:16.000000Z'


def test_a_live_read_never_commits(client, db, switch):
    fresh = [dict(PORTS[0], macs=['AA:BB:CC:00:00:01'])]
    with patch('app.vendors.read_switch_ports', return_value={'switchPorts': fresh}), \
         patch.object(db.session, 'commit') as commit:
        client.get(f'/api/network/devices/{switch.mac_address}/switch-ports')
    commit.assert_not_called()


def test_a_switch_with_no_ip_is_not_probed(client, db):
    row = NetworkDevice(mac_address='D0:69:9E:00:00:01', device_type='luminex',
                        vendor_data={'switchPorts': PORTS})
    db.session.add(row); db.session.commit()
    try:
        with patch('app.vendors.read_switch_ports') as reader:
            res = client.get('/api/network/devices/D0:69:9E:00:00:01/switch-ports')
        reader.assert_not_called()
        assert res.get_json()['live'] is False
    finally:
        db.session.delete(row); db.session.commit()


def test_uplink_finds_a_directly_attached_device(client, db, switch):
    dev = NetworkDevice(mac_address='00:19:7C:02:E0:5B', device_type='bolero',
                        label='Bollero Antenna #1', last_ip='192.168.1.11')
    db.session.add(dev); db.session.commit()
    try:
        res = client.get('/api/network/devices/00:19:7C:02:E0:5B/uplink')
        body = res.get_json()
        assert body['found'] is True
        assert body['port'] == 5
        assert body['deviceCount'] == 1
        assert body['switchLabel'] == 'Luminex (CARL)'
    finally:
        db.session.delete(dev); db.session.commit()


def test_uplink_reports_the_count_for_a_device_seen_only_via_an_uplink(client, db, switch):
    """deviceCount 2 means the UI must say "behind", not "on"."""
    dev = NetworkDevice(mac_address='00:19:7C:15:E4:97', device_type='unknown')
    db.session.add(dev); db.session.commit()
    try:
        body = client.get('/api/network/devices/00:19:7C:15:E4:97/uplink').get_json()
        assert body['found'] is True
        assert body['deviceCount'] == 2
    finally:
        db.session.delete(dev); db.session.commit()


def test_uplink_reports_not_found_for_an_unseen_device(client, db, switch):
    dev = NetworkDevice(mac_address='11:22:33:44:55:66', device_type='unknown')
    db.session.add(dev); db.session.commit()
    try:
        assert client.get('/api/network/devices/11:22:33:44:55:66/uplink').get_json() == {'found': False}
    finally:
        db.session.delete(dev); db.session.commit()


def test_uplink_issues_no_snmp(client, db, switch):
    """It is pure computation over rows already in the database. Walking six
    switches on every device selection would put constant SNMP load on live
    show hardware."""
    dev = NetworkDevice(mac_address='00:19:7C:02:E0:5B', device_type='bolero')
    db.session.add(dev); db.session.commit()
    try:
        with patch('app.vendors.read_switch_ports') as reader:
            client.get('/api/network/devices/00:19:7C:02:E0:5B/uplink')
        reader.assert_not_called()
    finally:
        db.session.delete(dev); db.session.commit()


def test_both_routes_404_an_unknown_mac(client):
    assert client.get('/api/network/devices/FF:FF:FF:FF:FF:FF/switch-ports').status_code == 404
    assert client.get('/api/network/devices/FF:FF:FF:FF:FF:FF/uplink').status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python -m pytest tests/test_switch_routes.py -v
```

Expected: FAIL. Note `test_both_routes_404_an_unknown_mac` may **pass incidentally** at this point: the routes do not exist yet, so the request falls through to the SPA catch-all in `routes.py`, which also answers 404. That is not evidence of anything — it must still pass at the end, when it is a real 404 from the handler.

- [ ] **Step 3: Write the implementation**

Add to `backend/app/network_routes.py` after `device_ports`:

```python
@net.get('/devices/<mac>/switch-ports')
def device_switch_ports(mac):
    """Which MACs are behind each port of a managed switch, live then cached.

    Read-only in both directions: SNMP GET/WALK only toward the switch (the
    rig is live), and no database write here — the scanner updates this row
    concurrently.
    """
    from . import vendors

    device = db.session.get(NetworkDevice, mac)
    if device is None:
        return jsonify({'error': 'not found'}), 404

    if device.last_ip:
        live = vendors.read_switch_ports(device.last_ip)
        if live.get('switchPorts'):
            return jsonify({
                'switchPorts': live['switchPorts'],
                'live': True,
                'asOf': _utc_iso(datetime.utcnow()),
            })

    # The map's own timestamp, never last_seen — last_seen is the ICMP clock
    # that quick_reprobe refreshes every 20s without walking SNMP.
    stored = device.vendor_data or {}
    return jsonify({
        'switchPorts': stored.get('switchPorts') or [],
        'live': False,
        'asOf': stored.get('switchPortsAsOf'),
    })


@net.get('/devices/<mac>/uplink')
def device_uplink(mac):
    """Which switch port this device sits behind.

    Pure computation over stored maps — issues no SNMP at all. Answering this
    live would mean walking every switch on every device selection.

    `deviceCount` is part of the answer, not decoration: only a count of one
    proves direct attachment, and the caller must word itself accordingly.
    """
    from . import vendors

    device = db.session.get(NetworkDevice, mac)
    if device is None:
        return jsonify({'error': 'not found'}), 404

    switches = [
        {'mac': s.mac_address, 'label': s.label,
         'switchPorts': (s.vendor_data or {}).get('switchPorts')}
        for s in NetworkDevice.query.filter(NetworkDevice.mac_address != mac).all()
        if (s.vendor_data or {}).get('switchPorts')
    ]
    hit = vendors.find_switch_port(mac, switches)
    if hit is None:
        return jsonify({'found': False})
    return jsonify({'found': True, **hit})
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/test_switch_routes.py -v
```

Expected: 9 PASS.

- [ ] **Step 5: Run the whole backend suite**

```bash
python -m pytest tests/ -q
```

Expected: no new failures.

- [ ] **Step 6: Commit**

```bash
git add backend/app/network_routes.py backend/tests/test_switch_routes.py
git commit -m "feat(network): add switch port map and uplink lookup routes"
```

---

### Task 4: Wire the reader into the sweep

**Files:**
- Modify: `backend/app/vendors/__init__.py` — `_enrich_luminex`
- Test: `backend/tests/test_switch_ports.py` (extend)

**Interfaces:**
- Consumes: `read_switch_ports(ip)` from Task 1.
- Produces: `vendor_data` on a `luminex` device now carries `switchPorts` and `switchPortsAsOf` alongside the existing `model` / `portCount` / `activePorts`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_switch_ports.py`:

```python
def test_luminex_enrichment_attaches_the_port_map():
    """This is what puts the table in the Network tab. It rides on the same
    sweep that already reads model and port count over SNMP."""
    with patch('app.vendors._enrich_snmp_switch',
               return_value={'model': 'GigaCore12 GigaBit Ethernet Switch',
                             'portCount': 12}), \
         patch('app.vendors.read_switch_ports',
               return_value={'switchPorts': [{'port': 5, 'name': 'Port 5',
                                              'link': 'up', 'macs': ['AA:BB:CC:00:00:01'],
                                              'deviceCount': 1}],
                             'switchPortsAsOf': '2026-08-06T13:15:16.000000Z'}):
        data = vendors.enrich_device('172.16.1.21', 'D0:69:9E:04:78:72', 'luminex')

    assert data['model'] == 'GigaCore12 GigaBit Ethernet Switch'
    assert data['switchPorts'][0]['port'] == 5
    assert data['switchPortsAsOf'] == '2026-08-06T13:15:16.000000Z'


def test_a_switch_that_answers_snmp_but_not_the_bridge_table_keeps_its_model():
    """The two reads are independent, exactly as /model/device and
    /model/status are for the DMX nodes — half a read must not cost the
    other half."""
    with patch('app.vendors._enrich_snmp_switch',
               return_value={'model': 'GigaCore12 GigaBit Ethernet Switch'}), \
         patch('app.vendors.read_switch_ports', return_value={}):
        data = vendors.enrich_device('172.16.1.21', 'D0:69:9E:04:78:72', 'luminex')

    assert data['model'] == 'GigaCore12 GigaBit Ethernet Switch'
    assert 'switchPorts' not in data
```

- [ ] **Step 2: Run to verify it fails**

```bash
python -m pytest tests/test_switch_ports.py -k luminex_enrichment -v
```

Expected: FAIL with `KeyError: 'switchPorts'`.

- [ ] **Step 3: Write the implementation**

Replace `_enrich_luminex` in `backend/app/vendors/__init__.py`:

```python
def _enrich_luminex(ip: str) -> dict:
    # GigaCore's web GUI is auth-locked (401) and exposes no public REST API,
    # but SNMP v2c is enabled by default. Firmware is not in any MIB GigaCore
    # answers, so it stays None.
    #
    # The per-port device map is read alongside, from the same SNMP session's
    # worth of walks. Merged independently: a switch that answers MIB-II but
    # not the bridge table still contributes its model, and vice versa.
    data = _enrich_snmp_switch(ip, 'Luminex')
    data.update(read_switch_ports(ip))
    return data
```

- [ ] **Step 4: Run to verify it passes**

```bash
python -m pytest tests/test_switch_ports.py -v
```

Expected: 11 PASS.

- [ ] **Step 5: Confirm the sweep still preserves a half-read**

```bash
python -m pytest tests/test_scanner_port_persistence.py -v
```

Expected: PASS. The scanner's general `{**prior, **fresh}` merge already carries `switchPorts` forward when a walk fails — this task adds no new preservation logic and must not need any.

- [ ] **Step 6: Commit**

```bash
git add backend/app/vendors/__init__.py backend/tests/test_switch_ports.py
git commit -m "feat(network): read the GigaCore port map on the discovery sweep"
```

---

### Task 5: SwitchPortTable component

**Files:**
- Create: `app/src/components/SwitchPortTable.jsx`, `app/src/components/SwitchPortTable.test.jsx`
- Modify: `app/src/pages/NetworkMonitor.jsx`

**Interfaces:**
- Consumes: `GET /api/network/devices/<mac>/switch-ports`.
- Produces: `<SwitchPortTable device={device} devices={devices} />`, default export. `devices` is the full device list, used to name MACs.

- [ ] **Step 1: Write the failing tests**

Create `app/src/components/SwitchPortTable.test.jsx`:

```jsx
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import axios from 'axios'
import SwitchPortTable from './SwitchPortTable'

vi.mock('axios')

const PORTS = [
  { port: 5, name: 'Port 5', link: 'up', macs: ['00:19:7C:02:E0:5B'], deviceCount: 1 },
  { port: 6, name: 'Port 6', link: 'up', macs: ['AA:BB:CC:00:00:99'], deviceCount: 1 },
  { port: 7, name: 'Port 7', link: 'down', macs: [], deviceCount: 0 },
  { port: 12, name: 'Port 12', link: 'up',
    macs: Array.from({ length: 79 }, (_, i) => `DD:EE:FF:00:00:${i.toString(16).padStart(2, '0').toUpperCase()}`),
    deviceCount: 79 },
]

const SWITCH = {
  macAddress: 'D0:69:9E:04:78:72',
  vendorData: { switchPorts: PORTS, switchPortsAsOf: '2026-08-06T13:15:16.000000Z' },
}

const DEVICES = [
  { macAddress: '00:19:7C:02:E0:5B', label: 'Bollero Antenna #1', lastIp: '192.168.1.11', deviceType: 'bolero' },
]

beforeEach(() => { vi.resetAllMocks() })

describe('SwitchPortTable', () => {
  it('names a device on a single-MAC port', () => {
    axios.get.mockReturnValue(new Promise(() => {}))
    render(<SwitchPortTable device={SWITCH} devices={DEVICES} />)
    expect(screen.getByText(/Bollero Antenna #1/)).toBeInTheDocument()
  })

  it('shows a raw MAC for a device it does not know, rather than inventing a name', () => {
    axios.get.mockReturnValue(new Promise(() => {}))
    render(<SwitchPortTable device={SWITCH} devices={DEVICES} />)
    expect(screen.getByText(/AA:BB:CC:00:00:99/)).toBeInTheDocument()
  })

  it('does not claim a device is ON a port shared with 78 others', () => {
    axios.get.mockReturnValue(new Promise(() => {}))
    render(<SwitchPortTable device={SWITCH} devices={DEVICES} />)
    const row = screen.getByText('Port 12').closest('tr')
    expect(row.textContent).toMatch(/79 devices/)
  })

  it('shows an empty port as empty', () => {
    axios.get.mockReturnValue(new Promise(() => {}))
    render(<SwitchPortTable device={SWITCH} devices={DEVICES} />)
    const row = screen.getByText('Port 7').closest('tr')
    expect(row.textContent).toMatch(/down/)
  })

  it('labels the map stale when the switch did not answer', async () => {
    axios.get.mockResolvedValue({ data: { live: false, switchPorts: PORTS, asOf: new Date(Date.now() - 240_000).toISOString() } })
    render(<SwitchPortTable device={SWITCH} devices={DEVICES} />)
    expect(await screen.findByText(/switch did not answer/)).toBeInTheDocument()
  })

  it('says our refresh failed rather than blaming the switch, on a bad body', async () => {
    axios.get.mockResolvedValue({ data: '<!doctype html><html>Frontend not built</html>' })
    render(<SwitchPortTable device={SWITCH} devices={DEVICES} />)
    expect(await screen.findByText(/could not refresh/)).toBeInTheDocument()
    expect(screen.queryByText(/switch did not answer/)).not.toBeInTheDocument()
  })

  it('keeps the cached map and says so when the request errors', async () => {
    axios.get.mockRejectedValue(new Error('network'))
    render(<SwitchPortTable device={SWITCH} devices={DEVICES} />)
    expect(await screen.findByText(/could not refresh/)).toBeInTheDocument()
    expect(screen.getByText('Port 5')).toBeInTheDocument()
  })

  it('renders nothing and fires no request for a device with no map', () => {
    const { container } = render(
      <SwitchPortTable device={{ macAddress: 'AA:BB:CC:00:00:01', vendorData: {} }} devices={DEVICES} />
    )
    expect(container).toBeEmptyDOMElement()
    expect(axios.get).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run to verify they fail**

From `C:\dev\Five12-TheApp\app`:

```bash
npx vitest run src/components/SwitchPortTable.test.jsx
```

Expected: FAIL — `Failed to resolve import "./SwitchPortTable"`.

- [ ] **Step 3: Write the component**

Create `app/src/components/SwitchPortTable.jsx`:

```jsx
import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { timeAgo } from '../utils/timeAgo';

const CELL = { padding: '3px 8px', fontSize: 12, textAlign: 'left', verticalAlign: 'top' };
const HEAD = { ...CELL, color: 'var(--color-text-muted)', fontSize: 10, letterSpacing: 1 };

// How many names to print before collapsing to a count. CARL's busiest real
// port has 6 devices behind it and its uplink has 79, so the cap has to sit
// low enough to separate "a small switch downstream" from "the uplink".
const NAME_CAP = 4;

export default function SwitchPortTable({ device, devices }) {
  const cached = device.vendorData?.switchPorts;
  // Both states are tagged with the device they describe. DeviceDetail renders
  // without a `key`, so the component persists across selections and would
  // otherwise paint the previous switch's rows — or its stale banner — over
  // the newly selected one for the render before the effect commits.
  const [portsState, setPortsState] = useState({ mac: device.macAddress, ports: cached || [] });
  const [stale, setStale] = useState({ mac: device.macAddress, value: null });

  useEffect(() => {
    setPortsState({ mac: device.macAddress, ports: device.vendorData?.switchPorts || [] });
    setStale({ mac: device.macAddress, value: null });
    if (!device.vendorData?.switchPorts?.length) return;

    let cancelled = false;
    const failed = () => setStale({
      mac: device.macAddress,
      value: { asOf: device.vendorData?.switchPortsAsOf ?? null, refreshFailed: true },
    });

    axios.get(`/api/network/devices/${device.macAddress}/switch-ports`)
      .then(res => {
        if (cancelled) return;
        // A stale backend 404s this route into index.html, and axios RESOLVES
        // with that HTML string. Treating it as a switch failure would blame
        // hardware that is working for a fault that is entirely ours.
        const wellFormed = res.data && typeof res.data === 'object' && typeof res.data.live === 'boolean';
        if (!wellFormed) return failed();
        if (res.data.switchPorts?.length) {
          setPortsState({ mac: device.macAddress, ports: res.data.switchPorts });
        }
        setStale({ mac: device.macAddress, value: res.data.live ? null : { asOf: res.data.asOf ?? null } });
      })
      .catch(() => { if (!cancelled) failed(); });
    return () => { cancelled = true; };
  }, [device.macAddress]);

  if (!cached?.length) return null;

  const ports = portsState.mac === device.macAddress ? portsState.ports : cached;
  const staleValue = stale.mac === device.macAddress ? stale.value : null;

  const byMac = {};
  for (const d of devices || []) byMac[d.macAddress.toUpperCase()] = d;

  // A MAC we cannot name renders as itself. Inventing a label would be worse
  // than a hex string an operator can look up.
  const nameFor = mac => {
    const d = byMac[mac.toUpperCase()];
    if (!d) return mac;
    return d.label ? `${d.label}${d.lastIp ? ` · ${d.lastIp}` : ''}` : mac;
  };

  return (
    <div style={{ background: 'var(--color-surface)', borderRadius: 4, padding: 8, marginBottom: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4 }}>
        <div style={{ color: 'var(--color-text-muted)', fontSize: 11, letterSpacing: 1 }}>SWITCH PORTS</div>
        {staleValue !== null && (
          <div style={{ color: 'var(--color-warn)', fontSize: 10 }}>
            {staleValue.refreshFailed ? 'could not refresh' : 'switch did not answer'}
            {' · '}
            {staleValue.asOf ? `as of ${timeAgo(staleValue.asOf)}` : 'time unknown'}
          </div>
        )}
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={HEAD}>PORT</th>
            <th style={HEAD}>LINK</th>
            <th style={HEAD}>WHAT'S ON IT</th>
          </tr>
        </thead>
        <tbody>
          {ports.map(p => (
            <tr key={p.port} style={{ borderTop: '1px solid var(--color-border)' }}>
              <td style={{ ...CELL, color: 'var(--color-text-muted)', fontVariantNumeric: 'tabular-nums' }}>{p.name}</td>
              <td style={{ ...CELL, color: p.link === 'up' ? 'var(--color-online)' : 'var(--color-text-muted)' }}>{p.link}</td>
              <td style={{ ...CELL, color: 'var(--color-text)' }}>
                {p.deviceCount === 0 && <span style={{ color: 'var(--color-text-muted)' }}>—</span>}
                {/* Exactly one MAC is the ONLY case that proves direct
                    attachment, so it is the only case that gets to read like
                    a plain statement of what is plugged in. */}
                {p.deviceCount === 1 && nameFor(p.macs[0])}
                {p.deviceCount > 1 && (
                  <>
                    <div style={{ color: 'var(--color-warn)', fontSize: 11 }}>
                      {p.deviceCount} devices behind this port
                    </div>
                    {p.macs.slice(0, NAME_CAP).map(m => (
                      <div key={m} style={{ color: 'var(--color-text-muted)', fontSize: 11 }}>{nameFor(m)}</div>
                    ))}
                    {p.deviceCount > NAME_CAP && (
                      <div style={{ color: 'var(--color-text-muted)', fontSize: 11 }}>
                        +{p.deviceCount - NAME_CAP} more
                      </div>
                    )}
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 4: Run to verify they pass**

```bash
npx vitest run src/components/SwitchPortTable.test.jsx
```

Expected: 8 PASS.

- [ ] **Step 5: Wire it into the Network tab**

In `app/src/pages/NetworkMonitor.jsx`, add to the imports:

```jsx
import SwitchPortTable from '../components/SwitchPortTable';
```

`DeviceDetail` does not currently receive the device list. Add it: change the `DeviceDetail` signature to `function DeviceDetail({ device, devices, locations, onUpdate })`, and at its call site (the `selectedDevice ? <DeviceDetail ... />` ternary) pass `devices={devices}`. Then render immediately after `<PortTable device={device} />`:

```jsx
      <SwitchPortTable device={device} devices={devices} />
```

Do not alter `<PortTable>`, the `universes` block, or anything else in the pane.

- [ ] **Step 6: Run the full frontend suite**

```bash
npm test
```

Expected: no new failures.

- [ ] **Step 7: Commit**

```bash
git add app/src/components/SwitchPortTable.jsx app/src/components/SwitchPortTable.test.jsx app/src/pages/NetworkMonitor.jsx
git commit -m "feat(network): show what is on each GigaCore port"
```

---

### Task 6: UplinkLine — the device-side answer

**Files:**
- Create: `app/src/components/UplinkLine.jsx`, `app/src/components/UplinkLine.test.jsx`
- Modify: `app/src/pages/NetworkMonitor.jsx`

**Interfaces:**
- Consumes: `GET /api/network/devices/<mac>/uplink`.
- Produces: `<UplinkLine device={device} />`, default export.

- [ ] **Step 1: Write the failing tests**

Create `app/src/components/UplinkLine.test.jsx`:

```jsx
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import axios from 'axios'
import UplinkLine from './UplinkLine'

vi.mock('axios')

const DEVICE = { macAddress: '00:19:7C:02:E0:5B', label: 'Bollero Antenna #1' }

beforeEach(() => { vi.resetAllMocks() })

describe('UplinkLine', () => {
  it('states the port plainly when one device is behind it', async () => {
    axios.get.mockResolvedValue({ data: { found: true, switchLabel: 'Luminex (CARL)',
      switchMac: 'D0:69:9E:04:78:72', port: 5, portName: 'Port 5', deviceCount: 1 } })
    render(<UplinkLine device={DEVICE} />)
    expect(await screen.findByText(/on Luminex \(CARL\) · Port 5/)).toBeInTheDocument()
  })

  it('says BEHIND, with the count, when the port is shared', async () => {
    axios.get.mockResolvedValue({ data: { found: true, switchLabel: 'Luminex',
      switchMac: 'D0:69:9E:04:77:C8', port: 12, portName: 'Port 12', deviceCount: 73 } })
    render(<UplinkLine device={DEVICE} />)
    expect(await screen.findByText(/behind Luminex · Port 12/)).toBeInTheDocument()
    expect(screen.getByText(/72 others/)).toBeInTheDocument()
  })

  it('never says "on" for a shared port', async () => {
    axios.get.mockResolvedValue({ data: { found: true, switchLabel: 'Luminex',
      switchMac: 'D0:69:9E:04:77:C8', port: 12, portName: 'Port 12', deviceCount: 73 } })
    render(<UplinkLine device={DEVICE} />)
    await screen.findByText(/behind/)
    expect(screen.queryByText(/^on /)).not.toBeInTheDocument()
  })

  it('says no switch has seen it rather than staying blank', async () => {
    axios.get.mockResolvedValue({ data: { found: false } })
    render(<UplinkLine device={DEVICE} />)
    expect(await screen.findByText(/no switch has seen this device/i)).toBeInTheDocument()
  })

  it('renders nothing while the request is in flight', () => {
    axios.get.mockReturnValue(new Promise(() => {}))
    const { container } = render(<UplinkLine device={DEVICE} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders nothing when the request fails', async () => {
    axios.get.mockRejectedValue(new Error('network'))
    const { container } = render(<UplinkLine device={DEVICE} />)
    await waitFor(() => expect(axios.get).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
  })
})
```

- [ ] **Step 2: Run to verify they fail**

```bash
npx vitest run src/components/UplinkLine.test.jsx
```

Expected: FAIL — `Failed to resolve import "./UplinkLine"`.

- [ ] **Step 3: Write the component**

Create `app/src/components/UplinkLine.jsx`:

```jsx
import React, { useState, useEffect } from 'react';
import axios from 'axios';

export default function UplinkLine({ device }) {
  // Tagged with the device it describes: this component persists across
  // selections, and showing the previous device's switch port under the new
  // device's name would be a confident, wrong answer.
  const [hit, setHit] = useState({ mac: device.macAddress, value: null });

  useEffect(() => {
    setHit({ mac: device.macAddress, value: null });
    let cancelled = false;
    axios.get(`/api/network/devices/${device.macAddress}/uplink`)
      .then(res => {
        if (cancelled) return;
        if (res.data && typeof res.data === 'object' && typeof res.data.found === 'boolean') {
          setHit({ mac: device.macAddress, value: res.data });
        }
      })
      // Silent: this is a supplementary line, and a failed lookup is not
      // evidence about where the device is. Saying nothing beats guessing.
      .catch(() => {});
    return () => { cancelled = true; };
  }, [device.macAddress]);

  const value = hit.mac === device.macAddress ? hit.value : null;
  if (!value) return null;

  if (!value.found) {
    return (
      <div style={{ color: 'var(--color-text-muted)', fontSize: 11, marginBottom: 8 }}>
        No switch has seen this device
      </div>
    );
  }

  // Exactly one device behind the port proves direct attachment. Anything
  // more is a path through an uplink — [MEASURED 2026-08-06] Bolero Antenna
  // #3's best candidate is a port with 73 devices behind it, and it is
  // plugged into something else entirely. Saying "on Port 12" would send an
  // operator to the wrong rack.
  const direct = value.deviceCount === 1;
  const where = `${value.switchLabel || value.switchMac} · ${value.portName}`;

  return (
    <div style={{ color: 'var(--color-gel)', fontSize: 11, marginBottom: 8 }}>
      {direct ? `on ${where}` : `behind ${where}`}
      {!direct && (
        <span style={{ color: 'var(--color-text-muted)' }}>
          {' '}· shared with {value.deviceCount - 1} others, so this is a path, not a patch point
        </span>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run to verify they pass**

```bash
npx vitest run src/components/UplinkLine.test.jsx
```

Expected: 6 PASS.

- [ ] **Step 5: Wire it in**

In `app/src/pages/NetworkMonitor.jsx`, add to the imports:

```jsx
import UplinkLine from '../components/UplinkLine';
```

Render it inside `DeviceDetail` immediately **above** the meta grid (the `<div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', ...`), so it reads as a location strapline under the device name:

```jsx
      <UplinkLine device={device} />
```

- [ ] **Step 6: Run the full frontend suite**

```bash
npm test
```

Expected: no new failures.

- [ ] **Step 7: Commit**

```bash
git add app/src/components/UplinkLine.jsx app/src/components/UplinkLine.test.jsx app/src/pages/NetworkMonitor.jsx
git commit -m "feat(network): show which switch port a device sits behind"
```

---

### Task 7: Verify on the actual rig

Tests prove the parsing. They cannot prove the app can reach a switch, and this is the task that caught a stale backend last time.

**Files:**
- Modify: `docs/superpowers/specs/2026-08-06-gigacore-port-device-map-design.md` (status line + a Verification section)

- [ ] **Step 1: Confirm SNMP still answers from this machine**

```bash
cd /c/dev/Five12-TheApp/backend && "C:/Users/antho/AppData/Local/Programs/Python/Python312/python.exe" -c "import sys; sys.path.insert(0,'.'); from app.vendors import read_switch_ports; d=read_switch_ports('172.16.1.21'); print(len(d.get('switchPorts',[])), 'ports'); [print(p['name'], p['link'], p['deviceCount']) for p in d.get('switchPorts',[])]"
```

Expected: 12 ports, a mix of link states, one port with a high `deviceCount` (the uplink). If this fails, stop — nothing below can work.

- [ ] **Step 2: Restart the backend so it runs this code**

The running backend will predate these commits. Ask Anthony before restarting — it is a live rig. The command `start.ps1` uses:

```
$env:FIVE12_BLE_TOOLS='1'; $env:FIVE12_BLE_WRITE='1'; cd backend;
& "C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe" -m flask run --port 5000 --no-reload
```

- [ ] **Step 3: Confirm both routes answer**

```bash
curl -s http://localhost:5000/api/network/devices/D0:69:9E:04:78:72/switch-ports
curl -s http://localhost:5000/api/network/devices/00:19:7C:02:E0:5B/uplink
```

Expected: the first `"live": true` with 12 ports; the second `"found": true` with a `deviceCount`. A `deviceCount` of 1 means direct attachment; anything higher must render as "behind".

- [ ] **Step 4: Trigger a sweep and confirm the maps persist**

```bash
curl -s -X POST http://localhost:5000/api/network/scan/trigger
```

Then confirm the five reachable Luminex rows carry `switchPorts`, and that `172.16.1.12` — which answers neither SNMP nor HTTP — does not, without having broken its row.

- [ ] **Step 5: Confirm on screen**

Open the Network tab. Select a GigaCore: the SWITCH PORTS table shows 12 rows, named devices on single-MAC ports, a count on the uplink. Select a Bolero antenna: the uplink line reads `on Luminex (CARL) · Port 5`. Select Bolero Antenna #3: it must read **behind**, with a count — not `on`.

- [ ] **Step 6: Confirm nothing else moved**

A Swisson node still shows its DMX `PORTS` table and no SWITCH PORTS table. A Stardust unit still shows `UNIVERSES OUTPUTTING`. The Devices tab is unchanged.

- [ ] **Step 7: Update the spec status and commit**

Set the status line to `implemented 2026-08-06`, add a Verification section recording what step 3 and step 5 actually showed, and commit.

---

## Notes for the implementer

- **The count is the feature.** Everything else is a table. If you find yourself dropping `deviceCount` to simplify a signature, you have removed the only thing that distinguishes a fact from a guess.
- **Never issue an SNMP SET.** The rig is live. Task 1's last test asserts the module's source contains no write call — if you need to change that test, you are doing something wrong.
- **The FDB is a live, ageing table.** Fixtures are frozen captures. A test asserting a real switch reports N devices will fail on a quiet Tuesday.
- **`ifName` returns nothing on this firmware.** Use `ifDescr`, and collapse its padding (`b'Port  1'` → `'Port 1'`).
- **Bridge port 0 is the switch itself**, not a port. It has no `dot1dBasePortIfIndex` entry, which is how you detect it.
