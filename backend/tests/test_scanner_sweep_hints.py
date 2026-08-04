"""Sweep hints: telling the scanner where the gear actually lives.

`_sweep_targets` reduces a wide CIDR to the /24s holding either a local NIC or
a previously-seen device, because enumerating the sACN /8 would take ~47h. That
is the right instinct with the wrong aim: on this rig the show gear sits in
10.9.15.0/24 while the host NIC is 10.220.220.220, so the nodes' /24 is never
probed. And `known_ips` comes from devices already in the database, so a device
that has never been seen can never become a sweep target — a device has to be
found before it can be looked for.

Fifteen SideCar nodes (10.9.15.101-.114, .121) were invisible to the app for
exactly this reason while answering ping in 1ms.

Sweep hints break the loop: the operator names the /24s worth probing inside a
loose subnet, and a fresh database finds the gear with no bootstrap ritual.
"""

import pytest

from app import scanner
from app.models import NetworkSubnet


# ---------------------------------------------------------------------------
# Parsing hints
# ---------------------------------------------------------------------------


def test_hint_networks_accepts_a_comma_separated_list():
    assert scanner._hint_networks('10.9.15.0/24, 10.9.16.0/24', '10.0.0.0/8') == [
        '10.9.15.0/24',
        '10.9.16.0/24',
    ]


def test_hint_networks_tolerates_whitespace_and_blanks():
    assert scanner._hint_networks(' 10.9.15.0/24 ,, ', '10.0.0.0/8') == ['10.9.15.0/24']


def test_hint_networks_ignores_a_hint_outside_its_own_subnet():
    """A hint is scoped to its subnet. Sweeping someone else's range because of
    a typo in one row is not a behaviour worth having."""
    assert scanner._hint_networks('192.168.50.0/24', '10.0.0.0/8') == []


def test_hint_networks_rejects_a_hint_too_wide_to_sweep():
    """A /16 hint would reinstate the ~11min sweep that MAX_SWEEP_ADDRESSES
    exists to prevent, and a /8 hint the ~47h one."""
    assert scanner._hint_networks('10.0.0.0/16', '10.0.0.0/8') == []
    assert scanner._hint_networks('10.0.0.0/8', '10.0.0.0/8') == []


def test_a_mixed_family_hint_does_not_abort_the_scan(monkeypatch):
    """Found in review. `subnet_of` raises TypeError across address families,
    and only ValueError was caught — so an IPv6 hint on an IPv4 subnet threw
    out of _sweep_targets, past _arp_scan, and aborted that subnet's entire
    scan rather than being ignored."""
    _no_local_ifaces(monkeypatch)
    assert scanner._hint_networks('fd00::/120', '10.0.0.0/8') == []
    assert scanner._sweep_targets('10.0.0.0/8', known_ips=[], sweep_hints='fd00::/120') == []


def test_validate_reports_why_each_hint_was_rejected():
    accepted, errors = scanner.validate_sweep_hints(
        '10.9.15.0/24, fd00::/120, 192.168.50.0/24, 10.0.0.0/16, garbage',
        '10.0.0.0/8',
    )
    assert accepted == ['10.9.15.0/24']
    joined = ' | '.join(errors)
    assert 'IPv6' in joined                      # mixed family
    assert 'outside' in joined                   # 192.168.50.0/24
    assert 'the limit is' in joined              # /16 too wide
    assert 'not a CIDR block' in joined          # garbage


def test_validate_accepts_silence():
    assert scanner.validate_sweep_hints(None, '10.0.0.0/8') == ([], [])
    assert scanner.validate_sweep_hints('', '10.0.0.0/8') == ([], [])


def test_validate_rejects_an_unusable_parent_subnet_without_raising():
    accepted, errors = scanner.validate_sweep_hints('10.9.15.0/24', 'not-a-network')
    assert accepted == []
    assert errors


def test_hint_networks_survives_nonsense_without_raising():
    assert scanner._hint_networks('not-a-cidr, 10.9.15.0/24', '10.0.0.0/8') == [
        '10.9.15.0/24'
    ]
    assert scanner._hint_networks(None, '10.0.0.0/8') == []
    assert scanner._hint_networks('', '10.0.0.0/8') == []


# ---------------------------------------------------------------------------
# Aiming the sweep
# ---------------------------------------------------------------------------


def _no_local_ifaces(monkeypatch):
    """Pin the host's interfaces out of the picture.

    `_sweep_targets` falls back to the /24s holding a local NIC, so any test
    asserting on its exact output is otherwise measuring the laptop. Same helper
    and same reason as test_scanner_discovery.py. Learned the hard way on
    2026-07-30: these passed all morning with the show NICs unplugged and went
    red the moment they were connected.
    """
    monkeypatch.setattr(scanner, 'local_ipv4s', lambda *a, **k: [])



def test_wide_subnet_without_hints_misses_the_node_range(monkeypatch):
    """The fault, stated as a test. No local NIC and no known device in
    10.9.15.0/24, so nothing aims there and the SideCars stay invisible."""
    _no_local_ifaces(monkeypatch)
    targets = scanner._sweep_targets('10.0.0.0/8', known_ips=['10.220.220.220'])
    assert '10.9.15.0/24' not in targets


def test_a_hint_puts_the_node_range_in_the_sweep(monkeypatch):
    _no_local_ifaces(monkeypatch)
    targets = scanner._sweep_targets(
        '10.0.0.0/8', known_ips=['10.220.220.220'], sweep_hints='10.9.15.0/24'
    )
    assert '10.9.15.0/24' in targets


def test_hints_do_not_replace_the_existing_targets(monkeypatch):
    """Hints are additive. Losing the local-NIC /24 would trade one blind spot
    for another."""
    _no_local_ifaces(monkeypatch)
    targets = scanner._sweep_targets(
        '10.0.0.0/8', known_ips=['10.0.0.5'], sweep_hints='10.9.15.0/24'
    )
    assert '10.9.15.0/24' in targets
    assert '10.0.0.0/24' in targets


def test_hints_are_deduplicated_against_discovered_targets(monkeypatch):
    _no_local_ifaces(monkeypatch)
    targets = scanner._sweep_targets(
        '10.0.0.0/8', known_ips=['10.9.15.111'], sweep_hints='10.9.15.0/24'
    )
    assert targets.count('10.9.15.0/24') == 1


def test_a_narrow_subnet_is_still_swept_whole(monkeypatch):
    """Under MAX_SWEEP_ADDRESSES the whole range is swept, so hints are
    irrelevant rather than harmful."""
    _no_local_ifaces(monkeypatch)
    targets = scanner._sweep_targets('192.168.1.0/24', sweep_hints='192.168.1.0/25')
    assert targets == ['192.168.1.0/24']


def test_hints_alone_are_enough_on_a_fresh_database(monkeypatch):
    """The point of the feature: no known devices, no local NIC in range, and
    the sweep still aims somewhere useful.

    `local_ipv4s` is stubbed out so this asserts the function's behaviour and
    not the adapters of whichever machine runs the suite.
    """
    monkeypatch.setattr(scanner, 'local_ipv4s', lambda *a, **k: [])

    targets = scanner._sweep_targets(
        '10.0.0.0/8', known_ips=[], sweep_hints='10.9.15.0/24'
    )

    assert targets == ['10.9.15.0/24']


# ---------------------------------------------------------------------------
# Model and API
# ---------------------------------------------------------------------------


def test_subnet_exposes_sweep_hints(db):
    subnet = NetworkSubnet(label='sACN', cidr='10.0.0.0/8', sweep_hints='10.9.15.0/24')
    db.session.add(subnet)
    db.session.commit()

    assert subnet.to_dict()['sweepHints'] == '10.9.15.0/24'


def test_sweep_hints_default_to_empty(db):
    subnet = NetworkSubnet(label='sACN', cidr='10.0.0.0/8')
    db.session.add(subnet)
    db.session.commit()

    assert subnet.to_dict()['sweepHints'] is None


def test_create_subnet_accepts_sweep_hints(client):
    resp = client.post(
        '/api/network/subnets',
        json={'label': 'sACN', 'cidr': '10.0.0.0/8', 'sweepHints': '10.9.15.0/24'},
    )
    assert resp.status_code == 201
    assert resp.get_json()['sweepHints'] == '10.9.15.0/24'


def test_patch_sets_hints_on_an_existing_subnet(client):
    """Without an update route the only way to add hints to the subnets that
    already exist is to delete and recreate them, which nulls every device's
    subnet_id."""
    created = client.post(
        '/api/network/subnets', json={'label': 'sACN', 'cidr': '10.0.0.0/8'}
    ).get_json()

    resp = client.patch(
        f"/api/network/subnets/{created['id']}", json={'sweepHints': '10.9.15.0/24'}
    )

    assert resp.status_code == 200
    assert resp.get_json()['sweepHints'] == '10.9.15.0/24'


def test_patch_leaves_unmentioned_fields_alone(client):
    created = client.post(
        '/api/network/subnets',
        json={'label': 'sACN', 'cidr': '10.0.0.0/8', 'color': '#abcdef'},
    ).get_json()

    client.patch(f"/api/network/subnets/{created['id']}", json={'sweepHints': '10.9.15.0/24'})
    after = client.get('/api/network/subnets').get_json()[-1]

    assert after['color'] == '#abcdef'
    assert after['label'] == 'sACN'
    assert after['cidr'] == '10.0.0.0/8'


def test_patch_can_clear_hints(client):
    created = client.post(
        '/api/network/subnets',
        json={'label': 'sACN', 'cidr': '10.0.0.0/8', 'sweepHints': '10.9.15.0/24'},
    ).get_json()

    resp = client.patch(f"/api/network/subnets/{created['id']}", json={'sweepHints': ''})

    assert resp.get_json()['sweepHints'] is None


def test_patch_on_a_missing_subnet_is_404(client):
    assert client.patch('/api/network/subnets/99999', json={'sweepHints': ''}).status_code == 404


# ---------------------------------------------------------------------------
# The API must not accept a hint the scanner will ignore
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hint,because",
    [
        ('fd00::/120', 'wrong address family'),
        ('192.168.50.0/24', 'outside the parent subnet'),
        ('10.0.0.0/16', 'wider than MAX_SWEEP_ADDRESSES'),
        ('not-a-cidr', 'unparseable'),
    ],
)
def test_create_rejects_a_hint_the_scanner_would_ignore(client, hint, because):
    """Storing it and echoing it back as configuration would be the API
    claiming a setting was applied while the scanner does something else."""
    resp = client.post(
        '/api/network/subnets',
        json={'label': 'sACN', 'cidr': '10.0.0.0/8', 'sweepHints': hint},
    )
    assert resp.status_code == 400, f'{hint} should be rejected: {because}'
    assert resp.get_json()['details'], 'the 400 must say what was wrong'


def test_patch_rejects_a_bad_hint_and_leaves_the_stored_value_alone(client):
    created = client.post(
        '/api/network/subnets',
        json={'label': 'sACN', 'cidr': '10.0.0.0/8', 'sweepHints': '10.9.15.0/24'},
    ).get_json()

    resp = client.patch(
        f"/api/network/subnets/{created['id']}", json={'sweepHints': 'fd00::/120'}
    )

    assert resp.status_code == 400
    after = client.get('/api/network/subnets').get_json()[-1]
    assert after['sweepHints'] == '10.9.15.0/24', 'a rejected patch must change nothing'


def test_patch_refuses_fields_it_does_not_support(client):
    """A caller that thinks it changed `cidr` and got a 200 has been misled.
    Changing the parent CIDR also leaves attached device attribution stale."""
    created = client.post(
        '/api/network/subnets', json={'label': 'sACN', 'cidr': '10.0.0.0/8'}
    ).get_json()

    resp = client.patch(
        f"/api/network/subnets/{created['id']}",
        json={'cidr': '10.1.0.0/16', 'active': False},
    )

    assert resp.status_code == 400
    body = resp.get_json()
    assert body['details'] == ['active', 'cidr']
    # ignoreCidrs joined the allowlist on 2026-07-30. The test's point is
    # unchanged -- cidr and active stay refused, because rewriting cidr leaves
    # device attribution stale and flipping active silently stops a scan.
    assert body['supported'] == ['ignoreCidrs', 'sweepHints']

    after = client.get('/api/network/subnets').get_json()[-1]
    assert after['cidr'] == '10.0.0.0/8'
    assert after['active'] is True


# ── IPv6 (Hermes' re-review, 2026-07-30) ─────────────────────────────────────
#
# The family rule was written as "the hint must match the subnet", which is the
# wrong invariant. It catches an IPv6 hint on an IPv4 subnet — the TypeError
# from subnet_of — but an IPv6 subnet with IPv6 hints agrees with itself and is
# accepted, then handed to a sweep that can only send ARP. ARP is IPv4-only:
# there is no such thing as an ARP request for an IPv6 host. The invariant is
# absolute, not relative.

def test_an_ipv6_hint_is_rejected_even_when_the_subnet_is_ipv6_too():
    validate_sweep_hints = scanner.validate_sweep_hints
    accepted, errors = validate_sweep_hints('fd00::/120', 'fd00::/64')
    assert accepted == []
    assert errors, 'an IPv6 hint must be reported, not silently accepted'
    assert 'IPv4' in errors[0], f'the error should say why: {errors[0]!r}'


def test_an_ipv6_subnet_reports_itself_rather_than_being_swept():
    validate_sweep_hints = scanner.validate_sweep_hints
    accepted, errors = validate_sweep_hints('fd00::/120,fd00::100/120', 'fd00::/64')
    assert accepted == []
    assert len(errors) >= 1


def test_ipv4_is_still_accepted():
    validate_sweep_hints = scanner.validate_sweep_hints
    accepted, errors = validate_sweep_hints('10.9.15.0/24', '10.0.0.0/8')
    assert accepted == ['10.9.15.0/24']
    assert errors == []


# ── ignore_cidrs and the sweep (2026-07-30) ──────────────────────────────────
#
# ignore_cidrs filtered results at persist time only: _arp_scan probed the whole
# range and _is_ignored_ip dropped the rows afterwards. So a range the operator
# had declared not-ours was still swept every cycle.
#
# Found via NordVPN: its tunnel adapter is 10.100.0.2/22, inside the configured
# sACN 10.0.0.0/8, so a local NIC put 10.100.0.0/24 in the sweep. Probing a VPN
# tunnel to throw every answer away is pure waste.

def test_a_target_entirely_inside_an_ignored_range_is_not_swept(monkeypatch):
    monkeypatch.setattr(scanner, 'local_ipv4s', lambda *a, **k: ['10.100.0.2'])
    targets = scanner._sweep_targets('10.0.0.0/8', known_ips=[],
                                     ignore_cidrs='10.100.0.0/22')
    assert '10.100.0.0/24' not in targets


def test_ignoring_a_range_does_not_blind_a_target_that_is_only_partly_in_it(monkeypatch):
    """A /25 inside a /24 must not stop the /24 being swept — half of it is
    still ours."""
    monkeypatch.setattr(scanner, 'local_ipv4s', lambda *a, **k: ['10.9.15.10'])
    targets = scanner._sweep_targets('10.0.0.0/8', known_ips=[],
                                     ignore_cidrs='10.9.15.0/25')
    assert '10.9.15.0/24' in targets


def test_ignoring_nothing_leaves_the_sweep_alone(monkeypatch):
    monkeypatch.setattr(scanner, 'local_ipv4s', lambda *a, **k: ['10.100.0.2'])
    assert scanner._sweep_targets('10.0.0.0/8', known_ips=[],
                                  ignore_cidrs=None) == ['10.100.0.0/24']


def test_an_ignored_range_also_suppresses_a_hint_aimed_into_it(monkeypatch):
    """An operator hint and an operator ignore that contradict each other: the
    ignore wins, because it is the more specific statement of intent."""
    _no_local_ifaces(monkeypatch)
    targets = scanner._sweep_targets('10.0.0.0/8', known_ips=[],
                                     sweep_hints='10.100.0.0/24',
                                     ignore_cidrs='10.100.0.0/22')
    assert targets == []


def test_a_garbage_ignore_entry_does_not_abort_the_sweep(monkeypatch):
    """Rows can be edited straight in the database. A bad entry must not take
    the whole subnet's scan down."""
    monkeypatch.setattr(scanner, 'local_ipv4s', lambda *a, **k: ['10.100.0.2'])
    targets = scanner._sweep_targets('10.0.0.0/8', known_ips=[],
                                     ignore_cidrs='not-a-cidr, 10.100.0.0/22')
    assert '10.100.0.0/24' not in targets


def test_patch_sets_ignore_cidrs_on_an_existing_subnet(client):
    """The whole reason this field joined the allowlist: it was previously
    settable only at create time, and recreating a subnet nulls subnet_id on
    every attached device."""
    created = client.post(
        '/api/network/subnets', json={'label': 'sACN', 'cidr': '10.0.0.0/8'}
    ).get_json()

    resp = client.patch(f"/api/network/subnets/{created['id']}",
                        json={'ignoreCidrs': '10.100.0.0/22'})

    assert resp.status_code == 200
    assert resp.get_json()['ignoreCidrs'] == '10.100.0.0/22'


def test_patch_rejects_an_ignore_range_outside_the_subnet(client):
    created = client.post(
        '/api/network/subnets', json={'label': 'sACN', 'cidr': '10.0.0.0/8'}
    ).get_json()

    resp = client.patch(f"/api/network/subnets/{created['id']}",
                        json={'ignoreCidrs': '192.168.1.0/24'})

    assert resp.status_code == 400
    assert 'outside' in ' '.join(resp.get_json()['details'])


def test_patch_rejects_an_unparseable_ignore_range(client):
    created = client.post(
        '/api/network/subnets', json={'label': 'sACN', 'cidr': '10.0.0.0/8'}
    ).get_json()

    resp = client.patch(f"/api/network/subnets/{created['id']}",
                        json={'ignoreCidrs': '10.100.0.0/22, nonsense'})

    assert resp.status_code == 400
    assert 'not a CIDR block' in ' '.join(resp.get_json()['details'])


def test_patch_can_clear_ignore_cidrs(client):
    created = client.post(
        '/api/network/subnets',
        json={'label': 'sACN', 'cidr': '10.0.0.0/8', 'ignoreCidrs': '10.100.0.0/22'}
    ).get_json()

    resp = client.patch(f"/api/network/subnets/{created['id']}",
                        json={'ignoreCidrs': ''})

    assert resp.status_code == 200
    assert resp.get_json()['ignoreCidrs'] is None
