# NETGEAR Port Configuration Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read per-port Profile Name and Profile Template from a saved NETGEAR Port Configuration page — real table rows keyed to the port — instead of depending on the Overview page's document-order popover association.

**Architecture:** `netgear_snapshot.py` gains a page-type sniffer and a second pure parser. `POST /api/network/snapshot` dispatches on page type; a portconfig import identifies its switch from an explicit `macAddress` in the request, never from the page. Results land in a new `netgearPortConfig` key so an Overview re-import cannot discard them.

**Tech Stack:** Python 3.12 (app interpreter), BeautifulSoup 4.14.3 with `html.parser`, Flask, pytest. React 18 frontend, vitest.

**Spec:** `docs/superpowers/specs/2026-08-10-netgear-portconfig-import-design.md`

## Global Constraints

- **Run tests on the APP interpreter**, always by full path: `C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe`. `python` on PATH is 3.14 with a different package set; a green suite there says nothing about the app runtime.
- **`html.parser` only.** No lxml — it is not a dependency of this project.
- **The parser is pure.** No network, no database, no Flask imports in `netgear_snapshot.py`.
- **Never raise on malformed input.** The parser is fed operator-pasted text from firmware that can change; return `{}` or `[]` rather than raising, matching `parse_snapshot`.
- **Nothing is ever deleted** from `vendor_data`. A partial capture must be safe.
- **Expected values come from the fixture file**, read by running the parser — never transcribed from a chat paste. A paste taken at a different moment than the file will disagree on time-varying fields.
- **Branch:** `feat/claude/netgear-portconfig-import`. Do not commit to `main`.

---

### Task 1: Page detection and the portconfig parser

**Files:**
- Modify: `backend/app/vendors/netgear_snapshot.py`
- Test: `backend/tests/test_netgear_portconfig.py` (create)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces:
  - `detect_page_type(html: str) -> str | None` returning `'overview'`, `'portconfig'`, or `None`
  - `parse_portconfig(html: str) -> list[dict]` returning `[{'port': int, 'profile': str, 'template': str, 'linkUp': bool, 'poe': bool}, ...]` sorted by port

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_netgear_portconfig.py`:

```python
"""Port Configuration page parser tests.

Run against the real capture, never a synthetic fixture.

[VERIFIED 2026-08-10] The page's table is a `vue-recycle-scroller`, so a saved
page contains ONLY the rows rendered at capture time. This fixture is a
12-port switch and holds 10 rows; ports 11 and 12 are absent from the file.
The 10 below is therefore the CORRECT expected value, not a parser bug.
"""
from pathlib import Path

import pytest

from app.vendors.netgear_snapshot import detect_page_type, parse_portconfig

FIXTURES = Path(__file__).parent / 'fixtures'
PORTCONFIG = FIXTURES / 'netgear_m4250_portconfig.html'
OVERVIEW = FIXTURES / 'netgear_m4250_overview.html'


@pytest.fixture
def portconfig_html():
    return PORTCONFIG.read_text(encoding='utf-8')


def test_detects_the_portconfig_page(portconfig_html):
    assert detect_page_type(portconfig_html) == 'portconfig'


def test_detects_the_overview_page():
    assert detect_page_type(OVERVIEW.read_text(encoding='utf-8')) == 'overview'


def test_returns_none_for_anything_else():
    assert detect_page_type('<html><body>hello</body></html>') is None
    assert detect_page_type('') is None
    assert detect_page_type(None) is None


def test_parses_only_the_rows_that_were_captured(portconfig_html):
    # Ten of twelve. See the module docstring -- this is the virtual scroller,
    # and pinning it here stops a future reader "fixing" it.
    rows = parse_portconfig(portconfig_html)
    assert len(rows) == 10
    assert [r['port'] for r in rows] == list(range(1, 11))


def test_reads_profile_and_template_from_the_row(portconfig_html):
    rows = {r['port']: r for r in parse_portconfig(portconfig_html)}
    assert rows[3]['profile'] == 'HogNet'
    assert rows[3]['template'] == 'Data'
    assert rows[1]['profile'] == 'Default'
    assert rows[1]['template'] == 'Default'


def test_reads_link_state_for_cross_checking(portconfig_html):
    rows = {r['port']: r for r in parse_portconfig(portconfig_html)}
    assert rows[1]['linkUp'] is True
    assert rows[2]['linkUp'] is False


def test_never_raises_on_junk():
    assert parse_portconfig('') == []
    assert parse_portconfig(None) == []
    assert parse_portconfig('<div class="port-configuration-row"></div>') == []
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd C:/dev/Five12-TheApp/backend && "C:/Users/antho/AppData/Local/Programs/Python/Python312/python.exe" -m pytest tests/test_netgear_portconfig.py -v
```

Expected: FAIL with `ImportError: cannot import name 'detect_page_type'`.

- [ ] **Step 3: Implement both functions**

Add to `backend/app/vendors/netgear_snapshot.py`, after `_parse_ports`:

```python
def detect_page_type(html) -> str | None:
    """Which AV UI page this is, or None.

    Cheap string tests before any parse: the route is handed whatever JSON
    supplied, and building a soup for a 440KB page only to reject it is waste.
    Order matters -- the portconfig page also contains port graphics, but only
    it carries `.port-configuration-row`.
    """
    if not isinstance(html, str) or not html:
        return None
    if 'port-configuration-row' in html:
        return 'portconfig'
    if 'device_manageip' in html:
        return 'overview'
    return None


def parse_portconfig(html) -> list:
    """Per-port profile and template from a Port Configuration page.

    Structural, unlike _merge_popovers: the port number and its profile live in
    the SAME row, so nothing here depends on document order.

    [VERIFIED 2026-08-10] The table is a `vue-recycle-scroller`. A saved page
    holds only the rows rendered at capture time -- 10 of 12 in the fixture --
    so the caller must treat the result as a SUPPLEMENT and never as the set of
    ports that exist.
    """
    if not isinstance(html, str) or not html:
        return []
    soup = BeautifulSoup(html, _PARSER)
    out = []
    for row in soup.select('.port-configuration-row'):
        number = _int_in(_text(row.select_one('.port-cell .lan-font')))
        if number is None:
            continue
        cells = row.select('.scrollable-cells > .cell')
        # Profile Name and Profile Template are the last two columns. Indexing
        # from the END keeps this working if a firmware adds a column earlier
        # in the row, which is the likelier change.
        if len(cells) < 2:
            continue
        content = row.select_one('.port-cell .lan-content')
        classes = content.get('class', []) if content else []
        out.append({
            'port': number,
            'profile': _text(cells[-2]),
            'template': _text(cells[-1]),
            'linkUp': bool(_LINK_UP_CLASSES & set(classes)),
            'poe': row.select_one('.port-poe') is not None,
        })
    out.sort(key=lambda r: r['port'])
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd C:/dev/Five12-TheApp/backend && "C:/Users/antho/AppData/Local/Programs/Python/Python312/python.exe" -m pytest tests/test_netgear_portconfig.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Prove the row test is not vacuous**

Temporarily change `cells[-2]` to `cells[15]` and `cells[-1]` to `cells[16]` (positional instead of end-relative), re-run, and confirm the tests still pass — they should, since the fixture has 17 cells. Then temporarily change to `cells[0]` and `cells[1]` and confirm `test_reads_profile_and_template_from_the_row` FAILS. Revert both edits.

This proves the assertion is reading the columns it claims to read, not passing by coincidence.

- [ ] **Step 6: Commit**

```bash
git add backend/app/vendors/netgear_snapshot.py backend/tests/test_netgear_portconfig.py
git commit -m "Parse the Port Configuration page's per-port profile rows"
```

---

### Task 2: Route dispatch and the supplement merge

**Files:**
- Modify: `backend/app/network_routes.py:409-500` (the `import_snapshot` handler)
- Test: `backend/tests/test_netgear_portconfig_routes.py` (create)

**Interfaces:**
- Consumes: `detect_page_type(html)` and `parse_portconfig(html)` from Task 1.
- Produces: `POST /api/network/snapshot` accepting `{html, macAddress}`; on a portconfig page returns 200 with keys `macAddress`, `portsUpdated` (int), `portsInCaptureNotInBase` (list of int), `disagreements` (list of dict), `portConfigAsOf` (ISO string).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_netgear_portconfig_routes.py`:

```python
"""Portconfig import route tests.

The Port Configuration page carries NO identity fields at all -- no management
IP, name, model or serial. Worse, the only IP readable as TEXT on it is the
LLDP neighbour's (172.16.3.52, "FMB Switch 52"), while the switch's own
(172.16.3.73) appears solely inside attributes and scripts. So identity here is
an explicit operator choice, and these tests exist to prove the route never
infers it from the page.
"""
from pathlib import Path

import pytest

from app import db
from app.models import NetworkDevice

FIXTURES = Path(__file__).parent / 'fixtures'
PORTCONFIG = FIXTURES / 'netgear_m4250_portconfig.html'

SCANNER_MAC = '28:94:01:84:3C:E1'
MGMT_IP = '172.16.3.73'
# The LLDP neighbour that appears as visible text on the page. No request may
# ever be filed against this device.
NEIGHBOUR_MAC = '28:94:01:84:47:05'
NEIGHBOUR_IP = '172.16.3.52'


@pytest.fixture
def portconfig_html():
    return PORTCONFIG.read_text(encoding='utf-8')


@pytest.fixture
def switch(db):
    """A switch that already holds an Overview snapshot, plus the neighbour."""
    device = NetworkDevice(mac_address=SCANNER_MAC, device_type='netgear',
                           last_ip=MGMT_IP)
    device.vendor_data = {
        'serial': 'ABC123',
        'netgearPorts': [
            {'port': 1, 'profile': 'Default', 'template': 'Default', 'linkUp': True},
            {'port': 3, 'profile': 'WRONG', 'template': 'Data', 'linkUp': False},
            {'port': 12, 'profile': 'VidNet', 'template': 'Video', 'linkUp': True},
        ],
    }
    neighbour = NetworkDevice(mac_address=NEIGHBOUR_MAC, device_type='netgear',
                              last_ip=NEIGHBOUR_IP)
    db.session.add_all([device, neighbour])
    db.session.commit()
    yield device
    for row in db.session.query(NetworkDevice).all():
        db.session.delete(row)
    db.session.commit()


def test_refuses_a_portconfig_page_with_no_device(client, switch, portconfig_html):
    res = client.post('/api/network/snapshot', json={'html': portconfig_html})
    assert res.status_code == 400
    assert res.get_json()['error'] == 'device_required'


def test_refuses_an_unknown_mac(client, switch, portconfig_html):
    res = client.post('/api/network/snapshot',
                      json={'html': portconfig_html, 'macAddress': 'AA:BB:CC:DD:EE:FF'})
    assert res.status_code == 404
    assert res.get_json()['error'] == 'unknown_device'


def test_refuses_a_device_with_no_base_snapshot(client, switch, portconfig_html):
    res = client.post('/api/network/snapshot',
                      json={'html': portconfig_html, 'macAddress': NEIGHBOUR_MAC})
    assert res.status_code == 409
    assert res.get_json()['error'] == 'no_base_snapshot'


def test_never_files_against_the_neighbour_named_on_the_page(client, switch, portconfig_html):
    """The page names 172.16.3.52 as text. Importing for the real switch must
    leave that device completely untouched."""
    client.post('/api/network/snapshot',
                json={'html': portconfig_html, 'macAddress': SCANNER_MAC})
    neighbour = (db.session.query(NetworkDevice)
                 .filter_by(mac_address=NEIGHBOUR_MAC).one())
    assert not (neighbour.vendor_data or {}).get('netgearPortConfig')


def test_stores_profiles_under_its_own_key(client, switch, portconfig_html):
    res = client.post('/api/network/snapshot',
                      json={'html': portconfig_html, 'macAddress': SCANNER_MAC})
    assert res.status_code == 200
    device = db.session.query(NetworkDevice).filter_by(mac_address=SCANNER_MAC).one()
    rows = {r['port']: r for r in device.vendor_data['netgearPortConfig']}
    assert rows[3]['profile'] == 'HogNet'
    # netgearPorts is NOT rewritten -- the two sources stay distinguishable.
    ports = {p['port']: p for p in device.vendor_data['netgearPorts']}
    assert ports[3]['profile'] == 'WRONG'


def test_leaves_an_uncaptured_port_alone(client, switch, portconfig_html):
    """Port 12 is not in the capture (virtual scroller). It must survive."""
    client.post('/api/network/snapshot',
                json={'html': portconfig_html, 'macAddress': SCANNER_MAC})
    device = db.session.query(NetworkDevice).filter_by(mac_address=SCANNER_MAC).one()
    ports = {p['port']: p for p in device.vendor_data['netgearPorts']}
    assert ports[12]['profile'] == 'VidNet'


def test_reports_a_profile_disagreement_without_failing(client, switch, portconfig_html):
    """Port 3's stored popover-derived profile is 'WRONG'; the row says
    'HogNet'. That disagreement is the evidence the popover association
    misattributed, and it is reported, not fatal."""
    res = client.post('/api/network/snapshot',
                      json={'html': portconfig_html, 'macAddress': SCANNER_MAC})
    assert res.status_code == 200
    body = res.get_json()
    ports = [d['port'] for d in body['disagreements']]
    assert 3 in ports
    assert 1 not in ports


def test_reports_captured_ports_absent_from_the_base(client, switch, portconfig_html):
    res = client.post('/api/network/snapshot',
                      json={'html': portconfig_html, 'macAddress': SCANNER_MAC})
    # The base holds ports 1, 3, 12. The capture holds 1..10.
    assert res.get_json()['portsInCaptureNotInBase'] == [2, 4, 5, 6, 7, 8, 9, 10]


def test_an_overview_page_still_imports_unchanged(client, db):
    """Regression: dispatch must not break the existing path."""
    overview = (FIXTURES / 'netgear_m4250_overview.html').read_text(encoding='utf-8')
    device = NetworkDevice(mac_address=SCANNER_MAC, device_type='netgear', last_ip=MGMT_IP)
    db.session.add(device)
    db.session.commit()
    res = client.post('/api/network/snapshot', json={'html': overview})
    assert res.status_code == 200
    assert res.get_json()['portCount'] == 12
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd C:/dev/Five12-TheApp/backend && "C:/Users/antho/AppData/Local/Programs/Python/Python312/python.exe" -m pytest tests/test_netgear_portconfig_routes.py -v
```

Expected: FAIL — the route currently returns 422 `unrecognised_page` for a portconfig page, because it has no serial or management IP.

- [ ] **Step 3: Split the handler and add the portconfig branch**

In `backend/app/network_routes.py`, replace the body of `import_snapshot` from the `payload = request.get_json(...)` line down to (but not including) `ip = (parsed.get('managementIp')...` with:

```python
    from .vendors.netgear_snapshot import (detect_page_type, parse_portconfig,
                                           parse_snapshot)

    payload = request.get_json(silent=True) or {}
    html = payload.get('html') or ''

    if detect_page_type(html) == 'portconfig':
        return _import_portconfig(html, payload.get('macAddress'))

    parsed = parse_snapshot(html)
```

Then add this new function immediately after `import_snapshot`:

```python
def _import_portconfig(html, mac):
    """Fold a Port Configuration capture into an existing snapshot.

    SUPPLEMENT ONLY. The page's table is a virtual scroller, so a capture holds
    only the rows that were scrolled into view -- 10 of 12 on the fixture
    switch. Ports it omits are left exactly as they were.

    Identity is the caller's `macAddress` and never the page. The page carries
    no identity fields, and the only IP readable as text on it belongs to the
    LLDP NEIGHBOUR, so inferring identity here would file one switch's
    configuration against another -- the precise failure this route exists to
    refuse.
    """
    from datetime import datetime

    from .models import _utc_iso
    # Imported here as well as in import_snapshot: this is a separate function
    # and does not see that one's local imports.
    from .vendors.netgear_snapshot import parse_portconfig

    if not mac:
        return jsonify({
            'error': 'device_required',
            'detail': 'A Port Configuration page does not say which switch it '
                      'came from. Import it from the switch you want to update.',
        }), 400

    device = (db.session.query(NetworkDevice)
              .filter(NetworkDevice.mac_address == mac).one_or_none())
    if device is None:
        return jsonify({
            'error': 'unknown_device',
            'detail': f'No device known with MAC {mac}. Nothing was changed.',
        }), 404

    stored = device.vendor_data or {}
    base = stored.get('netgearPorts') or []
    if not base:
        return jsonify({
            'error': 'no_base_snapshot',
            'detail': 'Import the Configure -> Overview page for this switch '
                      'first. A Port Configuration page only fills in the '
                      'ports it captured, so it needs a full snapshot to '
                      'supplement.',
        }), 409

    rows = parse_portconfig(html)
    by_port = {p['port']: p for p in base}

    disagreements = []
    link_differs = []
    absent = []
    kept = []
    for row in rows:
        prior = by_port.get(row['port'])
        if prior is None:
            absent.append(row['port'])
            continue
        # profile/template on `prior` came from the popovers. A disagreement is
        # evidence the document-order association misattributed this port.
        for field in ('profile', 'template'):
            if prior.get(field) and row[field] and prior[field] != row[field]:
                disagreements.append({
                    'port': row['port'], 'field': field,
                    'popover': prior[field], 'portConfig': row[field],
                })
        # Link state and PoE are a SECONDARY note, deliberately kept out of
        # `disagreements`. Both sides read them structurally, so a difference
        # says nothing about the popover association -- and the two pages are
        # saved minutes apart, so a port can legitimately have changed state
        # between them. Reported separately and labelled as such.
        if prior.get('linkUp') is not None and prior['linkUp'] != row['linkUp']:
            link_differs.append(row['port'])
        kept.append({'port': row['port'], 'profile': row['profile'],
                     'template': row['template']})

    as_of = _utc_iso(datetime.utcnow())
    device.vendor_data = {**stored,
                          'netgearPortConfig': kept,
                          'portConfigAsOf': as_of}
    db.session.commit()

    return jsonify({
        'macAddress': device.mac_address,
        'portsUpdated': len(kept),
        'portsInCaptureNotInBase': absent,
        'disagreements': disagreements,
        'linkStateDiffers': link_differs,
        'portConfigAsOf': as_of,
    })
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd C:/dev/Five12-TheApp/backend && "C:/Users/antho/AppData/Local/Programs/Python/Python312/python.exe" -m pytest tests/test_netgear_portconfig_routes.py tests/test_netgear_snapshot_routes.py -v
```

Expected: all pass, including the pre-existing Overview route tests.

- [ ] **Step 5: Prove the no-delete guarantee is not vacuous**

Temporarily change the `device.vendor_data = {...}` line to also write `'netgearPorts': [p for p in base if p['port'] in by_port and p['port'] <= 10]`, re-run, and confirm `test_leaves_an_uncaptured_port_alone` FAILS. Revert.

- [ ] **Step 6: Run the whole backend suite**

```bash
cd C:/dev/Five12-TheApp/backend && "C:/Users/antho/AppData/Local/Programs/Python/Python312/python.exe" -m pytest -q
```

Expected: no regressions against the pre-change count.

- [ ] **Step 7: Commit**

```bash
git add backend/app/network_routes.py backend/tests/test_netgear_portconfig_routes.py
git commit -m "Import a Port Configuration capture as a supplement, keyed by an explicit MAC"
```

---

### Task 3: Panel sends the device and reports the result

**Files:**
- Modify: `app/src/components/SnapshotImportPanel.jsx`
- Test: `app/src/components/SnapshotImportPanel.test.jsx`

**Interfaces:**
- Consumes: the 200 body from Task 2 — `portsUpdated`, `portsInCaptureNotInBase`, `disagreements`.
- Produces: no new exports. The component already receives `device`.

- [ ] **Step 1: Write the failing tests**

Add to `app/src/components/SnapshotImportPanel.test.jsx`:

```jsx
it('sends the selected device MAC with the paste', async () => {
  axios.post.mockResolvedValue({ data: { portsUpdated: 10 } });
  render(<SnapshotImportPanel device={{ deviceType: 'netgear', macAddress: 'AA:BB' }} />);
  fireEvent.click(screen.getByText(/IMPORT SWITCH SNAPSHOT/));
  fireEvent.change(screen.getByPlaceholderText(/Paste the page HTML/), {
    target: { value: '<html>x</html>' },
  });
  fireEvent.click(screen.getByText('Import'));
  await waitFor(() => expect(axios.post).toHaveBeenCalledWith(
    '/api/network/snapshot',
    { html: '<html>x</html>', macAddress: 'AA:BB' },
  ));
});

it('names the ports a partial capture missed', async () => {
  axios.post.mockResolvedValue({
    data: { portsUpdated: 10, portsInCaptureNotInBase: [11, 12], disagreements: [] },
  });
  render(<SnapshotImportPanel device={{ deviceType: 'netgear', macAddress: 'AA:BB' }} />);
  fireEvent.click(screen.getByText(/IMPORT SWITCH SNAPSHOT/));
  fireEvent.change(screen.getByPlaceholderText(/Paste the page HTML/), {
    target: { value: '<html>x</html>' },
  });
  fireEvent.click(screen.getByText('Import'));
  await screen.findByText(/11, 12/);
});

it('surfaces a profile disagreement as a warning', async () => {
  axios.post.mockResolvedValue({
    data: {
      portsUpdated: 10, portsInCaptureNotInBase: [],
      disagreements: [{ port: 3, field: 'profile', popover: 'WRONG', portConfig: 'HogNet' }],
    },
  });
  render(<SnapshotImportPanel device={{ deviceType: 'netgear', macAddress: 'AA:BB' }} />);
  fireEvent.click(screen.getByText(/IMPORT SWITCH SNAPSHOT/));
  fireEvent.change(screen.getByPlaceholderText(/Paste the page HTML/), {
    target: { value: '<html>x</html>' },
  });
  fireEvent.click(screen.getByText('Import'));
  await screen.findByText(/port 3/i);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd C:/dev/Five12-TheApp/app && npm test -- SnapshotImportPanel
```

Expected: FAIL — `axios.post` is called with `{ html }` only.

- [ ] **Step 3: Send the MAC and render the portconfig result**

In `app/src/components/SnapshotImportPanel.jsx`, change the post call:

```jsx
    axios.post('/api/network/snapshot', { html, macAddress: device.macAddress })
```

Update `HINT` to name both pages:

```jsx
const HINT = 'In the switch UI at Configure → Overview (or Port Configuration), open the '
  + 'browser console and run copy(document.documentElement.outerHTML), then paste here. '
  + 'A Port Configuration page only carries the rows you scrolled into view.';
```

Add this block inside the `{result && (...)}` div, after the existing ports line:

```jsx
              {result.portsUpdated !== undefined && (
                <>
                  Port configuration: {result.portsUpdated} ports updated.
                  {result.portsInCaptureNotInBase?.length > 0 && (
                    <span style={{ color: 'var(--color-text-muted)' }}>
                      {' '}Not in the snapshot: {result.portsInCaptureNotInBase.join(', ')}.
                    </span>
                  )}
                  {result.disagreements?.map(d => (
                    <div key={`${d.port}-${d.field}`} style={{ color: 'var(--color-brand-hi)' }}>
                      Port {d.port}: the snapshot says {d.field} “{d.popover}”, this page says
                      {' '}“{d.portConfig}”. The snapshot value came from the page's popovers,
                      which are matched by document order — treat this page as correct.
                    </div>
                  ))}
                </>
              )}
```

Guard the existing Overview line so it does not render for a portconfig result — change its wrapper condition to `{result.portCount !== undefined && (...)}`.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd C:/dev/Five12-TheApp/app && npm test -- SnapshotImportPanel
```

Expected: all pass.

- [ ] **Step 5: Run the whole frontend suite**

```bash
cd C:/dev/Five12-TheApp/app && npm test
```

Expected: no regressions against the pre-change count.

- [ ] **Step 6: Commit**

```bash
git add app/src/components/SnapshotImportPanel.jsx app/src/components/SnapshotImportPanel.test.jsx
git commit -m "Send the selected switch with a snapshot paste and report the portconfig result"
```

---

### Task 4: Verify on the rig and record it

**Files:**
- Modify: `docs/superpowers/specs/2026-08-10-netgear-portconfig-import-design.md` (status line and a Verification section)

Tests prove the mapping. They cannot prove the running backend accepts a page the operator actually saved today, and on this feature's sibling that gap hid a wrong-checkout dev server for most of a session.

- [ ] **Step 1: Confirm the dev stack is serving this branch**

```bash
pwsh -File C:/dev/Five12-TheApp/scripts/doctor.ps1
```

Expected: `OK Dev server  port 5173 serves C:\dev\Five12-TheApp\app`. A FAIL here means the browser is showing another checkout — fix before believing anything below.

- [ ] **Step 2: Capture a live page**

In the switch's AV UI at Configure → Port Configuration, **scroll the table to the bottom first**, then run `copy(document.documentElement.outerHTML)` in the console.

- [ ] **Step 3: Import it through the UI**

Open the Network tab, select that switch, expand IMPORT SWITCH SNAPSHOT, paste, Import.

Record: how many ports were updated, which ports the capture missed, and whether any disagreement was reported. A disagreement is a real finding — it means the Overview popover association misattributed that port on this switch.

- [ ] **Step 4: Confirm the refusal path on real hardware**

Paste the same page with a different switch selected. Expect a `no_base_snapshot` 409 if that switch has no Overview snapshot, or a successful import with a large `portsInCaptureNotInBase` if it does — and confirm with a read-only query that the first switch's `netgearPortConfig` was not altered.

- [ ] **Step 5: Update the spec and commit**

Set the status line to `implemented 2026-08-10`, add a Verification section recording what steps 3 and 4 actually showed — including the real numbers, not "worked as expected" — and commit.

```bash
git add docs/superpowers/specs/2026-08-10-netgear-portconfig-import-design.md
git commit -m "Record what the portconfig import did on the rig"
```

---

## Notes for the implementer

- **`_text` returns `None` for an empty node**, so `profile` can be `None`. The disagreement check already guards with `prior.get(field) and row[field]`.
- **`_LINK_UP_CLASSES` includes `lan-connected-powered`.** A PoE port that is linked *and* delivering power carries that distinct class, not `lan-connected`. Matching only `lan-connected` reports a live port as down — this was a real defect on 2026-08-10.
- **Do not add a `strictPort`-style "did you scroll?" check.** A short capture is indistinguishable from a complete one in the file; the supplement model is what makes that safe, and `portsInCaptureNotInBase` is what makes it visible.
