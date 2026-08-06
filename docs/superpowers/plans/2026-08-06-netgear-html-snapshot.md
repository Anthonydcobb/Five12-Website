# NETGEAR M4250 Settings From a Saved AV UI Page — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse a saved copy of an M4250's AV UI Overview page into the Network tab, so all seven switches show their profiles, per-port VLAN/PoE assignments and device details without SNMP being configured on them.

**Architecture:** A pure parser (`parse_snapshot(html) -> dict`) with no network, DB or Flask dependency, called by one POST route that matches the parsed serial+MAC to an existing `NetworkDevice` and merges into its `vendor_data`. The React side gains two read-only tables and a paste panel. Nothing writes to a switch.

**Tech Stack:** Python 3.12 / Flask / SQLAlchemy / BeautifulSoup 4 (`html.parser` backend, no lxml) · React 18 / Vitest / @testing-library/react · pytest 9.

**Spec:** `docs/superpowers/specs/2026-08-06-netgear-html-snapshot-design.md`

## Global Constraints

- **Interpreter.** The app runs on `C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe`. Tests MUST run on that same interpreter. `python` on PATH is 3.14 and has a different package set — a green suite there says nothing about the app runtime. Every `pytest` command below assumes the app interpreter is first on PATH.
- **No lxml.** It is not installed and needs a compiler on Windows. Use `BeautifulSoup(html, 'html.parser')` — stdlib backend, no build step.
- **Read-only.** No code in this plan may issue a write to a switch.
- **Storage key is `netgearPorts`. Never `ports`, never `switchPorts`.** Both of those are taken, by different features, with different shapes:
  - `ports` — `PortTable` renders whenever `vendorData.ports` is non-empty (`PortTable.jsx:103`) and `/api/network/devices/<mac>/ports` re-reads it live via `read_port_status`. Using it would render a DMX universe/protocol table for every switch and aim a DMX node endpoint at a switch's IP.
  - `switchPorts` — claimed by the in-flight GigaCore port-to-device map on branch `spec/gigacore-port-device-map`, which writes `{port, name, link, macs, deviceCount}` from BRIDGE-MIB. That reader is generic to any managed switch, so if it is ever wired into `_enrich_netgear` it would overwrite this feature's ports on every 300s sweep through the scanner's `{**prior, **fresh}` merge.

  This is the single most important naming rule in the plan. The two port datasets are complementary, not redundant — theirs answers "what is behind port 6", this one answers "what VLAN and profile is port 6 in" — and they are kept in separate keys so either can land without waiting on the other.
- **Never guess a value.** A field that cannot be located is absent. Follow the `'code N'` convention already in `vendors/__init__.py` — never blank, never guessed.
- **Timestamps** use `_utc_iso` from `app.models`, matching every other timestamp in this module.
- **Provenance keys:** `snapshotAsOf` (ISO string) and `source: 'html-snapshot'`.

## Prerequisite: capture the fixture

Task 2 onward cannot start without a real captured page. In the switch's AV UI at Configure → Overview, open the browser console and run:

```javascript
copy(document.documentElement.outerHTML)
```

Save the clipboard to `backend/tests/fixtures/netgear_m4250_overview.html`. A `view-source` of the SPA shell contains none of the data — it must be the rendered DOM.

> **Expected values come from the fixture file, never from anything else.** The
> first draft of this plan took them from a copy of the page pasted into chat
> ~40 minutes before the file was saved. Identity fields matched, but uptime,
> temperature and CPU had all moved on, and Task 2 blocked on the mismatch.
> If you need a value, read it out of `netgear_m4250_overview.html`.

**The fixture is already captured and in place** (Ctrl+S "Webpage, Complete" from the AV UI). It is FMB Switch **73**, an `M4250-10G2F-PoE+`, serial `70VG5C57A01E0`, base MAC `28:94:01:84:3C:DE`, management IP `172.16.3.73`, firmware `13.0.5.26`. Every assertion below uses those values verbatim — do not loosen an assertion to make it pass.

Three sibling pages were captured alongside it and are also on disk. They are NOT parsed by this plan, but they are the raw material for the follow-on described in Future work, so leave them in place:

- `netgear_m4250_portconfig.html` — per-port Profile Name and Template in a real table row
- `netgear_m4250_neighbor.html` — port → host → MAC → VLAN → IP in a real table
- `netgear_m4250_profiles.html` — the Network Profiles page

## File Structure

| File | Responsibility |
|---|---|
| `backend/requirements.txt` (modify) | Declare `beautifulsoup4` |
| `backend/app/vendors/netgear_snapshot.py` (create) | Pure parser. The only file that knows NETGEAR's DOM. |
| `backend/app/network_routes.py` (modify) | One POST route: identity matching, refusal rules, merge |
| `backend/tests/fixtures/netgear_m4250_overview.html` (create) | Captured page |
| `backend/tests/test_netgear_snapshot.py` (create) | Parser unit tests |
| `backend/tests/test_netgear_snapshot_routes.py` (create) | Route + matching tests |
| `backend/tests/test_scanner_snapshot_precedence.py` (create) | Regression: SNMP must not clobber |
| `app/src/components/NetgearPortTable.jsx` (create) | Per-port switch table |
| `app/src/components/NetgearProfilesTable.jsx` (create) | Profiles table |
| `app/src/components/SnapshotImportPanel.jsx` (create) | Paste box + confirm |
| `app/src/pages/NetworkMonitor.jsx` (modify) | Wire the three components into `DeviceDetail` |
| `app/src/components/*.test.jsx` (create) | Component tests |

---

### Task 1: Put BeautifulSoup on the app interpreter

The parser needs an HTML library. `bs4` is currently installed on the PATH interpreter (3.14) but **not** on the app's 3.12. Installing it in the wrong place is precisely the failure `requirements-dev.txt` documents at length, so this is its own task with its own verification.

**Files:**
- Modify: `backend/requirements.txt`

**Interfaces:**
- Produces: `bs4` importable on the app interpreter; `scripts/doctor.ps1` will check it on every dev launch because it checks `requirements.txt`.

- [ ] **Step 1: Confirm it is currently missing on the app interpreter**

```bash
'/c/Users/antho/AppData/Local/Programs/Python/Python312/python.exe' -c "import bs4"
```

Expected: `ModuleNotFoundError: No module named 'bs4'`. If it already imports, skip to Step 4.

- [ ] **Step 2: Declare the dependency**

In `backend/requirements.txt`, add after the `requests==2.34.2` line:

```
beautifulsoup4==4.14.3
```

- [ ] **Step 3: Install it into the app interpreter**

```bash
'/c/Users/antho/AppData/Local/Programs/Python/Python312/python.exe' -m pip install beautifulsoup4==4.14.3
```

- [ ] **Step 4: Verify on the app interpreter, with the stdlib backend**

```bash
'/c/Users/antho/AppData/Local/Programs/Python/Python312/python.exe' -c "from bs4 import BeautifulSoup; print(BeautifulSoup('<b id=x>hi</b>','html.parser').find(id='x').get_text())"
```

Expected: `hi`

- [ ] **Step 5: Confirm the existing suite still passes on the app interpreter**

```bash
cd backend && python -m pytest -q
```

Expected: all tests pass, same count as before this task.

- [ ] **Step 6: Commit**

```bash
git add backend/requirements.txt
git commit -m "deps: add beautifulsoup4 for NETGEAR snapshot parsing"
```

---

### Task 2: Parse device details

**Files:**
- Create: `backend/app/vendors/netgear_snapshot.py`
- Create: `backend/tests/test_netgear_snapshot.py`
- Requires: `backend/tests/fixtures/netgear_m4250_overview.html` (see Prerequisite)

**Interfaces:**
- Produces: `parse_snapshot(html: str) -> dict`. Later tasks add the `profiles` and `netgearPorts` keys to the same returned dict. Also produces the private helpers `_text(node)`, `_by_id(soup, element_id)` and `_int_in(text)` which Tasks 3–5 reuse.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_netgear_snapshot.py`:

```python
from pathlib import Path

import pytest

from app.vendors.netgear_snapshot import parse_snapshot

FIXTURE = Path(__file__).parent / 'fixtures' / 'netgear_m4250_overview.html'


@pytest.fixture(scope='module')
def snapshot():
    return parse_snapshot(FIXTURE.read_text(encoding='utf-8'))


def test_identity_fields(snapshot):
    assert snapshot['serial'] == '70VG5C57A01E0'
    assert snapshot['baseMac'] == '28:94:01:84:3C:DE'
    assert snapshot['model'] == 'M4250-10G2F-PoE+'
    assert snapshot['systemName'] == 'FMB Switch 73'


def test_version_fields(snapshot):
    assert snapshot['firmware'] == '13.0.5.26'
    assert snapshot['bootVersion'] == '1.0.0.11'
    assert snapshot['avUiVersion'] == '2.2.15.16'


def test_network_and_health_fields(snapshot):
    assert snapshot['managementIp'] == '172.16.3.73'
    assert snapshot['uptime'] == '0 days, 11 hrs, 58 mins, 10 secs'
    assert snapshot['stpMode'] == 'Neutral mode(32768): 32768'
    assert snapshot['fanMode'] == 'Quiet'
    assert snapshot['tempC'] == 32
    assert snapshot['maxTempC'] == 53
    assert snapshot['cpuPercent'] == 39.06
    assert snapshot['memoryPercent'] == 33.43


def test_absent_field_is_absent_not_blank():
    """A page missing an element yields no key at all, never an empty string."""
    html = '<div id="device_serial">ABC123</div><div id="device_mac">AA:BB:CC:DD:EE:FF</div>'
    parsed = parse_snapshot(html)
    assert parsed['serial'] == 'ABC123'
    assert 'firmware' not in parsed
    assert 'tempC' not in parsed


def test_non_netgear_page_yields_no_identity():
    parsed = parse_snapshot('<html><body><h1>Some other device</h1></body></html>')
    assert 'serial' not in parsed
    assert 'baseMac' not in parsed
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_netgear_snapshot.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.vendors.netgear_snapshot'`

- [ ] **Step 3: Write the implementation**

Create `backend/app/vendors/netgear_snapshot.py`:

```python
"""Parse a saved NETGEAR M4250 AV UI Overview page.

Pure: no network, no database, no Flask. Given the rendered HTML of the
Configure -> Overview page, returns a dict shaped for NetworkDevice.vendor_data.

Read-only by construction. The AV UI is a Vue SPA, so this must be fed the
RENDERED DOM (document.documentElement.outerHTML) -- a view-source of the shell
contains none of the data.

Design note: every field is independently optional. A NETGEAR firmware update
that renames one element must cost that one field, never the whole import, and
never a wrong value. A field that cannot be located is simply absent from the
returned dict.
"""
import re

from bs4 import BeautifulSoup

# lxml is not installed and needs a compiler on Windows. The stdlib backend is
# sufficient: this document is well-formed output from a Vue renderer.
_PARSER = 'html.parser'


def _text(node) -> str | None:
    """Visible text of `node`, or None when it has none.

    The AV UI nests icon <i> elements inside value divs (the edit pencils next
    to system name and management IP). Those are empty, so a plain get_text
    with whitespace stripped yields the value alone.
    """
    if node is None:
        return None
    txt = node.get_text(strip=True)
    return txt or None


def _by_id(soup, element_id: str) -> str | None:
    return _text(soup.find(id=element_id))


def _int_in(text: str | None) -> int | None:
    """First integer in `text`. Temperatures render as '25 ℃'."""
    if not text:
        return None
    m = re.search(r'-?\d+', text)
    return int(m.group()) if m else None


def _progress_value(soup, element_id: str) -> float | None:
    """A circular progress widget's value.

    Read from aria-valuenow rather than the rendered text: the attribute is the
    unformatted number, while the text carries a '%' that would need stripping.
    """
    node = soup.find(id=element_id)
    if node is None:
        return None
    try:
        return float(node.get('aria-valuenow'))
    except (TypeError, ValueError):
        return None


def _fan_mode(soup) -> str | None:
    """Label of the selected fan-mode radio ('Off' / 'Quiet' / 'Cool').

    The value lives on the checked <input> as an opaque code (1/2/3); the label
    beside it is the operator-facing word. Take the label so no code table has
    to be invented and kept in sync.
    """
    group = soup.find(id='fan_mode')
    if group is None:
        return None
    checked = group.select_one('.el-radio.is-checked .el-radio__label')
    return _text(checked)


# id -> output key, for the fields that are a plain text read.
_SIMPLE_FIELDS = {
    'device_serial': 'serial',
    'device_mac': 'baseMac',
    'device_model': 'model',
    'device_firmware': 'firmware',
    'device_bootver': 'bootVersion',
    'device_avuiversion': 'avUiVersion',
    'device_uptime': 'uptime',
    'device_manageip': 'managementIp',
    'device_serviceportip': 'oobIp',
    'device_stp': 'stpMode',
    'product_name': 'productName',
    'device_time': 'deviceTime',
}


def _parse_device(soup) -> dict:
    out = {}
    for element_id, key in _SIMPLE_FIELDS.items():
        val = _by_id(soup, element_id)
        if val is not None:
            out[key] = val

    # System name sits in its own span so the edit pencil stays out of it.
    name = soup.select_one('#device_name .item-name')
    if name is not None and _text(name):
        out['systemName'] = _text(name)

    temp = _int_in(_by_id(soup, 'fan_temp'))
    if temp is not None:
        out['tempC'] = temp
    max_temp = _int_in(_by_id(soup, 'max_temp'))
    if max_temp is not None:
        out['maxTempC'] = max_temp

    cpu = _progress_value(soup, 'cpu_monitor')
    if cpu is not None:
        out['cpuPercent'] = cpu
    mem = _progress_value(soup, 'memory_monitor')
    if mem is not None:
        out['memoryPercent'] = mem

    fan = _fan_mode(soup)
    if fan is not None:
        out['fanMode'] = fan
    return out


def parse_snapshot(html: str) -> dict:
    """Device details, profiles and per-port state from an Overview page.

    Returns {} for input that is not such a page. Never raises on malformed
    input -- it is fed operator-pasted text from hardware whose firmware can
    change under us, the same defensive posture read_port_status takes.
    """
    soup = BeautifulSoup(html or '', _PARSER)
    return _parse_device(soup)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && python -m pytest tests/test_netgear_snapshot.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/vendors/netgear_snapshot.py backend/tests/test_netgear_snapshot.py backend/tests/fixtures/netgear_m4250_overview.html
git commit -m "feat: parse device details from NETGEAR M4250 overview page"
```

---

### Task 3: Parse the profiles table

The AV UI emits `id="profile_name"` and `id="profile_color"` on **every** row — duplicate ids, invalid HTML that parsers tolerate. An id lookup returns only the first row and would silently import one profile out of five while looking like it worked. Walk rows positionally.

**Files:**
- Modify: `backend/app/vendors/netgear_snapshot.py`
- Modify: `backend/tests/test_netgear_snapshot.py`

**Interfaces:**
- Consumes: `_text`, `parse_snapshot` from Task 2.
- Produces: `parse_snapshot(...)['profiles']` — a list of dicts with keys `name` (str), `template` (str), `vlan` (int|None), `ip` (str|None), `portCount` (int|None), `color` (str|None, `'#rrggbb'`).

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_netgear_snapshot.py`:

```python
def test_profiles_all_rows_parsed(snapshot):
    """Five profiles, not one. Guards the duplicate-id trap: every row carries
    id="profile_name", so an id lookup would return only 'Default'."""
    names = [p['name'] for p in snapshot['profiles']]
    assert names == ['Default', 'FixtureNet', 'Comms', 'VidNet', 'HogNet']


def test_profile_fields(snapshot):
    by_name = {p['name']: p for p in snapshot['profiles']}

    assert by_name['FixtureNet']['template'] == 'Lighting'
    assert by_name['FixtureNet']['vlan'] == 300
    assert by_name['FixtureNet']['portCount'] == 8
    assert by_name['FixtureNet']['color'] == '#00ff00'

    assert by_name['Comms']['template'] == 'Audio AES67'
    assert by_name['Comms']['vlan'] == 400
    assert by_name['VidNet']['template'] == 'BirdDog AV Network'
    assert by_name['VidNet']['vlan'] == 500
    assert by_name['HogNet']['template'] == 'Data'
    assert by_name['HogNet']['vlan'] == 600
    assert by_name['HogNet']['color'] == '#ffa600'

    assert by_name['Default']['vlan'] == 1
    assert by_name['Default']['ip'] == '172.16.3.73'


def test_profiles_absent_when_table_missing():
    parsed = parse_snapshot('<div id="device_serial">X</div>')
    assert parsed.get('profiles', []) == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_netgear_snapshot.py -k profile -v
```

Expected: FAIL — `KeyError: 'profiles'`

- [ ] **Step 3: Write the implementation**

Add to `backend/app/vendors/netgear_snapshot.py`, above `parse_snapshot`:

```python
def _rgb_to_hex(style: str | None) -> str | None:
    """'background-color: rgb(0, 255, 0);' -> '#00ff00'.

    The profile swatch colour is worth carrying: it is how an operator
    recognises FixtureNet at a glance on the switch's own page, and reusing it
    avoids inventing a second palette for the same four networks.
    """
    if not style:
        return None
    m = re.search(r'rgba?\(\s*(\d+)\D+(\d+)\D+(\d+)', style)
    if not m:
        return None
    return '#%02x%02x%02x' % tuple(int(g) for g in m.groups())


def _parse_profiles(soup) -> list:
    """Rows of the Configured Profiles table.

    Parsed positionally, NOT by id. The AV UI puts id="profile_name" and
    id="profile_color" on every row, so soup.find(id=...) returns the first
    row only -- which imports 'Default' and silently drops the four profiles
    an operator actually cares about.

    Element Plus renders the header and the body as two separate <table>s;
    only the body carries data rows.
    """
    table = soup.select_one('#configured_profiles_table table.el-table__body')
    if table is None:
        return []
    out = []
    for row in table.select('tbody tr'):
        cells = row.find_all('td')
        if len(cells) < 5:
            continue
        name = _text(cells[0].select_one('span[id="profile_name"], span[id="profile_defaultName"]'))
        if name is None:
            # Fall back to the cell's own text minus the swatch, so a renamed
            # id costs the swatch colour rather than the whole row.
            name = _text(cells[0])
        if not name:
            continue
        swatch = cells[0].select_one('.color-block')
        out.append({
            'name': name,
            'template': _text(cells[1]),
            'vlan': _int_in(_text(cells[2])),
            'ip': (lambda v: None if v in (None, 'N/A') else v)(_text(cells[3])),
            'portCount': _int_in(_text(cells[4])),
            'color': _rgb_to_hex(swatch.get('style') if swatch else None),
        })
    return out
```

Then extend `parse_snapshot`'s body:

```python
    soup = BeautifulSoup(html or '', _PARSER)
    data = _parse_device(soup)
    data['profiles'] = _parse_profiles(soup)
    return data
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && python -m pytest tests/test_netgear_snapshot.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/vendors/netgear_snapshot.py backend/tests/test_netgear_snapshot.py
git commit -m "feat: parse configured profiles from NETGEAR overview page"
```

---

### Task 4: Parse the port strip

Everything here comes from the port elements themselves, which carry their own port number in the markup. Nothing in this task depends on document ordering, so nothing here is at risk from the popover problem Task 5 handles.

**Files:**
- Modify: `backend/app/vendors/netgear_snapshot.py`
- Modify: `backend/tests/test_netgear_snapshot.py`

**Interfaces:**
- Produces: `parse_snapshot(...)['netgearPorts']` — list of dicts with `port` (int), `media` (`'copper'`|`'fiber'`), `linkUp` (bool), `poe` (bool), `trunk` (`'manual'`|`'auto'`|None), `color` (str|None). Also `portCount` (int) and `activePorts` (int). Task 5 adds more keys to each port dict.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_netgear_snapshot.py`:

```python
def test_all_twelve_ports_in_order(snapshot):
    ports = snapshot['netgearPorts']
    assert [p['port'] for p in ports] == list(range(1, 13))
    assert snapshot['portCount'] == 12


def test_port_media_copper_and_fiber(snapshot):
    by_num = {p['port']: p for p in snapshot['netgearPorts']}
    assert by_num[1]['media'] == 'copper'
    assert by_num[11]['media'] == 'fiber'
    assert by_num[12]['media'] == 'fiber'


def test_port_link_state(snapshot):
    by_num = {p['port']: p for p in snapshot['netgearPorts']}
    assert by_num[1]['linkUp'] is True     # lan-disabled lan-connected
    assert by_num[4]['linkUp'] is True     # lan-connected
    assert by_num[3]['linkUp'] is False
    assert by_num[8]['linkUp'] is False
    assert snapshot['activePorts'] == 3


def test_powered_port_counts_as_up(snapshot):
    """Port 5 carries `lan-connected-powered`, not `lan-connected`.

    A substring test would pass by accident; an exact class-list membership
    test for 'lan-connected' reports this port DOWN. It is up at 100T Full
    and delivering 6W to a Raspberry Pi, so reporting it down would send an
    operator to a rack to fix a port that is working.
    """
    by_num = {p['port']: p for p in snapshot['netgearPorts']}
    assert by_num[5]['linkUp'] is True
    assert by_num[5]['poe'] is True


def test_port_poe_and_trunk_badges(snapshot):
    by_num = {p['port']: p for p in snapshot['netgearPorts']}
    assert by_num[3]['poe'] is True
    assert by_num[9]['poe'] is False
    assert by_num[1]['trunk'] == 'auto'
    assert by_num[2]['trunk'] == 'manual'
    assert by_num[10]['trunk'] == 'manual'
    assert by_num[4]['trunk'] is None


def test_port_colour_matches_profile_swatch(snapshot):
    by_num = {p['port']: p for p in snapshot['netgearPorts']}
    assert by_num[3]['color'] == '#ffa600'   # HogNet
    assert by_num[8]['color'] == '#00fff7'   # Comms
    assert by_num[4]['color'] == '#00ff00'   # FixtureNet


def test_ports_absent_when_strip_missing():
    parsed = parse_snapshot('<div id="device_serial">X</div>')
    assert parsed.get('netgearPorts', []) == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_netgear_snapshot.py -k port -v
```

Expected: FAIL — `KeyError: 'netgearPorts'`

- [ ] **Step 3: Write the implementation**

Add to `backend/app/vendors/netgear_snapshot.py`:

```python
def _parse_ports(soup) -> list:
    """Per-port state read from the port graphic.

    Each port element carries its own number in .lan-font, so this mapping is
    structural -- unlike the popovers in _merge_popovers, which are position-
    dependent and therefore guarded.

    Fibre ports nest .lan-font inside .fib-view; copper ports put it in
    .lan-three. Searching for the class rather than the container covers both.

    Link-up is marked by 'lan-connected' OR 'lan-connected-powered' -- the
    latter is a PoE port that is both linked and delivering power, and it is a
    DISTINCT class, not 'lan-connected' with a suffix. Testing membership of
    'lan-connected' alone reports a powered, working port as down; testing by
    substring instead would be right by accident and would also match any
    future 'lan-connected-*' class whose meaning we have not seen. Match the
    two known classes explicitly, so an unknown third one shows up as down and
    gets noticed rather than being silently absorbed.
    """
    LINK_UP_CLASSES = {'lan-connected', 'lan-connected-powered'}
    out = []
    for lan in soup.select('.sakura-port-lan'):
        number = _int_in(_text(lan.select_one('.lan-font')))
        if number is None:
            continue
        content = lan.select_one('.lan-content')
        classes = content.get('class', []) if content else []
        swatch = lan.select_one('.lan-three') or lan.select_one('.fib-view')
        trunk = None
        if lan.select_one('.port-manualTrunk'):
            trunk = 'manual'
        elif lan.select_one('.port-autoTrunk'):
            trunk = 'auto'
        out.append({
            'port': number,
            'media': 'fiber' if lan.select_one('.fib-view') else 'copper',
            'linkUp': bool(LINK_UP_CLASSES & set(classes)),
            'poe': lan.select_one('.port-poe') is not None,
            'trunk': trunk,
            'color': _rgb_to_hex(swatch.get('style') if swatch else None),
        })
    out.sort(key=lambda p: p['port'])
    return out
```

Extend `parse_snapshot`:

```python
    soup = BeautifulSoup(html or '', _PARSER)
    data = _parse_device(soup)
    data['profiles'] = _parse_profiles(soup)
    ports = _parse_ports(soup)
    data['netgearPorts'] = ports
    if ports:
        data['portCount'] = len(ports)
        data['activePorts'] = sum(1 for p in ports if p['linkUp'])
    return data
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && python -m pytest tests/test_netgear_snapshot.py -v
```

Expected: 14 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/vendors/netgear_snapshot.py backend/tests/test_netgear_snapshot.py
git commit -m "feat: parse per-port link, PoE, media and trunk state"
```

---

### Task 5: Merge popover data behind a count guard

Popovers are rendered into a detached `#el-popper-container-*` at the end of the body. The only thing tying one to a port is document order. On the reference capture that ordering is exact and cross-checks against every port's own colour and badge — but that is an observation about NETGEAR's renderer, not a contract.

Dropping a column is recoverable. Attributing port 7's connected fixture to port 6 is not.

**Files:**
- Modify: `backend/app/vendors/netgear_snapshot.py`
- Modify: `backend/tests/test_netgear_snapshot.py`

**Interfaces:**
- Produces: on each `netgearPorts` entry, the optional keys `vlans` (list[int]), `profile` (str|None), `template` (str|None), `host` (str|None), `mac` (str|None), `ip` (str|None), `linkSpeed` (str|None), `powerWatts` (str|None). Plus the top-level flag `netgearPortHostsAvailable` (bool), which the UI reads to explain a degraded import.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_netgear_snapshot.py`:

```python
def test_popover_alignment_holds(snapshot):
    """Cross-checks popover-sourced VLAN against each port's own colour, which
    is read structurally. If ordering ever drifts these disagree."""
    by_num = {p['port']: p for p in snapshot['netgearPorts']}
    assert snapshot['netgearPortHostsAvailable'] is True

    assert by_num[3]['profile'] == 'HogNet'
    assert by_num[3]['vlans'] == [600]
    assert by_num[8]['profile'] == 'Comms'
    assert by_num[8]['vlans'] == [400]
    assert by_num[4]['profile'] == 'FixtureNet'
    assert by_num[4]['template'] == 'Lighting'
    assert by_num[1]['vlans'] == [1, 300, 400, 500, 600]
    assert by_num[2]['vlans'] == [300, 400, 500, 600, 1]


def test_popover_connected_host_details(snapshot):
    by_num = {p['port']: p for p in snapshot['netgearPorts']}
    assert by_num[1]['host'] == 'FMB Switch 52'
    assert by_num[1]['mac'] == '28:94:01:84:47:02'
    assert by_num[1]['ip'] == '172.16.3.52'
    assert by_num[1]['linkSpeed'] == '1000 Full'
    assert by_num[4]['ip'] == '10.31.8.73'
    assert by_num[4]['mac'] == '28:36:38:C0:6D:51'
    assert by_num[4]['linkSpeed'] == '100T Full'
    assert by_num[5]['host'] == 'Raspberry Pi Trading Ltd'
    assert by_num[5]['ip'] == '10.0.5.5'
    assert by_num[5]['powerWatts'] == '6 Watts'


def test_unconnected_port_has_no_host_keys(snapshot):
    by_num = {p['port']: p for p in snapshot['netgearPorts']}
    assert by_num[3].get('host') is None
    assert by_num[3].get('ip') is None


def test_count_mismatch_drops_host_data_but_keeps_ports():
    """One popover removed -> alignment unprovable -> drop popover fields
    wholesale, keep everything read structurally."""
    html = FIXTURE.read_text(encoding='utf-8')
    marker = 'class="el-popper is-light el-tooltip el-popover sakura-port-popover"'
    cut = html.index(marker)
    end = html.index(marker, cut + 1)
    degraded = html[:cut - 60] + html[end - 60:]

    parsed = parse_snapshot(degraded)
    assert parsed['netgearPortHostsAvailable'] is False
    assert len(parsed['netgearPorts']) == 12
    assert parsed['netgearPorts'][2]['poe'] is True          # structural, kept
    assert parsed['netgearPorts'][2]['color'] == '#ffa600'   # structural, kept
    assert all('profile' not in p for p in parsed['netgearPorts'])
    assert all('ip' not in p for p in parsed['netgearPorts'])
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_netgear_snapshot.py -k popover -v
```

Expected: FAIL — `KeyError: 'netgearPortHostsAvailable'`

- [ ] **Step 3: Write the implementation**

Add to `backend/app/vendors/netgear_snapshot.py`:

```python
# Popover row label -> output key. Labels render as 'IP Address :'.
_POPOVER_FIELDS = {
    'Host': 'host',
    'MAC Address': 'mac',
    'IP Address': 'ip',
    'LLDP Remote ID': 'lldpRemoteId',
    'Port Type': 'portType',
    'Link Speed': 'linkSpeed',
    'Power Usage': 'powerWatts',
    'Profile Name': 'profile',
    'Profile Template': 'template',
}


def _parse_popover(node) -> dict:
    """One port popover, keyed by its own row labels rather than by position.

    Row order within a popover varies with how much the switch knows about the
    attached device, so labels are the only stable key here.
    """
    out = {}
    for item in node.select('.port-item'):
        label = _text(item.select_one('.item-label'))
        if not label:
            continue
        label = label.rstrip(':').strip()
        value_node = item.select_one('.flex-item')
        value = _text(value_node)
        if value is None:
            continue
        if label == 'VLAN ID':
            vlans = [int(v) for v in re.findall(r'\d+', value)]
            if vlans:
                out['vlans'] = vlans
        elif label in _POPOVER_FIELDS:
            out[_POPOVER_FIELDS[label]] = value
    return out


def _merge_popovers(soup, ports: list) -> bool:
    """Fold popover fields into `ports`, or refuse to and say so.

    Returns True when the merge happened, False when it was declined.

    The ONLY thing associating a popover with a port is document order --
    popovers live in a detached container at the end of the body, not inside
    the ports they describe. So the association is accepted only when the two
    counts match exactly. On any mismatch every popover-sourced field is
    dropped, and the caller surfaces that; the structurally-read fields from
    _parse_ports are unaffected because they never depended on ordering.

    Attributing one port's connected fixture to its neighbour is the failure
    this exists to prevent: it is silent, plausible, and gets acted on.

    Child popovers (.sakura-child-port-popover) are stack-member panels and
    carry no port data; they are interleaved with the real ones and excluded
    by the class selector.
    """
    popovers = soup.select('.sakura-port-popover')
    if not popovers or len(popovers) != len(ports):
        return False
    for port, node in zip(ports, popovers):
        port.update(_parse_popover(node))
    return True
```

Extend `parse_snapshot`'s tail:

```python
    ports = _parse_ports(soup)
    data['netgearPorts'] = ports
    if ports:
        data['portCount'] = len(ports)
        data['activePorts'] = sum(1 for p in ports if p['linkUp'])
        data['netgearPortHostsAvailable'] = _merge_popovers(soup, ports)
    return data
```

Note `_parse_ports` sorts by port number while popovers are in document order. On the reference capture these agree. If a future capture renders ports out of order the counts still match but the pairing would be wrong — so also assert order before merging by adding this guard at the top of `_merge_popovers`, after the count check:

```python
    if [p['port'] for p in ports] != sorted(p['port'] for p in ports):
        return False
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && python -m pytest tests/test_netgear_snapshot.py -v
```

Expected: 18 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/vendors/netgear_snapshot.py backend/tests/test_netgear_snapshot.py
git commit -m "feat: merge port popover data behind a strict alignment guard"
```

---

### Task 6: The import endpoint

**Files:**
- Modify: `backend/app/network_routes.py`
- Create: `backend/tests/test_netgear_snapshot_routes.py`

**Interfaces:**
- Consumes: `parse_snapshot` from Tasks 2–5.
- Produces: `POST /api/network/snapshot` accepting `{"html": "..."}`. On success `200 {"macAddress", "systemName", "profileCount", "portCount", "hostDataAvailable", "snapshotAsOf"}`. On refusal a 4xx with `{"error": "<machine code>", "detail": "<sentence>"}`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_netgear_snapshot_routes.py`:

```python
from pathlib import Path

import pytest

from app import db
from app.models import NetworkDevice

FIXTURE = Path(__file__).parent / 'fixtures' / 'netgear_m4250_overview.html'
MAC = '28:94:01:84:3C:DE'


@pytest.fixture
def html():
    return FIXTURE.read_text(encoding='utf-8')


@pytest.fixture
def switch(db):
    device = NetworkDevice(mac_address=MAC, device_type='netgear', last_ip='172.16.3.73')
    db.session.add(device)
    db.session.commit()
    yield device
    db.session.delete(db.session.get(NetworkDevice, MAC))
    db.session.commit()


def test_import_writes_snapshot(client, switch, html):
    res = client.post('/api/network/snapshot', json={'html': html})
    assert res.status_code == 200
    assert res.json['macAddress'] == MAC
    assert res.json['profileCount'] == 5
    assert res.json['portCount'] == 12
    assert res.json['hostDataAvailable'] is True

    stored = db.session.get(NetworkDevice, MAC).vendor_data
    assert stored['serial'] == '70VG5C57A01E0'
    assert stored['source'] == 'html-snapshot'
    assert stored['snapshotAsOf'].endswith('Z')
    assert len(stored['netgearPorts']) == 12
    # Both neighbouring keys are owned by other features with other shapes.
    assert 'ports' not in stored, 'must never occupy the DMX node patch key'
    assert 'switchPorts' not in stored, 'must never occupy the GigaCore SNMP map key'


def test_import_preserves_operator_fields(client, switch, html):
    switch.label = 'FMB Switch 60'
    switch.notes = 'rack 3'
    db.session.commit()
    client.post('/api/network/snapshot', json={'html': html})
    fresh = db.session.get(NetworkDevice, MAC)
    assert fresh.label == 'FMB Switch 60'
    assert fresh.notes == 'rack 3'


def test_unknown_mac_is_refused_and_creates_nothing(client, db, html):
    before = db.session.query(NetworkDevice).count()
    res = client.post('/api/network/snapshot', json={'html': html})
    assert res.status_code == 404
    assert res.json['error'] == 'unknown_device'
    assert db.session.query(NetworkDevice).count() == before


def test_serial_conflict_is_refused(client, switch, html):
    switch.vendor_data = {'serial': 'SOMEOTHERSERIAL'}
    db.session.commit()
    res = client.post('/api/network/snapshot', json={'html': html})
    assert res.status_code == 409
    assert res.json['error'] == 'serial_conflict'
    assert db.session.get(NetworkDevice, MAC).vendor_data['serial'] == 'SOMEOTHERSERIAL'


def test_non_netgear_html_is_refused(client, db):
    res = client.post('/api/network/snapshot', json={'html': '<html><body>hello</body></html>'})
    assert res.status_code == 422
    assert res.json['error'] == 'unrecognised_page'


def test_missing_html_is_refused(client, db):
    res = client.post('/api/network/snapshot', json={})
    assert res.status_code == 422
    assert res.json['error'] == 'unrecognised_page'
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_netgear_snapshot_routes.py -v
```

Expected: FAIL — 404s from Flask for an unregistered route.

- [ ] **Step 3: Write the implementation**

Append to `backend/app/network_routes.py`:

```python
@net.post('/snapshot')
def import_snapshot():
    """Import a saved NETGEAR AV UI Overview page.

    The switch's own page prints its serial and base MAC, so a snapshot
    identifies its own subject -- an operator pasting seven pages in a row
    never has to keep track of which is which, and cannot land switch 60's
    profiles on switch 76.

    Refuses rather than guesses. An unmatched MAC does NOT create a row: a
    switch the scanner has never seen is a discovery problem, not something to
    invent a record for out of a pasted document.

    Merges rather than replaces, so the operator's label and notes, and any
    live SNMP fields already present, survive. The next sweep merges SNMP over
    this (scanner._process_discovered_device), which is the intended
    precedence: SNMP is live, a snapshot is not.
    """
    from datetime import datetime

    from .models import _utc_iso
    from .vendors.netgear_snapshot import parse_snapshot

    payload = request.get_json(silent=True) or {}
    parsed = parse_snapshot(payload.get('html') or '')

    mac = (parsed.get('baseMac') or '').upper().replace('-', ':')
    if not mac or not parsed.get('serial'):
        return jsonify({
            'error': 'unrecognised_page',
            'detail': 'No NETGEAR serial and base MAC found. Paste the rendered '
                      'Configure -> Overview page (document.documentElement.outerHTML), '
                      'not a view-source of the page shell.',
        }), 422

    device = db.session.get(NetworkDevice, mac)
    if device is None:
        return jsonify({
            'error': 'unknown_device',
            'detail': f'No device known with MAC {mac}. Let the scanner discover '
                      f'the switch first, then import.',
        }), 404

    stored = device.vendor_data or {}
    known_serial = stored.get('serial')
    if known_serial and known_serial != parsed['serial']:
        return jsonify({
            'error': 'serial_conflict',
            'detail': f'{mac} is recorded with serial {known_serial}, but this page '
                      f'reports {parsed["serial"]}. Nothing was changed.',
        }), 409

    parsed['source'] = 'html-snapshot'
    parsed['snapshotAsOf'] = _utc_iso(datetime.utcnow())
    device.vendor_data = {**stored, **parsed}
    db.session.commit()

    return jsonify({
        'macAddress': mac,
        'systemName': parsed.get('systemName'),
        'profileCount': len(parsed.get('profiles', [])),
        'portCount': len(parsed.get('netgearPorts', [])),
        'hostDataAvailable': parsed.get('netgearPortHostsAvailable', False),
        'snapshotAsOf': parsed['snapshotAsOf'],
    })
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && python -m pytest tests/test_netgear_snapshot_routes.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/network_routes.py backend/tests/test_netgear_snapshot_routes.py
git commit -m "feat: POST /api/network/snapshot to import a switch overview page"
```

---

### Task 7: Pin the precedence rule with a regression test

`_process_discovered_device` already merges `{**prior, **fresh}` and skips the merge entirely on a falsy enrichment (`scanner.py:455-489`), so a snapshot survives both an empty and a partial SNMP read today. No production change is needed. What is missing is a test saying so — six of seven switches return `{}` from `enrich_device` on every 300s sweep, so a future refactor back to wholesale assignment would erase imported snapshots within seconds and no existing test would catch it.

**Files:**
- Create: `backend/tests/test_scanner_snapshot_precedence.py`

**Interfaces:**
- Consumes: `scanner._process_discovered_device`, `NetworkDevice`.
- Produces: nothing. Pure regression coverage.

- [ ] **Step 1: Write the test**

Create `backend/tests/test_scanner_snapshot_precedence.py`:

```python
"""A snapshot must survive the sweep that follows it.

enrich_device returns {} for every M4250 without SNMP v2c configured -- six of
the seven on this rig -- and that happens every 300s. If the scanner ever goes
back to assigning vendor_data wholesale, an imported snapshot is erased within
seconds of being saved and the Network tab silently empties.
"""
from unittest.mock import patch

import pytest

from app import db
from app.models import NetworkDevice
from app.scanner import _process_discovered_device

MAC = '28:94:01:84:3C:DE'
IP = '172.16.3.73'

SNAPSHOT = {
    'serial': '70VG5C57A01E0',
    'firmware': '13.0.5.26',
    'source': 'html-snapshot',
    'snapshotAsOf': '2026-08-06T12:00:00Z',
    'profiles': [{'name': 'FixtureNet', 'vlan': 300}],
    'netgearPorts': [{'port': 1, 'linkUp': True}],
}


@pytest.fixture
def switch(db):
    device = NetworkDevice(mac_address=MAC, device_type='netgear',
                           last_ip=IP, vendor_data=dict(SNAPSHOT))
    db.session.add(device)
    db.session.commit()
    yield device
    db.session.delete(db.session.get(NetworkDevice, MAC))
    db.session.commit()


def test_empty_snmp_read_leaves_snapshot_intact(app, switch):
    with patch('app.vendors.enrich_device', return_value={}):
        _process_discovered_device(IP, MAC, None, app)

    stored = db.session.get(NetworkDevice, MAC).vendor_data
    assert stored['profiles'] == SNAPSHOT['profiles']
    assert stored['netgearPorts'] == SNAPSHOT['netgearPorts']
    assert stored['snapshotAsOf'] == SNAPSHOT['snapshotAsOf']


def test_live_snmp_wins_for_its_own_fields_only(app, switch):
    live = {'firmware': '13.0.6.1', 'portCount': 12, 'activePorts': 3}
    with patch('app.vendors.enrich_device', return_value=live):
        _process_discovered_device(IP, MAC, None, app)

    stored = db.session.get(NetworkDevice, MAC).vendor_data
    assert stored['firmware'] == '13.0.6.1', 'SNMP is live; it wins'
    assert stored['portCount'] == 12
    assert stored['profiles'] == SNAPSHOT['profiles'], 'SNMP has no OID for these'
    assert stored['source'] == 'html-snapshot'
```

- [ ] **Step 2: Run the tests**

```bash
cd backend && python -m pytest tests/test_scanner_snapshot_precedence.py -v
```

Expected: 2 passed against unmodified `scanner.py`. **If either fails, stop** — the precedence the spec depends on is not actually in place, and the fix belongs here before any UI work.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_scanner_snapshot_precedence.py
git commit -m "test: pin that an SNMP sweep cannot erase an imported snapshot"
```

---

### Task 8: NetgearPortTable and NetgearProfilesTable components

**Files:**
- Create: `app/src/components/NetgearPortTable.jsx`
- Create: `app/src/components/NetgearPortTable.test.jsx`
- Create: `app/src/components/NetgearProfilesTable.jsx`

**Interfaces:**
- Consumes: `device.vendorData.netgearPorts`, `.profiles`, `.netgearPortHostsAvailable` from Task 6.
- Produces: default exports `NetgearPortTable({ device })` and `NetgearProfilesTable({ device })`. Both render `null` when their data is absent, matching `PortTable.jsx:103`.

- [ ] **Step 1: Write the failing test**

Create `app/src/components/NetgearPortTable.test.jsx`:

```jsx
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import NetgearPortTable from './NetgearPortTable'

const PORTS = [
  { port: 1, media: 'copper', linkUp: false, poe: false, trunk: 'manual',
    color: '#000000', vlans: [300, 400, 500, 600, 1] },
  { port: 3, media: 'copper', linkUp: false, poe: true, trunk: null,
    color: '#ffa600', vlans: [600], profile: 'HogNet', template: 'Data' },
  { port: 4, media: 'copper', linkUp: true, poe: true, trunk: null,
    color: '#00ff00', vlans: [300], profile: 'FixtureNet', template: 'Lighting',
    ip: '10.31.8.60', mac: '28:36:38:C0:73:63', linkSpeed: '100T Full' },
]

const device = (vendorData) => ({ macAddress: 'AA', vendorData })

describe('NetgearPortTable', () => {
  it('renders nothing when there are no switch ports', () => {
    const { container } = render(<NetgearPortTable device={device({})} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders a row per port with profile and VLAN', () => {
    render(<NetgearPortTable device={device({ netgearPorts: PORTS })} />)
    expect(screen.getByText('HogNet')).toBeTruthy()
    expect(screen.getByText('FixtureNet')).toBeTruthy()
    expect(screen.getByText('600')).toBeTruthy()
    expect(screen.getByText('10.31.8.60')).toBeTruthy()
    expect(screen.getByText('100T Full')).toBeTruthy()
  })

  it('shows a trunk as its VLAN list rather than a blank profile', () => {
    render(<NetgearPortTable device={device({ netgearPorts: PORTS })} />)
    expect(screen.getByText('300, 400, 500, 600, 1')).toBeTruthy()
    expect(screen.getByText('Trunk (manual)')).toBeTruthy()
  })

  it('explains missing host data instead of showing blank columns', () => {
    render(<NetgearPortTable device={device({
      netgearPorts: [{ port: 1, media: 'copper', linkUp: true, poe: false, trunk: null }],
      netgearPortHostsAvailable: false,
    })} />)
    expect(screen.getByText(/per-port host details were not readable/i)).toBeTruthy()
  })

  it('shows the snapshot age', () => {
    render(<NetgearPortTable device={device({
      netgearPorts: PORTS,
      netgearPortHostsAvailable: true,
      snapshotAsOf: new Date().toISOString(),
    })} />)
    // Anchored: the panel header is "SWITCH PORTS (SNAPSHOT)", so a bare
    // /snapshot/i matches two elements. Only the capture-age footer begins
    // with the word, and the footer is what this test is about.
    expect(screen.getByText(/^snapshot /i)).toBeTruthy()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd app && npm test -- NetgearPortTable
```

Expected: FAIL — cannot resolve `./NetgearPortTable`.

- [ ] **Step 3: Write the implementation**

Create `app/src/components/NetgearPortTable.jsx`:

```jsx
import React from 'react';
import { timeAgo } from '../utils/timeAgo';

const CELL = { padding: '3px 8px', fontSize: 12, textAlign: 'left' };
const HEAD = { ...CELL, color: 'var(--color-text-muted)', fontSize: 10, letterSpacing: 1 };

// A switch port and a DMX port share only the word "port": this has VLAN,
// profile and PoE where PortTable has universe, protocol and direction. They
// are deliberately separate components rather than one with half its columns
// blank for whichever kind it is rendering.
export default function NetgearPortTable({ device }) {
  const vd = device.vendorData || {};
  const ports = vd.netgearPorts;
  if (!ports?.length) return null;

  // Snapshots are manual and therefore stale by definition. The capture time
  // goes on the face of the panel, not in a tooltip -- an operator reading
  // this during a show needs to know at a glance whether it is ten minutes or
  // one load-in old.
  const asOf = vd.snapshotAsOf;

  return (
    <div style={{ background: 'var(--color-surface)', borderRadius: 4, padding: 8, marginBottom: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6 }}>
        <div style={{ color: 'var(--color-text-muted)', fontSize: 11, letterSpacing: 1 }}>
          SWITCH PORTS (SNAPSHOT)
        </div>
        <div style={{ color: 'var(--color-text-muted)', fontSize: 10 }}>
          snapshot {asOf ? timeAgo(asOf) : 'time unknown'}
        </div>
      </div>

      {vd.netgearPortHostsAvailable === false && (
        <div style={{ color: 'var(--color-brand-hi)', fontSize: 10, marginBottom: 6 }}>
          Per-port host details were not readable from this page — VLAN, PoE and
          link state below are still accurate.
        </div>
      )}

      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={HEAD}>PORT</th>
            <th style={HEAD}>PROFILE</th>
            <th style={HEAD}>VLAN</th>
            <th style={HEAD}>LINK</th>
            <th style={HEAD}>PoE</th>
            <th style={HEAD}>CONNECTED</th>
          </tr>
        </thead>
        <tbody>
          {ports.map(p => (
            <tr key={p.port} style={{ borderTop: '1px solid var(--color-border)' }}>
              <td style={CELL}>
                <span style={{
                  display: 'inline-block', width: 8, height: 8, borderRadius: 2,
                  background: p.color || 'transparent', marginRight: 6,
                }} />
                {p.port}{p.media === 'fiber' ? ' (SFP)' : ''}
              </td>
              <td style={CELL}>{p.trunk ? `Trunk (${p.trunk})` : (p.profile || '—')}</td>
              <td style={CELL}>{p.vlans?.length ? p.vlans.join(', ') : '—'}</td>
              <td style={{ ...CELL, color: p.linkUp ? 'var(--color-online)' : 'var(--color-text-muted)' }}>
                {p.linkUp ? (p.linkSpeed || 'up') : 'down'}
              </td>
              <td style={CELL}>{p.poe ? 'yes' : '—'}</td>
              <td style={CELL}>{p.host || p.ip || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

Create `app/src/components/NetgearProfilesTable.jsx`:

```jsx
import React from 'react';
import { timeAgo } from '../utils/timeAgo';

const CELL = { padding: '3px 8px', fontSize: 12, textAlign: 'left' };
const HEAD = { ...CELL, color: 'var(--color-text-muted)', fontSize: 10, letterSpacing: 1 };

export default function NetgearProfilesTable({ device }) {
  const vd = device.vendorData || {};
  const profiles = vd.profiles;
  if (!profiles?.length) return null;

  return (
    <div style={{ background: 'var(--color-surface)', borderRadius: 4, padding: 8, marginBottom: 8 }}>
      {/* Carries its own capture time rather than relying on the ports panel's.
          The two panels are populated from independent parts of the page and
          either can render without the other, so a shared timestamp somewhere
          above them would sometimes describe data that isn't on screen. */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6 }}>
        <div style={{ color: 'var(--color-text-muted)', fontSize: 11, letterSpacing: 1 }}>
          NETWORK PROFILES
        </div>
        <div style={{ color: 'var(--color-text-muted)', fontSize: 10 }}>
          snapshot {vd.snapshotAsOf ? timeAgo(vd.snapshotAsOf) : 'time unknown'}
        </div>
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={HEAD}>PROFILE</th>
            <th style={HEAD}>TEMPLATE</th>
            <th style={HEAD}>VLAN</th>
            <th style={HEAD}>PORTS</th>
          </tr>
        </thead>
        <tbody>
          {profiles.map(p => (
            <tr key={p.name} style={{ borderTop: '1px solid var(--color-border)' }}>
              <td style={CELL}>
                {/* The switch's own swatch colour, reused rather than a second
                    palette invented for the same four networks. */}
                <span style={{
                  display: 'inline-block', width: 8, height: 8, borderRadius: 2,
                  background: p.color || 'transparent', marginRight: 6,
                }} />
                {p.name}
              </td>
              <td style={CELL}>{p.template || '—'}</td>
              <td style={CELL}>{p.vlan ?? '—'}</td>
              <td style={CELL}>{p.portCount ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd app && npm test -- NetgearPortTable
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add app/src/components/NetgearPortTable.jsx app/src/components/NetgearPortTable.test.jsx app/src/components/NetgearProfilesTable.jsx
git commit -m "feat: switch port and profile tables for the Network tab"
```

---

### Task 9: The import panel, and wiring into DeviceDetail

**Files:**
- Create: `app/src/components/SnapshotImportPanel.jsx`
- Create: `app/src/components/SnapshotImportPanel.test.jsx`
- Modify: `app/src/pages/NetworkMonitor.jsx` (import at top; render inside `DeviceDetail` after the `<PortTable device={device} />` at line 307)

**Interfaces:**
- Consumes: `POST /api/network/snapshot` from Task 6; `NetgearPortTable`, `NetgearProfilesTable` from Task 8.
- Produces: `SnapshotImportPanel({ device, onImported })`, where `onImported()` is the existing refresh callback so the tables repaint.

- [ ] **Step 1: Write the failing test**

Create `app/src/components/SnapshotImportPanel.test.jsx`:

```jsx
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import axios from 'axios'
import SnapshotImportPanel from './SnapshotImportPanel'

vi.mock('axios')

const NETGEAR = { macAddress: 'AA', deviceType: 'netgear', vendorData: {} }
const NODE = { macAddress: 'BB', deviceType: 'swisson', vendorData: {} }

beforeEach(() => { vi.resetAllMocks() })

describe('SnapshotImportPanel', () => {
  it('renders nothing for a non-NETGEAR device', () => {
    const { container } = render(<SnapshotImportPanel device={NODE} onImported={() => {}} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('posts pasted html and reports what was imported', async () => {
    axios.post.mockResolvedValue({ data: {
      macAddress: 'AA', systemName: 'FMB Switch 60',
      profileCount: 5, portCount: 12, hostDataAvailable: true,
    } })
    const onImported = vi.fn()
    render(<SnapshotImportPanel device={NETGEAR} onImported={onImported} />)

    fireEvent.click(screen.getByText(/import switch snapshot/i))
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '<html>x</html>' } })
    fireEvent.click(screen.getByText(/^import$/i))

    await waitFor(() => expect(onImported).toHaveBeenCalled())
    expect(axios.post).toHaveBeenCalledWith('/api/network/snapshot', { html: '<html>x</html>' })
    expect(screen.getByText(/FMB Switch 60/)).toBeTruthy()
    expect(screen.getByText(/5 profiles/)).toBeTruthy()
  })

  it('surfaces the server refusal detail rather than a generic failure', async () => {
    axios.post.mockRejectedValue({
      response: { status: 409, data: { error: 'serial_conflict', detail: 'Recorded with serial X.' } },
    })
    render(<SnapshotImportPanel device={NETGEAR} onImported={() => {}} />)
    fireEvent.click(screen.getByText(/import switch snapshot/i))
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '<html>x</html>' } })
    fireEvent.click(screen.getByText(/^import$/i))

    await waitFor(() => expect(screen.getByText(/Recorded with serial X\./)).toBeTruthy())
  })

  it('warns when host data was dropped', async () => {
    axios.post.mockResolvedValue({ data: {
      macAddress: 'AA', systemName: 'S', profileCount: 5, portCount: 12,
      hostDataAvailable: false,
    } })
    render(<SnapshotImportPanel device={NETGEAR} onImported={() => {}} />)
    fireEvent.click(screen.getByText(/import switch snapshot/i))
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '<html>x</html>' } })
    fireEvent.click(screen.getByText(/^import$/i))

    await waitFor(() => expect(screen.getByText(/host details were not readable/i)).toBeTruthy())
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd app && npm test -- SnapshotImportPanel
```

Expected: FAIL — cannot resolve `./SnapshotImportPanel`.

- [ ] **Step 3: Write the implementation**

Create `app/src/components/SnapshotImportPanel.jsx`:

```jsx
import React, { useState } from 'react';
import axios from 'axios';

const HINT = 'In the switch UI at Configure → Overview, open the browser console and run '
  + 'copy(document.documentElement.outerHTML), then paste here.';

export default function SnapshotImportPanel({ device, onImported }) {
  const [open, setOpen] = useState(false);
  const [html, setHtml] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  if (device.deviceType !== 'netgear') return null;

  const submit = () => {
    setBusy(true);
    setError(null);
    setResult(null);
    axios.post('/api/network/snapshot', { html })
      .then(res => {
        setResult(res.data);
        setHtml('');
        onImported?.();
      })
      // The server's refusals are specific and actionable -- which switch the
      // MAC belongs to, which serial conflicts. Showing a generic "import
      // failed" would throw away the only part that tells the operator what to
      // do next.
      .catch(err => setError(err?.response?.data?.detail || 'Import failed.'))
      .finally(() => setBusy(false));
  };

  return (
    <div style={{ background: 'var(--color-surface)', borderRadius: 4, padding: 8, marginBottom: 8 }}>
      <div
        onClick={() => setOpen(o => !o)}
        style={{ color: 'var(--color-text-muted)', fontSize: 11, letterSpacing: 1, cursor: 'pointer' }}
      >
        {open ? '▾' : '▸'} IMPORT SWITCH SNAPSHOT
      </div>

      {open && (
        <div style={{ marginTop: 8 }}>
          <div style={{ color: 'var(--color-text-muted)', fontSize: 10, marginBottom: 6 }}>{HINT}</div>
          <textarea
            value={html}
            onChange={e => setHtml(e.target.value)}
            placeholder="Paste the page HTML"
            style={{
              width: '100%', height: 70, boxSizing: 'border-box',
              background: 'var(--color-bg)', color: 'var(--color-text)',
              border: '1px solid var(--color-border)', borderRadius: 4,
              fontSize: 11, padding: 6,
            }}
          />
          <button
            onClick={submit}
            disabled={busy || !html.trim()}
            style={{
              marginTop: 6, background: 'var(--color-surface-2)', color: 'var(--color-gel)',
              border: '1px solid var(--color-border)', borderRadius: 4,
              padding: '4px 10px', fontSize: 11, cursor: 'pointer',
            }}
          >
            {busy ? 'Importing…' : 'Import'}
          </button>

          {result && (
            <div style={{ marginTop: 6, fontSize: 10, color: 'var(--color-online)' }}>
              Imported {result.systemName || result.macAddress} — {result.profileCount} profiles,
              {' '}{result.portCount} ports.
              {result.hostDataAvailable === false && (
                <span style={{ color: 'var(--color-brand-hi)' }}>
                  {' '}Per-port host details were not readable from this page.
                </span>
              )}
            </div>
          )}
          {error && (
            <div style={{ marginTop: 6, fontSize: 10, color: 'var(--color-brand-hi)' }}>{error}</div>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd app && npm test -- SnapshotImportPanel
```

Expected: 4 passed.

- [ ] **Step 5: Add a refresh path for the selected device**

`DeviceDetail` is `function DeviceDetail({ device, locations, onUpdate })` (line 184) — there is no refresh prop, and `fetchDevices` (line 455) only calls `setDevices`. `selectedDevice` is separate state rendered at line 664, so a refetch alone would leave the panel showing pre-import data.

Add this next to `updateDevice` (line 527) in `NetworkMonitor.jsx`, mirroring how that function updates both pieces of state:

```jsx
  // The import writes vendor_data server-side rather than through
  // updateDevice's PATCH, so both the list and the selected-device copy have
  // to be re-read. Without the second setState the panel keeps rendering the
  // pre-import device object and the new tables never appear.
  const refreshDevice = async (mac) => {
    try {
      const res = await axios.get('/api/network/devices');
      setDevices(res.data);
      setSelectedDevice(prev => res.data.find(
        d => d.macAddress === (mac || prev?.macAddress)) || prev);
    } catch (e) {
      console.error('refresh device', e);
    }
  };
```

- [ ] **Step 6: Wire the three components into DeviceDetail**

Add beside the existing `PortTable` import at line 4:

```jsx
import NetgearPortTable from '../components/NetgearPortTable';
import NetgearProfilesTable from '../components/NetgearProfilesTable';
import SnapshotImportPanel from '../components/SnapshotImportPanel';
```

Widen the signature at line 184:

```jsx
function DeviceDetail({ device, locations, onUpdate, onRefresh }) {
```

Pass it at line 664:

```jsx
            ? <DeviceDetail device={selectedDevice} locations={locationsWithDevices} onUpdate={updateDevice} onRefresh={refreshDevice} />
```

Then replace the single line `<PortTable device={device} />` (line 307) with:

```jsx
      <PortTable device={device} />
      <NetgearProfilesTable device={device} />
      <NetgearPortTable device={device} />
      <SnapshotImportPanel device={device} onImported={() => onRefresh?.(device.macAddress)} />
```

Add the snapshot-only meta cells to the existing grid, after the `SERIAL` cell:

```jsx
        <MetaCell label="MGMT IP" value={vd.managementIp} />
        <MetaCell label="TEMP" value={vd.tempC != null ? `${vd.tempC}°C` : null} />
```

- [ ] **Step 7: Run the whole frontend suite**

```bash
cd app && npm test
```

Expected: all suites pass, including the pre-existing `PortTable` tests — confirming a switch's `netgearPorts` never triggers the DMX table.

- [ ] **Step 8: Run the whole backend suite on the app interpreter**

```bash
cd backend && python -m pytest -q
```

Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add app/src/components/SnapshotImportPanel.jsx app/src/components/SnapshotImportPanel.test.jsx app/src/pages/NetworkMonitor.jsx
git commit -m "feat: import panel and switch tables wired into the Network tab"
```

---

## Manual verification

After Task 9, with the backend running:

1. Open the Network tab and select a NETGEAR switch. Expand **IMPORT SWITCH SNAPSHOT**.
2. Capture the page from that switch's AV UI and paste it. Confirm the result line reports the right system name, 5 profiles, 12 ports.
3. Confirm **NETWORK PROFILES** shows all five with the switch's own colours, and **SWITCH PORTS (SNAPSHOT)** shows twelve rows — port 3 HogNet/600 with PoE, port 8 Comms/400, port 1 as the auto-trunk to FMB Switch 52 at 1000 Full, and port 5 up at 100T Full showing the Raspberry Pi drawing 6 W.
4. Confirm the snapshot age is on the panel face and advances.
5. Paste the *same* page while a *different* switch is selected. Expect a refusal naming the MAC, and no change to either device.
6. Wait one 300s sweep. Confirm the profile and port tables are still populated — this is the precedence rule holding in production, not just in Task 7's test.
