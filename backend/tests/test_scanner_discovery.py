"""Scanner discovery-path tests.

[VERIFIED 2026-07-21] These cover a live failure found on the rig: scapy
imports fine on Windows but cannot send raw frames without Npcap/admin, so its
ARP sweep returns ZERO answers WITHOUT raising. The old `_arp_scan` only fell
back to the OS ARP cache inside `except`, so it returned [] and discovery was
silently dead — every device's vendor type froze at whatever an older scan had
written, and a second Bolero antenna at 192.168.1.12 was never discovered.
"""

import pytest

import app.scanner as scanner
from app.scanner import (_arp_scan, _is_host_mac, _merge_pairs,
                         _sweep_targets, MAX_SWEEP_ADDRESSES)
from app.vendors import is_randomized_mac


CACHE = [('192.168.1.11', '00:19:7C:02:E0:5B'),
         ('192.168.1.12', '00:19:7C:02:E1:56')]


def test_falls_back_when_scapy_answers_nothing(monkeypatch):
    """The regression: silent empty result, no exception."""
    monkeypatch.setattr(scanner, '_scapy_scan', lambda cidr: [])
    monkeypatch.setattr(scanner, '_arp_fallback', lambda cidr: CACHE)
    assert sorted(_arp_scan('192.168.1.0/24')) == sorted(CACHE)


def test_falls_back_when_scapy_raises(monkeypatch):
    def boom(cidr):
        raise OSError('no Npcap')
    monkeypatch.setattr(scanner, '_scapy_scan', boom)
    monkeypatch.setattr(scanner, '_arp_fallback', lambda cidr: CACHE)
    assert sorted(_arp_scan('192.168.1.0/24')) == sorted(CACHE)


def test_merges_both_sources_rather_than_preferring_one(monkeypatch):
    """scapy sees live responders; the ARP cache remembers recent ones. Either
    can hold a device the other misses, so discovery uses the union."""
    monkeypatch.setattr(scanner, '_scapy_scan',
                        lambda cidr: [('192.168.1.11', '00:19:7C:02:E0:5B')])
    monkeypatch.setattr(scanner, '_arp_fallback', lambda cidr: CACHE)
    assert sorted(_arp_scan('192.168.1.0/24')) == sorted(CACHE)


def test_scapy_result_wins_on_conflicting_mac(monkeypatch):
    """A stale cache entry must not override a live scapy answer for the same IP."""
    monkeypatch.setattr(scanner, '_scapy_scan',
                        lambda cidr: [('192.168.1.11', 'AA:BB:CC:00:00:01')])
    monkeypatch.setattr(scanner, '_arp_fallback',
                        lambda cidr: [('192.168.1.11', '00:19:7C:02:E0:5B')])
    assert _arp_scan('192.168.1.0/24') == [('192.168.1.11', 'AA:BB:CC:00:00:01')]


def test_merge_dedupes_identical_pairs():
    assert _merge_pairs(CACHE, CACHE) == sorted(CACHE)


def test_both_bolero_antennas_survive_the_filters():
    """Riedel antennas share OUI 00:19:7C — neither is randomized or non-host,
    so both must pass the filters that keep venue phones out."""
    for ip, mac in CACHE:
        assert _is_host_mac(mac)
        assert not is_randomized_mac(mac)


# --- sweep targeting -------------------------------------------------------
# [VERIFIED 2026-07-21] Measured on the rig: a /24 scapy sweep takes ~2.6s, so
# a /16 is ~11min and the configured sACN 10.0.0.0/8 is ~47h. run_scan_now
# walks subnets sequentially, so the /8 stalled every later subnet for days.

def _no_local_ifaces(monkeypatch):
    monkeypatch.setattr(scanner, 'local_ipv4s', lambda *a, **k: [])


def test_narrow_cidr_is_swept_whole(monkeypatch):
    _no_local_ifaces(monkeypatch)
    assert _sweep_targets('192.168.1.0/24') == ['192.168.1.0/24']


def test_wide_cidr_is_never_enumerated_whole(monkeypatch):
    """The regression: a /8 must never become 16.7M probes."""
    _no_local_ifaces(monkeypatch)
    for target in _sweep_targets('10.0.0.0/8', ['10.0.0.4', '10.31.2.93']):
        import ipaddress
        assert ipaddress.ip_network(target).num_addresses <= MAX_SWEEP_ADDRESSES


def test_wide_cidr_targets_known_device_slash24s(monkeypatch):
    _no_local_ifaces(monkeypatch)
    targets = _sweep_targets('10.0.0.0/8', ['10.0.0.4', '10.0.0.22',
                                            '10.31.2.93'])
    # Two devices in one /24 collapse to a single target.
    assert targets == ['10.0.0.0/24', '10.31.2.0/24']


def test_local_nic_seeds_a_target(monkeypatch):
    monkeypatch.setattr(scanner, 'local_ipv4s',
                        lambda *a, **k: ['172.16.220.220', '192.168.1.220'])
    # Only the NIC inside the CIDR counts.
    assert _sweep_targets('172.16.0.0/16') == ['172.16.220.0/24']


def test_ips_outside_the_cidr_are_ignored(monkeypatch):
    _no_local_ifaces(monkeypatch)
    assert _sweep_targets('10.0.0.0/8', ['192.168.1.11', 'not-an-ip']) == []


def test_wide_cidr_with_no_known_ips_still_reads_the_cache(monkeypatch):
    """No sweep target is not the same as no discovery — `arp -a` covers the
    whole CIDR regardless, which is how the Netgear switches are found."""
    _no_local_ifaces(monkeypatch)
    monkeypatch.setattr(scanner, '_scapy_scan',
                        lambda cidr: pytest.fail('must not sweep a /8'))
    monkeypatch.setattr(scanner, '_warm_arp_cache',
                        lambda cidr: pytest.fail('must not warm a /8'))
    netgear = [('172.16.3.97', '28:94:01:84:39:E5')]
    monkeypatch.setattr(scanner, '_arp_fallback', lambda cidr: netgear)
    assert _arp_scan('10.0.0.0/8') == netgear
