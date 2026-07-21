"""Per-subnet "remove offline devices" — a soft hide, never a delete.

Operator intent: "the red ones go away, but if it plugs back in it should have
all the same notes and labels applied to it." Persistence is keyed on MAC, so
hiding a row and un-hiding it on the next sighting preserves everything the
operator typed. Deleting would not.
"""

from datetime import datetime, timedelta

import pytest

import app.vendors as vendors
from app.models import NetworkSubnet, NetworkDevice
from app.scanner import OFFLINE_THRESHOLD, _process_discovered_device


def _seen(seconds_ago):
    return datetime.utcnow() - timedelta(seconds=seconds_ago)


@pytest.fixture
def subnet(db):
    """A committed subnet plus cleanup — route tests need real commits."""
    row = NetworkSubnet(label='Management', cidr='172.16.0.0/16')
    db.session.add(row)
    db.session.commit()
    yield row
    NetworkDevice.query.filter_by(subnet_id=row.id).delete()
    db.session.delete(row)
    db.session.commit()


def _device(db, mac, subnet_id, seen_secs_ago, **kw):
    row = NetworkDevice(mac_address=mac, subnet_id=subnet_id,
                        last_seen=None if seen_secs_ago is None
                        else _seen(seen_secs_ago), **kw)
    db.session.add(row)
    db.session.commit()
    return row


def test_offline_threshold_matches_the_ui():
    """NetworkMonitor.jsx paints a device red at 90s. If the backend disagrees
    the button clears a different set than the operator can see."""
    assert OFFLINE_THRESHOLD == timedelta(seconds=90)


def test_device_reports_hidden(db):
    device = NetworkDevice(mac_address='AA:BB:CC:00:00:01')
    db.session.add(device)
    db.session.flush()
    assert device.to_dict()['hidden'] is False


def test_clear_offline_hides_offline_devices(client, db, subnet):
    _device(db, 'AA:BB:CC:00:00:02', subnet.id, 300)
    res = client.post(f'/api/network/subnets/{subnet.id}/clear-offline')
    assert res.status_code == 200
    assert res.get_json()['hidden'] == 1
    assert db.session.get(NetworkDevice, 'AA:BB:CC:00:00:02').hidden is True


def test_clear_offline_leaves_online_devices_alone(client, db, subnet):
    _device(db, 'AA:BB:CC:00:00:03', subnet.id, 10)
    res = client.post(f'/api/network/subnets/{subnet.id}/clear-offline')
    assert res.get_json()['hidden'] == 0
    assert db.session.get(NetworkDevice, 'AA:BB:CC:00:00:03').hidden is False


def test_never_seen_device_counts_as_offline(client, db, subnet):
    _device(db, 'AA:BB:CC:00:00:04', subnet.id, None)
    client.post(f'/api/network/subnets/{subnet.id}/clear-offline')
    assert db.session.get(NetworkDevice, 'AA:BB:CC:00:00:04').hidden is True


def test_clear_offline_is_scoped_to_one_subnet(client, db, subnet):
    other = NetworkSubnet(label='sACN', cidr='10.0.0.0/8')
    db.session.add(other)
    db.session.commit()
    _device(db, 'AA:BB:CC:00:00:05', other.id, 300)
    try:
        res = client.post(f'/api/network/subnets/{subnet.id}/clear-offline')
        assert res.get_json()['hidden'] == 0
        assert db.session.get(NetworkDevice, 'AA:BB:CC:00:00:05').hidden is False
    finally:
        NetworkDevice.query.filter_by(subnet_id=other.id).delete()
        db.session.delete(other)
        db.session.commit()


def test_hiding_preserves_label_and_notes(client, db, subnet):
    """The whole reason this is a hide and not a delete."""
    _device(db, 'AA:BB:CC:00:00:06', subnet.id, 300,
            label='Netgear SR1 Rack', notes='port 7 flaky')
    client.post(f'/api/network/subnets/{subnet.id}/clear-offline')
    row = db.session.get(NetworkDevice, 'AA:BB:CC:00:00:06')
    assert row.hidden is True
    assert row.label == 'Netgear SR1 Rack'
    assert row.notes == 'port 7 flaky'


def test_clear_offline_on_unknown_subnet_is_404(client):
    assert client.post('/api/network/subnets/99999/clear-offline').status_code == 404


def test_list_devices_omits_hidden(client, db, subnet):
    _device(db, 'AA:BB:CC:00:00:07', subnet.id, 10)
    _device(db, 'AA:BB:CC:00:00:08', subnet.id, 300, hidden=True)
    macs = [d['macAddress'] for d in client.get('/api/network/devices').get_json()]
    assert 'AA:BB:CC:00:00:07' in macs
    assert 'AA:BB:CC:00:00:08' not in macs


def test_list_devices_can_include_hidden(client, db, subnet):
    _device(db, 'AA:BB:CC:00:00:09', subnet.id, 300, hidden=True)
    res = client.get('/api/network/devices?includeHidden=1')
    macs = [d['macAddress'] for d in res.get_json()]
    assert 'AA:BB:CC:00:00:09' in macs


def test_a_returning_device_reappears_with_its_label(app, db, subnet, monkeypatch):
    """A hidden device that plugs back in must come back — with everything the
    operator typed on it still attached."""
    monkeypatch.setattr(vendors, 'detect_vendor_type', lambda mac: 'netgear')
    monkeypatch.setattr(vendors, 'enrich_device', lambda ip, mac, t: {})
    _device(db, 'AA:BB:CC:00:00:0A', subnet.id, 300,
            hidden=True, label='Netgear SR1 Rack', notes='port 7 flaky')

    _process_discovered_device('172.16.3.97', 'AA:BB:CC:00:00:0A',
                               subnet.id, app)

    row = db.session.get(NetworkDevice, 'AA:BB:CC:00:00:0A')
    db.session.refresh(row)
    assert row.hidden is False
    assert row.label == 'Netgear SR1 Rack'
    assert row.notes == 'port 7 flaky'
