"""Live per-port read with a cached fallback.

The universe on a port changes exactly when somebody is standing at the node
repatching it, and enrichment only runs on the 300s discovery sweep. A table
that is five minutes behind is wrong at the one moment it is being read, so
this route re-reads the node on demand — but keeps showing the last known
patch when the node has gone away, rather than blanking.
"""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app.models import NetworkDevice, _utc_iso


PORTS = [
    {'port': 1, 'universe': 21, 'protocol': 'sACN', 'direction': 'Output', 'status': 'OK'},
    {'port': 2, 'universe': 42, 'protocol': 'sACN', 'direction': 'Output', 'status': 'OK'},
]


# The sweep stamps the patch when /model/status answered. It is deliberately
# much older than last_seen below: last_seen is refreshed every 20s by the ICMP
# keep-alive, which does not enrich, so the two genuinely diverge on a node
# that pings but will not serve HTTP.
STORED_AS_OF = '2026-08-05T18:00:00Z'


@pytest.fixture
def node(db):
    row = NetworkDevice(
        mac_address='28:36:38:C0:39:C0',
        device_type='swisson',
        last_ip='10.31.8.51',
        last_seen=datetime.utcnow() - timedelta(seconds=30),
        vendor_data={'model': 'XND-8', 'ports': PORTS, 'portsAsOf': STORED_AS_OF},
    )
    db.session.add(row)
    db.session.commit()
    yield row
    db.session.delete(row)
    db.session.commit()


def test_a_reachable_node_is_read_live(client, node):
    fresh = [dict(PORTS[0], universe=77), PORTS[1]]
    with patch('app.vendors.read_port_status', return_value={'ports': fresh}):
        res = client.get(f'/api/network/devices/{node.mac_address}/ports')

    assert res.status_code == 200
    body = res.get_json()
    assert body['live'] is True
    assert body['ports'][0]['universe'] == 77


def test_a_live_read_reports_asof_as_now(client, node):
    """The contract is {'ports', 'live', 'asOf'} on every response. A live
    read has a well-defined 'as of': the moment it was just taken. Consumers
    should never see the field vanish on this branch while the fallback
    branch sends null for the equivalent 'no timestamp' case."""
    fresh = [dict(PORTS[0], universe=77), PORTS[1]]
    with patch('app.vendors.read_port_status', return_value={'ports': fresh}):
        res = client.get(f'/api/network/devices/{node.mac_address}/ports')

    body = res.get_json()
    assert 'asOf' in body
    assert body['asOf'] is not None
    assert body['asOf'].endswith('Z')


def test_a_live_read_does_not_overwrite_stored_vendor_data(client, db, node):
    """Read path only. A live value disagreeing with the sweep is not evidence
    the sweep was wrong, and writing here would race the scanner."""
    fresh = [dict(PORTS[0], universe=77), PORTS[1]]
    with patch('app.vendors.read_port_status', return_value={'ports': fresh}):
        client.get(f'/api/network/devices/{node.mac_address}/ports')

    db.session.refresh(node)
    assert node.vendor_data['ports'][0]['universe'] == 21


def test_a_live_read_never_commits(client, db, node):
    """The stronger version of the invariant above: this route runs against a
    row the scanner sweep is concurrently updating, so it must never write or
    commit at all, not just leave one field untouched. A later 'helpful'
    addition — e.g. bumping last_seen on a successful probe — would race the
    scanner and must fail this test even though it wouldn't touch vendor_data.
    """
    fresh = [dict(PORTS[0], universe=77), PORTS[1]]
    with patch('app.vendors.read_port_status', return_value={'ports': fresh}), \
            patch.object(db.session, 'commit') as mock_commit:
        res = client.get(f'/api/network/devices/{node.mac_address}/ports')

    assert res.status_code == 200
    mock_commit.assert_not_called()


def test_an_unreachable_node_falls_back_to_the_stored_patch(client, node):
    """The last known patch is still useful — better than an empty panel."""
    with patch('app.vendors.read_port_status', return_value={}):
        res = client.get(f'/api/network/devices/{node.mac_address}/ports')

    body = res.get_json()
    assert body['live'] is False
    assert body['ports'][0]['universe'] == 21
    assert body['asOf'].endswith('Z')


def test_the_fallback_asof_is_the_patch_read_not_the_last_ping(client, node):
    """The provenance of the PATCH, not of the ping.

    `last_seen` is refreshed every 20s by quick_reprobe, which explicitly does
    not enrich. A node whose HTTP stack is wedged (crashed web server, TCP/80
    ACL change, mid-reboot) but which still answers ping keeps advancing
    last_seen while the patch stays frozen — so reporting last_seen here
    rendered an hours-old patch as "as of 10s ago", and somebody can repatch
    that node from its front panel inside that window.
    """
    with patch('app.vendors.read_port_status', return_value={}):
        res = client.get(f'/api/network/devices/{node.mac_address}/ports')

    body = res.get_json()
    assert body['asOf'] == STORED_AS_OF
    # last_seen is 30s old; the stored patch is from August 5th. If those two
    # were ever conflated again this assertion is the one that fires.
    assert body['asOf'] != _utc_iso(node.last_seen)


def test_a_row_swept_before_portsasof_existed_reports_no_time(client, db):
    """No migration: rows written before the timestamp existed simply have
    none. `None` is honest — the panel degrades to "time unknown" — where
    borrowing last_seen would invent a provenance the row does not have."""
    row = NetworkDevice(mac_address='AA:BB:CC:00:00:0B', last_ip='10.0.0.11',
                        last_seen=datetime.utcnow(),
                        vendor_data={'model': 'XND-8', 'ports': PORTS})
    db.session.add(row)
    db.session.commit()
    try:
        with patch('app.vendors.read_port_status', return_value={}):
            res = client.get('/api/network/devices/AA:BB:CC:00:00:0B/ports')

        body = res.get_json()
        assert body['ports'][0]['universe'] == 21   # the patch still shows
        assert body['asOf'] is None
    finally:
        db.session.delete(row)
        db.session.commit()


def test_an_unreachable_node_with_nothing_stored_returns_an_empty_list(client, db):
    row = NetworkDevice(mac_address='AA:BB:CC:00:00:09', last_ip='10.0.0.9')
    db.session.add(row)
    db.session.commit()
    try:
        with patch('app.vendors.read_port_status', return_value={}):
            res = client.get('/api/network/devices/AA:BB:CC:00:00:09/ports')
        assert res.status_code == 200
        assert res.get_json() == {'ports': [], 'live': False, 'asOf': None}
    finally:
        db.session.delete(row)
        db.session.commit()


def test_a_device_with_no_ip_is_not_probed(client, db):
    """Never call requests.get(None) — a device known only by MAC has no
    address to read."""
    row = NetworkDevice(mac_address='AA:BB:CC:00:00:0A', vendor_data={'ports': PORTS})
    db.session.add(row)
    db.session.commit()
    try:
        with patch('app.vendors.read_port_status') as reader:
            res = client.get('/api/network/devices/AA:BB:CC:00:00:0A/ports')
        reader.assert_not_called()
        assert res.get_json()['live'] is False
        assert res.get_json()['ports'][0]['universe'] == 21
    finally:
        db.session.delete(row)
        db.session.commit()


def test_an_unknown_mac_is_404(client):
    res = client.get('/api/network/devices/FF:FF:FF:FF:FF:FF/ports')
    assert res.status_code == 404
