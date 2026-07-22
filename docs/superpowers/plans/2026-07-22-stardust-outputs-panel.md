# Stardust Outputs Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-output Outputs table to the Devices-page Stardust panel showing each CRMX output's source protocol, universe/address, CRMX radio type, power, name, and enabled state.

**Architecture:** Keep the existing Art-Net/RDM path in `backend/app/integrations/stardust.py` untouched (it owns discovery, MAC labels, RDM fixtures). Add a complementary, read-only WebSocket poll of the LumenRadio control plane (`ws://<ip>/ws`, JSON `_type_` frames) that fills a new `status['outputs']` list. The frontend renders it as one extra table in `StardustPanel`.

**Tech Stack:** Python 3.12 (Flask backend), `websocket-client` (new), React 19 + Tailwind (frontend).

## Global Constraints

- Python interpreter is `backend/.venv/Scripts/python.exe` (has scapy, puresnmp, pytest, requests). A bare `python` off PATH does not. Do NOT diagnose the interpreter from process-list paths — the venv is a redirector.
- Tests: `& .venv\Scripts\python.exe -m pytest tests/ -q` from `backend/`.
- API JSON keys are camelCase.
- The `ws://<ip>/ws` socket is the device's live control plane: send ONLY `*.GetSettingsCommand` frames, NEVER a `*.Settings` frame.
- Host for the WS is always re-validated via `require_private_host` and never derived from request input.
- This feature is read-only: no DB, no models, no migrations.
- After any backend change that you run live: `Get-Process python | Stop-Process -Force` before restarting; nothing respawns them.
- CRMX² labels use the superscript-2 character `²` (²).

---

### Task 1: Dependency + pure mapping helpers

**Files:**
- Modify: `backend/requirements.txt` (append one line)
- Modify: `backend/app/integrations/stardust.py` (add constants + 3 helpers after `universes_outputting`, ~line 124)
- Test: `backend/tests/test_stardust_outputs.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `OUTPUT_LETTERS: dict[int,str]`, `_output_letter(n:int)->str`
  - `CRMX_LABELS: dict[int,dict[str,str]]`, `_crmx_label(raw:str|None, n:int)->str`
  - `_artnet_addr(v:int)->str`

- [ ] **Step 1: Add the dependency**

Append to `backend/requirements.txt`:

```
websocket-client
```

- [ ] **Step 2: Install it into the venv**

Run (from `backend/`):

```bash
& .venv\Scripts\python.exe -m pip install websocket-client
```

Expected: `Successfully installed websocket-client-…`

- [ ] **Step 3: Write the failing tests**

Create `backend/tests/test_stardust_outputs.py`:

```python
"""Stardust /ws outputs mapping — pure helpers and the settings join.

[VERIFIED 2026-07-22] Field names and the CRMX label table were mapped from the
LumenRadio GUI bundle main.7bc0d075.chunk.js in a captured HAR. The device
drives its whole UI over ws://<ip>/ws with JSON _type_ frames.
"""

from app.integrations.stardust import _output_letter, _artnet_addr, _crmx_label


def test_output_letter_maps_1_to_8():
    assert [_output_letter(n) for n in range(1, 9)] == list('ABCDEFGH')


def test_output_letter_out_of_range_is_blank():
    assert _output_letter(0) == ' '
    assert _output_letter(9) == ' '


def test_artnet_addr_decodes_net_sub_uni():
    # net=1, sub=2, uni=3 -> (1<<8)|(2<<4)|3
    assert _artnet_addr((1 << 8) | (2 << 4) | 3) == '1/2/3'
    assert _artnet_addr(0) == '0/0/0'


def test_crmx_label_full_enum_n8():
    expected = {
        'CRMX': 'CRMX Classic', 'CRMX2_1_4': '1/4 CRMX²',
        'CRMX2_2_4': '2/4 CRMX²', 'CRMX2_3_4': '3/4 CRMX²',
        'CRMX2': 'CRMX²', 'WDMX_G3': 'W-DMX G3', 'WDMX_G4S': 'W-DMX G4S',
    }
    for raw, label in expected.items():
        assert _crmx_label(raw, 8) == label


def test_crmx_label_split_varies_by_output_count():
    assert _crmx_label('CRMX2_1_4', 2) == 'CRMX²'
    assert _crmx_label('CRMX2_1_4', 4) == '1/2 CRMX²'
    assert _crmx_label('CRMX2_1_4', 6) == '1/3 CRMX²'


def test_crmx_label_unknown_falls_back():
    assert _crmx_label('CRMX', 7) == 'CRMX Classic'   # unknown N -> N=8 table
    assert _crmx_label('MYSTERY', 8) == 'MYSTERY'      # unknown raw -> verbatim
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `& .venv\Scripts\python.exe -m pytest tests/test_stardust_outputs.py -q`
Expected: FAIL with `ImportError: cannot import name '_output_letter'`

- [ ] **Step 5: Add the helpers**

In `backend/app/integrations/stardust.py`, immediately after the `universes_outputting` function (around line 124), add:

```python
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
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `& .venv\Scripts\python.exe -m pytest tests/test_stardust_outputs.py -q`
Expected: PASS (6 passed)

- [ ] **Step 7: Commit**

```bash
git add backend/requirements.txt backend/app/integrations/stardust.py backend/tests/test_stardust_outputs.py
git commit -m "Add Stardust /ws output mapping helpers + websocket-client dep"
```

---

### Task 2: `_merge_outputs` — join the three settings payloads

**Files:**
- Modify: `backend/app/integrations/stardust.py` (add `_merge_outputs` after `_crmx_label`)
- Test: `backend/tests/test_stardust_outputs.py` (append)

**Interfaces:**
- Consumes: `_output_letter`, `_artnet_addr`, `_crmx_label` (Task 1).
- Produces: `_merge_outputs(timo:dict, sacn:dict, artnet:dict) -> list[dict]`, each dict `{output:str, name:str|None, source:str, universe:str|None, crmxType:str, powerMw:int|None, enabled:bool}`, sorted by `output`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_stardust_outputs.py`:

```python
from app.integrations.stardust import _merge_outputs

TIMO = {
    'universe_nrs': [1, 2, 3, 4],
    'output_names': ['Front', 'Back', 'Spot', ''],
    'output_powers_mw': [100, 100, 30, 100],
    'rf_protocols': ['CRMX', 'CRMX', 'CRMX2_1_4', 'CRMX'],
    'enabled_universe_nrs': [1, 2, 3],
    'disabled_universe_nrs': [4],
}
# sACN map is {universe: [outputNrs]}; ArtNet map is {outputNr: addrInt}.
# JSON object keys arrive as strings; output C (3) is fed by ArtNet 0/1/5,
# output D (4) is present in the ArtNet map but null (i.e. not ArtNet).
SACN = {'universe_map': {'10': [1], '11': [2]}}
ARTNET = {'universe_map': {'3': (0 << 8) | (1 << 4) | 5, '4': None}}


def _by_output(*args):
    return {o['output']: o for o in _merge_outputs(*args)}


def test_merge_sacn_output():
    a = _by_output(TIMO, SACN, ARTNET)['A']
    assert a['source'] == 'sACN'
    assert a['universe'] == '10'
    assert a['name'] == 'Front'
    assert a['crmxType'] == 'CRMX Classic'
    assert a['powerMw'] == 100
    assert a['enabled'] is True


def test_merge_artnet_output_decodes_address():
    c = _by_output(TIMO, SACN, ARTNET)['C']
    assert c['source'] == 'ArtNet'
    assert c['universe'] == '0/1/5'
    # N = len(universe_nrs) = 4, so CRMX2_1_4 -> '1/2 CRMX²'
    assert c['crmxType'] == '1/2 CRMX²'


def test_merge_output_with_no_source_and_disabled():
    d = _by_output(TIMO, SACN, ARTNET)['D']
    assert d['source'] == 'None'
    assert d['universe'] is None
    assert d['enabled'] is False
    assert d['name'] == ''


def test_merge_sorted_by_output_letter():
    outs = _merge_outputs(TIMO, SACN, ARTNET)
    assert [o['output'] for o in outs] == ['A', 'B', 'C', 'D']
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& .venv\Scripts\python.exe -m pytest tests/test_stardust_outputs.py -q`
Expected: FAIL with `ImportError: cannot import name '_merge_outputs'`

- [ ] **Step 3: Add `_merge_outputs`**

In `backend/app/integrations/stardust.py`, after `_crmx_label`, add:

```python
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
            'name': names[i] if i < len(names) else None,
            'source': source,
            'universe': universe,
            'crmxType': _crmx_label(protocols[i] if i < len(protocols) else None, n),
            'powerMw': powers[i] if i < len(powers) else None,
            'enabled': out_nr in enabled,
        })
    outputs.sort(key=lambda o: o['output'])
    return outputs
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& .venv\Scripts\python.exe -m pytest tests/test_stardust_outputs.py -q`
Expected: PASS (10 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/integrations/stardust.py backend/tests/test_stardust_outputs.py
git commit -m "Add _merge_outputs join for Stardust per-output config"
```

---

### Task 3: WebSocket fetch + wire into `_real_status`

**Files:**
- Modify: `backend/app/integrations/stardust.py` (add `WS_TIMEOUT` near line 42; add `_ws_fetch_settings` method; edit the `_real_status` return)
- Test: `backend/tests/test_stardust_outputs.py` (append)

**Interfaces:**
- Consumes: `_merge_outputs` (Task 2), `require_private_host` (already imported), `WS_TIMEOUT`.
- Produces: `StardustAdapter._ws_fetch_settings(self, ip:str) -> tuple[dict,dict,dict]` returning `(timo, sacn, artnet)`; `_real_status` now returns `status['outputs']` (list or `None`).

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_stardust_outputs.py`:

```python
import socket as _socket

from app.integrations.stardust import StardustAdapter


class _FakeSock:
    """Stand-in for the Art-Net TOD UDP socket: no real network, no fixtures."""
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def sendto(self, *args):
        pass

    def recvfrom(self, *args):
        raise _socket.timeout()

    def close(self):
        pass


def test_real_status_attaches_outputs_from_ws():
    a = StardustAdapter(sim=False)
    node = {'ip': '10.0.1.3', 'mac': 'AA:BB:CC:DD:EE:FF', 'shortName': 'Stardust',
            'longName': 'Stardust DTx8', 'firmware': '1.0', 'via': '', 'ports': []}
    a._discover_nodes = lambda: [node]
    a._open_socket = lambda *args, **kwargs: _FakeSock()
    a._ws_fetch_settings = lambda ip: (
        {'universe_nrs': [1], 'output_names': ['X'], 'output_powers_mw': [100],
         'rf_protocols': ['CRMX'], 'enabled_universe_nrs': [1]},
        {'universe_map': {'5': [1]}},
        {'universe_map': {}},
    )
    status = a._real_status()
    assert status['available'] is True
    assert status['outputs'][0]['output'] == 'A'
    assert status['outputs'][0]['source'] == 'sACN'
    assert status['outputs'][0]['universe'] == '5'
    assert status['outputs'][0]['crmxType'] == 'CRMX Classic'


def test_real_status_outputs_none_when_ws_fails():
    a = StardustAdapter(sim=False)
    node = {'ip': '10.0.1.3', 'mac': 'AA:BB:CC:DD:EE:FF', 'shortName': 'Stardust',
            'longName': 'Stardust DTx8', 'firmware': '1.0', 'via': '', 'ports': []}
    a._discover_nodes = lambda: [node]
    a._open_socket = lambda *args, **kwargs: _FakeSock()

    def _boom(ip):
        raise OSError('ws refused')

    a._ws_fetch_settings = _boom
    status = a._real_status()
    assert status['available'] is True   # Art-Net path unaffected
    assert status['outputs'] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& .venv\Scripts\python.exe -m pytest tests/test_stardust_outputs.py -k real_status -q`
Expected: FAIL with `KeyError: 'outputs'`

- [ ] **Step 3: Add the `WS_TIMEOUT` constant**

In `backend/app/integrations/stardust.py`, just after `UNIVERSE_UNASSIGNED = 0x7FFF` (around line 42), add:

```python
WS_TIMEOUT = 2.5   # seconds; ws://<ip>/ws connect + read budget for outputs
```

- [ ] **Step 4: Add the `_ws_fetch_settings` method**

In `class StardustAdapter`, add this method (place it right before `_real_status`):

```python
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
```

- [ ] **Step 5: Wire the outputs into `_real_status`**

In `_real_status`, find the final `return { … 'fixturesDiscovered': found, }` block. Replace it with:

```python
        status = {
            'available': True, 'source': 'artnet-rdm',
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
            try:
                timo, sacn, artnet = self._ws_fetch_settings(ws_host)
                if timo.get('universe_nrs'):
                    status['outputs'] = _merge_outputs(timo, sacn, artnet)
            except Exception as exc:  # noqa: BLE001 — outputs are best-effort
                log.warning('Stardust /ws outputs fetch failed: %s', exc)
        return status
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `& .venv\Scripts\python.exe -m pytest tests/test_stardust_outputs.py -q`
Expected: PASS (12 passed)

- [ ] **Step 7: Commit**

```bash
git add backend/app/integrations/stardust.py backend/tests/test_stardust_outputs.py
git commit -m "Poll Stardust /ws for outputs config in _real_status (read-only)"
```

---

### Task 4: Simulator outputs

**Files:**
- Modify: `backend/app/integrations/stardust.py` (`_sim_status`)
- Test: `backend/tests/test_stardust_outputs.py` (append)

**Interfaces:**
- Consumes: `_merge_outputs` (Task 2).
- Produces: `_sim_status` return now includes `outputs` (list of the same per-output dicts).

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_stardust_outputs.py`:

```python
def test_sim_exposes_outputs():
    s = StardustAdapter(sim=True).get_status()
    assert s['available'] and s['source'] == 'sim'
    assert len(s['outputs']) == 8
    for o in s['outputs']:
        assert set(o) >= {'output', 'name', 'source', 'universe',
                          'crmxType', 'powerMw', 'enabled'}
    by_output = {o['output']: o for o in s['outputs']}
    assert by_output['C']['crmxType'] == '1/4 CRMX²'   # CRMX2_1_4 at N=8
    assert by_output['H']['enabled'] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& .venv\Scripts\python.exe -m pytest tests/test_stardust_outputs.py::test_sim_exposes_outputs -q`
Expected: FAIL with `KeyError: 'outputs'`

- [ ] **Step 3: Build sim outputs**

In `_sim_status`, immediately before the final `return {` statement, add:

```python
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
```

Then add `'outputs': sim_outputs,` as a key inside the `return {` dict (next to `'fixturesDiscovered': …,`).

- [ ] **Step 4: Run test to verify it passes**

Run: `& .venv\Scripts\python.exe -m pytest tests/test_stardust_outputs.py::test_sim_exposes_outputs -q`
Expected: PASS

- [ ] **Step 5: Run the full backend suite**

Run: `& .venv\Scripts\python.exe -m pytest tests/ -q`
Expected: PASS (all prior tests + 13 stardust-outputs tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/integrations/stardust.py backend/tests/test_stardust_outputs.py
git commit -m "Expose outputs config in Stardust simulator"
```

---

### Task 5: Frontend Outputs table

**Files:**
- Modify: `app/src/pages/Devices.jsx` (`StardustPanel`, after the universe grid block, ~line 337)

**Interfaces:**
- Consumes: `status.outputs` (list of `{output, name, source, universe, crmxType, powerMw, enabled}`) from Task 3/4.
- Produces: rendered Outputs table.

- [ ] **Step 1: Add the Outputs table**

In `app/src/pages/Devices.jsx`, in `StardustPanel`, find the universe grid block that ends the `status.universes?.map(...)` grid (the `<div className="grid grid-cols-4 gap-1.5">…</div>`). Immediately AFTER that closing `</div>`, and BEFORE the `{status.universes?.some((u) => u.fixtures.length > 0) && (` RDM-discovery block, insert:

```jsx
      {status.outputs?.length > 0 && (
        <div>
          <div className="text-[8px] text-text-muted uppercase tracking-widest mb-1">Outputs — source, universe &amp; CRMX type</div>
          <table className="w-full text-[9px] font-mono">
            <thead>
              <tr className="text-text-muted text-left text-[7px] uppercase tracking-widest">
                <th className="font-normal py-0.5">Output</th><th className="font-normal">Name</th>
                <th className="font-normal">Source</th><th className="font-normal">Universe/Addr</th>
                <th className="font-normal">CRMX Type</th><th className="font-normal">Power</th>
              </tr>
            </thead>
            <tbody>
              {status.outputs.map((o) => (
                <tr key={o.output} className={'border-t border-[var(--color-surface)] ' + (o.enabled ? '' : 'opacity-40')}>
                  <td className="py-0.5 text-text">{o.output}</td>
                  <td className="text-text-muted">{o.name || '—'}</td>
                  <td className="text-text-muted">{o.source}</td>
                  <td className="text-text-muted">{o.universe ?? '—'}</td>
                  <td className="text-text-muted">{o.crmxType || '—'}</td>
                  <td className="text-text-muted">{o.powerMw != null ? o.powerMw + ' mW' : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
```

- [ ] **Step 2: Verify it renders in sim**

Run the frontend + backend (see `docs/network-state.md`), open the Devices page with SIM MODE on, and confirm the Stardust panel shows an Outputs table with rows A–H, mixed sACN/ArtNet sources, CRMX²/W-DMX types, and output H dimmed (disabled).

Alternatively (no browser), confirm the sim payload shape:

```bash
& .venv\Scripts\python.exe -c "from app.integrations.stardust import StardustAdapter; import json; print(json.dumps(StardustAdapter(sim=True).get_status()['outputs'], indent=2))"
```

Expected: 8 objects with `output` A–H and the six fields populated.

- [ ] **Step 3: Commit**

```bash
git add app/src/pages/Devices.jsx
git commit -m "Add Outputs table to Stardust panel (source, universe, CRMX type)"
```

---

## Live verification (after Task 5)

1. `Get-Process python | Stop-Process -Force`
2. Start the backend with the venv (see `docs/network-state.md`).
3. Query the real unit:

```bash
Invoke-RestMethod -Uri 'http://127.0.0.1:5000/api/devices/stardust/status' -TimeoutSec 8 | Select-Object -ExpandProperty outputs
```

Expected: per-output rows with real source/universe/crmxType. If `outputs` is null, the WS host wasn't reachable — set `FIVE12_STARDUST_HOST=10.0.1.3` in `backend/.env` and retry. The panel keeps working from Art-Net data regardless.

## Self-review notes

- **Spec coverage:** WS frames + parse (T3), CRMX table + address decode + output letter (T1), `_merge_outputs` join incl. sACN/ArtNet/None + disabled (T2), `_real_status` wiring + graceful `outputs=None` (T3), simulator (T4), frontend table (T5), `websocket-client` dependency (T1). Read-only stance enforced in T3 (`_ws_fetch_settings` sends only the three Get frames).
- **Types consistent:** `_merge_outputs(timo, sacn, artnet)` and the per-output dict keys (`output, name, source, universe, crmxType, powerMw, enabled`) are identical in T2, T3, T4, and the T5 JSX.
