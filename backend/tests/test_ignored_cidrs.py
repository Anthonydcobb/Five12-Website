"""Per-subnet ignore_cidrs — keep venue Wi-Fi out of the device table.

[MEASURED 2026-07-21] 148 unknown devices sat on the Management subnet and 145
of them were inside 172.16.10.0/23 — the venue Wi-Fi /23 that overlaps the
Management /16. Their OUIs are scattered consumer singletons, so OUI matching
cannot catch them. The subnet boundary can, so a subnet carries a list of CIDRs
whose addresses are never persisted as devices at all.
"""

import ipaddress

from app.models import NetworkSubnet
from app.scanner import _ignored_networks, _is_ignored_ip


def test_subnet_exposes_ignore_cidrs(db):
    subnet = NetworkSubnet(label='Management', cidr='172.16.0.0/16',
                           ignore_cidrs='172.16.10.0/23')
    db.session.add(subnet)
    db.session.flush()
    assert subnet.to_dict()['ignoreCidrs'] == '172.16.10.0/23'


def test_subnet_without_ignore_cidrs_reports_none(db):
    subnet = NetworkSubnet(label='HogNet', cidr='172.31.0.0/16')
    db.session.add(subnet)
    db.session.flush()
    assert subnet.to_dict()['ignoreCidrs'] is None


def test_subnet_can_be_created_with_an_ignore_list(client, db):
    res = client.post('/api/network/subnets',
                      json={'label': 'Venue', 'cidr': '172.16.0.0/16',
                            'ignoreCidrs': '172.16.10.0/23'})
    assert res.status_code == 201
    assert res.get_json()['ignoreCidrs'] == '172.16.10.0/23'
    client.delete(f"/api/network/subnets/{res.get_json()['id']}")


def test_blank_ignore_cidrs_parses_to_nothing():
    assert _ignored_networks(None) == []
    assert _ignored_networks('') == []
    assert _ignored_networks('   ') == []


def test_comma_separated_cidrs_parse():
    assert _ignored_networks('172.16.10.0/23, 192.168.5.0/24') == [
        ipaddress.ip_network('172.16.10.0/23'),
        ipaddress.ip_network('192.168.5.0/24'),
    ]


def test_unparseable_entry_is_skipped_not_fatal():
    """An operator typo must not take the whole subnet's scan down."""
    assert _ignored_networks('not-a-cidr, 172.16.10.0/23') == [
        ipaddress.ip_network('172.16.10.0/23')
    ]


def test_wifi_addresses_are_ignored():
    nets = _ignored_networks('172.16.10.0/23')
    assert _is_ignored_ip('172.16.10.5', nets)
    assert _is_ignored_ip('172.16.11.200', nets)


def test_lighting_addresses_on_the_same_subnet_are_kept():
    """The Netgear switches at 172.16.3.x sit inside the same Management /16
    and must survive the filter."""
    nets = _ignored_networks('172.16.10.0/23')
    assert not _is_ignored_ip('172.16.3.97', nets)
    assert not _is_ignored_ip('172.16.12.1', nets)


def test_no_ignore_list_ignores_nothing():
    assert not _is_ignored_ip('172.16.10.5', [])


def test_garbage_ip_is_not_ignored():
    assert not _is_ignored_ip('not-an-ip', _ignored_networks('172.16.10.0/23'))
