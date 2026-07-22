"""Keep-alive re-probe: real gear must not flap offline between discovery passes.

[Root cause] "Online" is `last_seen` within OFFLINE_THRESHOLD (90s), but the wide
discovery sweep revisits any given device only once per full pass — measured ~165s
on the rig (a /8 + two /16s + SNMP retries). So every device sawtoothed across the
90s line and flapped offline/online, even though the gear was fine.

`quick_reprobe` refreshes `last_seen` for already-known devices every ~20s, cheaply
(exact-IP pings + the OS ARP cache, no scapy sweep and no SNMP enrichment), so
present gear stays comfortably under the threshold between the slow discovery
passes. See docs/handoff-2026-07-22-network-monitor-flap.md.
"""

from datetime import datetime, timedelta

import pytest

import app.scanner as scanner
from app.scanner import quick_reprobe, OFFLINE_THRESHOLD
from app.models import NetworkDevice


KNOWN_MAC = 'AA:BB:CC:DD:00:01'
KNOWN_IP = '172.31.0.4'


@pytest.fixture
def cleanup(db):
    """Rows are committed to the session-scoped in-memory DB, so clean them up."""
    yield
    NetworkDevice.query.filter(
        NetworkDevice.mac_address.like('AA:BB:CC:DD:%')).delete(
        synchronize_session=False)
    db.session.commit()


def _add(db, mac, ip, seen_secs_ago, **kw):
    row = NetworkDevice(
        mac_address=mac, last_ip=ip,
        last_seen=datetime.utcnow() - timedelta(seconds=seen_secs_ago), **kw)
    db.session.add(row)
    db.session.commit()
    return row


def _no_ping(monkeypatch):
    monkeypatch.setattr(scanner, '_ping_hosts', lambda ips: None)


def test_reprobe_refreshes_a_stale_but_present_device(app, db, monkeypatch, cleanup):
    """A device aged past the offline threshold that still answers ARP is pulled
    back online — its last_seen jumps to now."""
    _no_ping(monkeypatch)
    _add(db, KNOWN_MAC, KNOWN_IP, 130)          # 130s > 90s: showing offline
    monkeypatch.setattr(scanner, '_arp_fallback',
                        lambda cidr: [(KNOWN_IP, KNOWN_MAC)])

    n = quick_reprobe(app)

    assert n == 1
    row = db.session.get(NetworkDevice, KNOWN_MAC)
    db.session.refresh(row)
    age = (datetime.utcnow() - row.last_seen).total_seconds()
    assert age < OFFLINE_THRESHOLD.total_seconds()   # now online
    assert age < 5                                   # essentially just-now


def test_reprobe_does_not_create_unknown_devices(app, db, monkeypatch, cleanup):
    """Discovery of NEW MACs is the slow pass's job. A MAC the keep-alive has
    never seen in the table is left alone — no blank rows, no enrichment."""
    _no_ping(monkeypatch)
    _add(db, KNOWN_MAC, KNOWN_IP, 130)          # something known, so we do probe
    monkeypatch.setattr(scanner, '_arp_fallback',
                        lambda cidr: [(KNOWN_IP, KNOWN_MAC),
                                      ('10.0.0.99', 'AA:BB:CC:DD:00:FF')])

    n = quick_reprobe(app)

    assert n == 1                                # only the known one
    assert db.session.get(NetworkDevice, 'AA:BB:CC:DD:00:FF') is None


def test_reprobe_skips_all_io_when_nothing_known(app, db, monkeypatch, cleanup):
    """No known IPs → no work, and crucially no ping/arp I/O at all."""
    monkeypatch.setattr(scanner, '_ping_hosts',
                        lambda ips: pytest.fail('must not ping with nothing known'))
    monkeypatch.setattr(scanner, '_arp_fallback',
                        lambda cidr: pytest.fail('must not read arp with nothing known'))
    assert quick_reprobe(app) == 0


def test_reprobe_never_sweeps_or_enriches(app, db, monkeypatch, cleanup):
    """The whole point is cheapness: no scapy sweep, no /24 warming, no SNMP."""
    _no_ping(monkeypatch)
    _add(db, KNOWN_MAC, KNOWN_IP, 130)
    monkeypatch.setattr(scanner, '_scapy_scan',
                        lambda cidr: pytest.fail('keep-alive must not sweep'))
    monkeypatch.setattr(scanner, '_warm_arp_cache',
                        lambda cidr: pytest.fail('keep-alive must not warm /24s'))
    monkeypatch.setattr(scanner, '_arp_fallback',
                        lambda cidr: [(KNOWN_IP, KNOWN_MAC)])

    quick_reprobe(app)                           # must not raise


def test_reprobe_unhides_a_returning_device(app, db, monkeypatch, cleanup):
    """A device hidden by "remove offline" that is back on the wire reappears —
    same contract as a discovery sighting — with its label untouched."""
    _no_ping(monkeypatch)
    _add(db, KNOWN_MAC, KNOWN_IP, 130, hidden=True, label='Hog FL HPU #4')
    monkeypatch.setattr(scanner, '_arp_fallback',
                        lambda cidr: [(KNOWN_IP, KNOWN_MAC)])

    quick_reprobe(app)

    row = db.session.get(NetworkDevice, KNOWN_MAC)
    db.session.refresh(row)
    assert row.hidden is False
    assert row.label == 'Hog FL HPU #4'          # untouched
