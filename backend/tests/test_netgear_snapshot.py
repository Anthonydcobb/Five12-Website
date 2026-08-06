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
