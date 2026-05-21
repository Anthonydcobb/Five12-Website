from app.models import NetworkSubnet, NetworkDevice, LocationSnapshot, LocationDevice
from datetime import datetime


def test_subnet_to_dict(db):
    subnet = NetworkSubnet(label='Management', cidr='192.168.10.0/24', color='#7dd3fc')
    db.session.add(subnet)
    db.session.flush()
    d = subnet.to_dict()
    assert d['label'] == 'Management'
    assert d['cidr'] == '192.168.10.0/24'
    assert d['active'] is True
    assert d['interfaceHint'] is None


def test_device_to_dict(db):
    device = NetworkDevice(
        mac_address='AA:BB:CC:DD:EE:FF',
        device_type='luminex',
        last_ip='192.168.10.5',
        last_seen=datetime(2026, 5, 21, 12, 0, 0),
    )
    db.session.add(device)
    db.session.flush()
    d = device.to_dict()
    assert d['macAddress'] == 'AA:BB:CC:DD:EE:FF'
    assert d['deviceType'] == 'luminex'
    assert d['lastIp'] == '192.168.10.5'
    assert '2026-05-21' in d['lastSeen']
    assert d['notes'] is None


def test_location_snapshot_with_devices(db):
    snap = LocationSnapshot(name='Warner Bros Lot 3')
    db.session.add(snap)
    db.session.flush()
    ld = LocationDevice(
        location_id=snap.id,
        mac_address='AA:BB:CC:DD:EE:FF',
        ip_at_time='192.168.10.5',
        online_at_time=True,
    )
    db.session.add(ld)
    db.session.flush()
    d = snap.to_dict()
    assert d['name'] == 'Warner Bros Lot 3'
    assert d['deviceCount'] == 1
    ld_dict = ld.to_dict()
    assert ld_dict['macAddress'] == 'AA:BB:CC:DD:EE:FF'
    assert ld_dict['onlineAtTime'] is True
