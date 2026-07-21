"""Scanner discovery-path tests.

[VERIFIED 2026-07-21] These cover a live failure found on the rig: scapy
imports fine on Windows but cannot send raw frames without Npcap/admin, so its
ARP sweep returns ZERO answers WITHOUT raising. The old `_arp_scan` only fell
back to the OS ARP cache inside `except`, so it returned [] and discovery was
silently dead — every device's vendor type froze at whatever an older scan had
written, and a second Bolero antenna at 192.168.1.12 was never discovered.
"""

import app.scanner as scanner
from app.scanner import _arp_scan, _is_host_mac, _merge_pairs
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
