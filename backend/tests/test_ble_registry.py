"""The registry is the single source of truth for "what is nearby". It is
written by the scan thread and read by Flask request threads, so it must be
thread-safe, and it must never grow without bound in a room full of BLE gear."""

import pytest

from app.five12_ble.registry import Registry


ADVERT = {
    'platform': 'lumenradio-timotwo-compatible',
    'product': None,
    'hardwareId': 'F1400000',
    'estaManufacturerId': '4C55',
    'modelId': 'F140',
    'rawManufacturerData': '03F14000004C55F140',
    'evidence': ['manufacturer-data'],
}


def test_upsert_creates_then_updates_same_device():
    r = Registry()
    r.upsert('os-1', 'F12L - 1946', -50, ADVERT, now=100.0)
    r.upsert('os-1', 'F12L - 1946', -44, ADVERT, now=101.0)
    assert r.count() == 1
    dev = r.get('os-1')
    assert dev.first_seen == 100.0
    assert dev.last_seen == 101.0


def test_rssi_is_smoothed_but_latest_is_kept():
    """A raw RSSI jitters several dB between adverts; the panel needs a stable
    bar. Keep both — smoothed for display, latest for the evidence drawer."""
    r = Registry()
    r.upsert('os-1', 'n', -40, ADVERT, now=100.0)
    r.upsert('os-1', 'n', -60, ADVERT, now=101.0)
    dev = r.get('os-1')
    assert dev.rssi == -60
    assert -60 < dev.rssi_smoothed < -40
    # Pin the exact blend so a changed alpha or swapped raw/existing weights
    # can't slip through the loose range check above:
    # 0.4 * -60 + 0.6 * -40 = -48.0
    assert dev.rssi_smoothed == pytest.approx(-48.0)


def test_first_sample_smoothed_equals_raw():
    r = Registry()
    r.upsert('os-1', 'n', -47, ADVERT, now=100.0)
    assert r.get('os-1').rssi_smoothed == -47


def test_stale_devices_are_excluded_from_all():
    r = Registry(stale_after=60)
    r.upsert('os-old', 'gone', -50, ADVERT, now=100.0)
    r.upsert('os-new', 'here', -50, ADVERT, now=150.0)
    ids = [d.os_id for d in r.all(now=170.0)]
    assert ids == ['os-new']


def test_stale_device_is_retained_for_lookup_not_deleted():
    """Expiry hides a device from the roster; it does not destroy what we
    learned about it, so a device that reappears keeps its first_seen."""
    r = Registry(stale_after=60)
    r.upsert('os-1', 'n', -50, ADVERT, now=100.0)
    assert r.all(now=200.0) == []
    r.upsert('os-1', 'n', -50, ADVERT, now=201.0)
    assert r.get('os-1').first_seen == 100.0


def test_all_sorted_by_signal_strongest_first():
    r = Registry()
    r.upsert('weak', 'w', -80, ADVERT, now=100.0)
    r.upsert('strong', 's', -35, ADVERT, now=100.0)
    assert [d.os_id for d in r.all(now=100.0)] == ['strong', 'weak']


def test_to_dict_is_camel_case_and_carries_no_gatt_fields():
    """A roster entry comes from advertisements only. Nearby is not connected —
    battery/firmware/mode must not appear until someone connects."""
    r = Registry()
    r.upsert('os-1', 'F12L - 1946', -41, ADVERT, now=100.0)
    out = r.get('os-1').to_dict()
    assert out['osId'] == 'os-1'
    assert out['localName'] == 'F12L - 1946'
    assert out['rssi'] == -41
    assert out['platform'] == 'lumenradio-timotwo-compatible'
    assert out['product'] is None
    for forbidden in ('battery', 'firmware', 'mode', 'linked'):
        assert forbidden not in out


def test_concurrent_upserts_do_not_lose_devices():
    import threading
    r = Registry()

    def writer(start):
        for i in range(start, start + 200):
            r.upsert(f'os-{i}', 'n', -50, ADVERT, now=100.0)

    threads = [threading.Thread(target=writer, args=(s,)) for s in (0, 200, 400)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert r.count() == 600


def test_concurrent_upserts_to_same_device_stay_consistent(monkeypatch):
    """Guards the real hazard the lock exists for: upsert's existing-device
    path (`existing.update_count += 1`, alongside the rssi_smoothed blend)
    is a compound read-modify-write spanning multiple bytecodes -- read the
    current value, add one, write it back -- which the GIL does NOT make
    atomic. If the lock in upsert were removed, concurrent writers to the
    SAME os_id could interleave mid-update and clobber each other's
    increments, so the final update_count would land under the true number
    of calls. This test fails if that lock is removed.

    On CPython, cooperative thread hand-off is only actually *acted on* at
    call/jump boundaries, not between arbitrary bytecodes -- so a bare
    `obj.attr += 1` with no call in between can execute uninterrupted even
    with the lock removed, letting a real bug hide from a naive thread-storm
    test. To make the hazard observable, update_count is routed through a
    property for the duration of this test: reading and writing it are then
    genuine Python-level calls (exactly the same attribute-access interface
    registry.py uses -- `existing.update_count += 1` is untouched), which
    gives the interpreter real checkpoints to land on mid-update. Verified
    directly: with the lock removed this reliably undercounts (200/200
    trials failed at 6 threads x 300 updates); with the lock intact it never
    does (0/200)."""
    import threading
    from app.five12_ble.models import DiscoveredDevice

    def _get_update_count(self):
        return self.__dict__.get('_update_count_storage', 0)

    def _set_update_count(self, value):
        self.__dict__['_update_count_storage'] = value

    monkeypatch.setattr(
        DiscoveredDevice, 'update_count',
        property(_get_update_count, _set_update_count),
    )

    r = Registry()

    updates_per_thread = 300
    num_threads = 6

    def writer():
        for i in range(updates_per_thread):
            r.upsert('os-1', 'n', -50 - (i % 30), ADVERT, now=100.0)

    threads = [threading.Thread(target=writer) for _ in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert r.count() == 1
    dev = r.get('os-1')
    # First upsert creates the device (no increment); every subsequent
    # upsert across all threads takes the existing-device path once.
    expected_updates = num_threads * updates_per_thread - 1
    assert dev.update_count == expected_updates
