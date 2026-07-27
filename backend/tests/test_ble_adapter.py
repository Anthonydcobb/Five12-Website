"""CintennaAdapter is the bridge between the BLE service and the existing
Devices page. Adding it to ALL_DEVICE_IDS is what makes the tab render."""

from app.integrations import ALL_DEVICE_IDS, get_adapter
from app.integrations.cintenna import CintennaAdapter
from app.five12_ble.errors import NotOwner


def test_cintenna_is_a_known_device_id():
    assert 'cintenna' in ALL_DEVICE_IDS


def test_get_adapter_returns_cintenna():
    adapter = get_adapter('cintenna', sim=True)
    assert isinstance(adapter, CintennaAdapter)
    assert adapter.id == 'cintenna'


def test_adapter_is_cached_per_sim_flag():
    assert get_adapter('cintenna', sim=True) is get_adapter('cintenna', sim=True)
    assert get_adapter('cintenna', sim=True) is not get_adapter('cintenna', sim=False)


def test_detect_reports_found_in_sim_with_device_count():
    adapter = get_adapter('cintenna', sim=True)
    adapter.service.poll_sim()
    det = adapter.detect()
    assert det['found'] is True
    assert '2' in det['detail']


def test_status_lists_devices_and_is_camel_case():
    adapter = get_adapter('cintenna', sim=True)
    adapter.service.poll_sim()
    status = adapter.get_status()
    assert status['available'] is True
    assert 'alerts' in status
    assert len(status['devices']) == 2
    assert 'osId' in status['devices'][0]


def test_status_devices_carry_no_gatt_fields():
    """The roster is advertisement-only. Nearby is not connected."""
    adapter = get_adapter('cintenna', sim=True)
    adapter.service.poll_sim()
    for dev in adapter.get_status()['devices']:
        for forbidden in ('battery', 'firmware', 'mode', 'linked'):
            assert forbidden not in dev


def test_devices_route_includes_cintenna(client):
    """The whole point: GET /api/devices must return a cintenna entry, because
    Devices.jsx renders its tab strip from that response."""
    resp = client.get('/api/devices?sim=1')
    assert resp.status_code == 200
    ids = [d['id'] for d in resp.get_json()]
    assert 'cintenna' in ids


def test_devices_route_cintenna_entry_shape(client):
    entry = next(d for d in client.get('/api/devices?sim=1').get_json()
                 if d['id'] == 'cintenna')
    assert entry['name']
    assert 'found' in entry
    assert 'detail' in entry


# ── detect() branch coverage ──────────────────────────────────────────────
#
# BleScanService.__init__ sets _adapter_available = sim, so for a real (non-
# sim) service it starts False and only flips True from inside the running
# scan loop. start() sets lastError to 'not-owner' or
# 'lock-mechanism-unavailable' BEFORE that loop ever runs. detect() must
# therefore check lastError ahead of adapterAvailable, or the ownership/
# lock-mechanism messages are unreachable exactly when they matter.
#
# These construct state by setting the BleScanService's private attributes
# directly, per the task's own suggestion — there is no production code
# whose only purpose is enabling this.

def test_detect_reports_no_adapter_when_really_unavailable(app, monkeypatch):
    # Gate ON, adapter still unavailable — genuinely missing hardware, as
    # opposed to the feature simply being switched off (see the disabled-gate
    # test below, added for Finding 1).
    monkeypatch.setitem(app.config, 'ENABLE_BLE_TOOLS', True)
    adapter = get_adapter('cintenna', sim=False)
    adapter.service._adapter_available = False
    adapter.service._last_error = None
    adapter.service._running = False

    with app.app_context():
        det = adapter.detect()
    assert det['found'] is False
    assert det['detail'] == 'no Bluetooth adapter'


def test_detect_reports_disabled_not_missing_when_gate_is_off(monkeypatch):
    """Regression test for Finding 1: with the feature gate off, the scan
    loop never runs and the adapter is never actually probed, so detect()
    must not claim the operator's hardware is missing."""
    monkeypatch.delenv('FIVE12_BLE_TOOLS', raising=False)
    adapter = get_adapter('cintenna', sim=False)
    adapter.service._adapter_available = False
    adapter.service._last_error = None
    adapter.service._running = False

    det = adapter.detect()
    assert det['found'] is False
    assert det['detail'] == 'BLE tools disabled'


def test_detect_reports_not_owner_before_adapter_available_flips_true():
    """Regression test for the Finding 1 bug: a losing gunicorn worker has
    adapterAvailable=False (it never got to run the loop) AND
    lastError='not-owner'. The ownership message must win, not the generic
    'no Bluetooth adapter' message that would mislead the operator into
    thinking their hardware is missing."""
    adapter = get_adapter('cintenna', sim=False)
    adapter.service._adapter_available = False
    adapter.service._last_error = 'not-owner'
    adapter.service._running = False

    det = adapter.detect()
    assert det['found'] is False
    assert det['detail'] == NotOwner().operator_message


def test_detect_reports_lock_mechanism_unavailable_distinctly():
    """The second lastError start() can set — no OS locking primitive on
    this platform — must get its own honest text, not be folded into the
    not-owner message."""
    adapter = get_adapter('cintenna', sim=False)
    adapter.service._adapter_available = False
    adapter.service._last_error = 'lock-mechanism-unavailable'
    adapter.service._running = False

    det = adapter.detect()
    assert det['found'] is False
    assert det['detail'] != 'another Five12 process owns the adapter'
    assert det['detail'] != 'no Bluetooth adapter'
    assert 'lock' in det['detail'].lower()


def test_detect_scanning_with_zero_devices_says_so():
    adapter = get_adapter('cintenna', sim=False)
    adapter.service._adapter_available = True
    adapter.service._last_error = None
    adapter.service._running = True

    det = adapter.detect()
    assert det['found'] is False
    assert 'scanning' in det['detail']
    assert 'none' in det['detail']


def test_detect_not_scanning_with_zero_devices_says_so():
    adapter = get_adapter('cintenna', sim=False)
    adapter.service._adapter_available = True
    adapter.service._last_error = None
    adapter.service._running = False

    det = adapter.detect()
    assert det['found'] is False
    assert det['detail'] == 'not scanning'


def test_get_status_populates_history():
    adapter = get_adapter('cintenna', sim=True)
    adapter.service.poll_sim()

    adapter.get_status()

    hist = adapter.get_history()
    assert len(hist) >= 1
    sample = hist[-1]
    assert 'deviceCount' in sample
    assert 'scanning' in sample
    assert 'available' in sample
    # passive roster only — no per-device or GATT fields belong in history
    assert 'devices' not in sample
    assert 'battery' not in sample
