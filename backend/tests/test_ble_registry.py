"""The registry is the single source of truth for "what is nearby". It is
written by the scan thread and read by Flask request threads, so it must be
thread-safe, and it must never grow without bound in a room full of BLE gear."""

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
