"""The scan service filters what bleak reports and feeds the registry.

handle_advertisement is pure with respect to bleak — it takes plain values, so
the whole filter/decode/store path is testable with no radio and no event loop.
"""

from app.five12_ble import constants as c
from app.five12_ble.scanner import BleScanService

TIMOTWO_UUIDS = [c.TIMOTWO_SERVICE_UUID]
MFR = {0xFFFF: bytes.fromhex('03F14000004C55F140')}


def test_timotwo_advertisement_is_recorded():
    svc = BleScanService()
    svc.handle_advertisement('os-1', 'F12L - 1946', -41, TIMOTWO_UUIDS, MFR, now=100.0)
    assert svc.registry.count() == 1
    assert svc.registry.get('os-1').local_name == 'F12L - 1946'


def test_unrelated_ble_device_is_ignored():
    """A room full of phones, headphones, and laptops must not fill the roster."""
    svc = BleScanService()
    svc.handle_advertisement('os-phone', 'Someones iPhone', -55,
                             ['0000180f-0000-1000-8000-00805f9b34fb'],
                             {0x004C: b'\x01\x02'}, now=100.0)
    assert svc.registry.count() == 0


def test_manufacturer_data_alone_is_enough_evidence():
    """Some stacks drop service UUIDs from the advertisement; matching
    manufacturer data still identifies the platform."""
    svc = BleScanService()
    svc.handle_advertisement('os-1', 'F12L - 1946', -41, [], MFR, now=100.0)
    assert svc.registry.count() == 1


def test_service_uuid_alone_is_enough_evidence():
    svc = BleScanService()
    svc.handle_advertisement('os-1', 'F12L - 1946', -41, TIMOTWO_UUIDS, {}, now=100.0)
    assert svc.registry.count() == 1
    assert 'service-uuid' in svc.registry.get('os-1').advert['evidence']


def test_uppercase_service_uuid_still_matches():
    svc = BleScanService()
    svc.handle_advertisement('os-1', 'n', -41,
                             [c.TIMOTWO_SERVICE_UUID.upper()], {}, now=100.0)
    assert svc.registry.count() == 1


def test_malformed_manufacturer_data_does_not_raise():
    svc = BleScanService()
    svc.handle_advertisement('os-1', 'n', -41, TIMOTWO_UUIDS, {0xFFFF: b'\x03'}, now=100.0)
    assert svc.registry.count() == 1
    assert svc.registry.get('os-1').advert['hardwareId'] is None


def test_repeat_advertisements_coalesce():
    svc = BleScanService()
    for i in range(10):
        svc.handle_advertisement('os-1', 'n', -50, TIMOTWO_UUIDS, MFR, now=100.0 + i)
    assert svc.registry.count() == 1


def test_sim_service_populates_registry_without_hardware():
    svc = BleScanService(sim=True)
    svc.poll_sim(now=100.0)
    assert svc.registry.count() == 2
    assert svc.status()['sim'] is True


def test_status_reports_not_running_before_start():
    svc = BleScanService()
    st = svc.status()
    assert st['running'] is False
    assert st['deviceCount'] == 0


def test_sim_status_reports_adapter_available():
    """Sim mode must never claim it needs hardware, or the panel shows a
    hardware error during a demo."""
    svc = BleScanService(sim=True)
    assert svc.status()['adapterAvailable'] is True
