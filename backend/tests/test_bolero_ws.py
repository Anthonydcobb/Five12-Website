"""Per-antenna beltpack counts from the Bolero websocket.

The protocol is established in docs/architecture/bolero-websocket-protocol.md.
Three facts drive every test here:

* the socket takes no requests, so there is no snapshot to ask for — a fresh
  listener knows nothing and learns only as `audioPorts` messages arrive;
* a pack's antenna changes several times a second (DECT handover), so only the
  aggregate count is worth showing;
* `audioPorts` only ever says `registered: true` — no deregistration was ever
  observed — so the model is last-announcement-wins.

Everything below drives the pure accumulator. Nothing here opens a socket.
"""

import time

import pytest

from app.integrations.bolero_ws import BoleroAntennaCounts


LM2, LM1, LM3 = 132651929, 163060633, 198187945
NAMES = {LM2: 'MBS LM 2', LM1: 'MBS LM 1', LM3: 'MBS LM 3'}


def _msg(bp_id, node_id, registered=True, port_type=1):
    return {'audioPorts': [{'registered': registered,
                            'id': {'type': port_type, 'id': bp_id},
                            'nodeId': node_id}]}


@pytest.fixture
def counts():
    return BoleroAntennaCounts(names_by_id=NAMES)


def test_it_knows_nothing_before_any_message(counts):
    assert counts.snapshot(packs_online=[2, 4])['converged'] is False


def test_it_withholds_counts_until_every_pack_is_accounted_for(counts):
    """Half a picture that looks whole is the failure this exists to avoid."""
    counts.observe(_msg(2, LM1))
    snap = counts.snapshot(packs_online=[2, 4])
    assert snap['converged'] is False
    assert snap['byAntenna'] is None


def test_it_converges_once_every_connected_pack_has_been_seen(counts):
    counts.observe(_msg(2, LM1))
    counts.observe(_msg(4, LM2))
    snap = counts.snapshot(packs_online=[2, 4])
    assert snap['converged'] is True
    assert snap['byAntenna'] == {'MBS LM 1': 1, 'MBS LM 2': 1}


def test_the_last_announcement_wins(counts):
    """Handover: pack 30 moved LM3 -> LM1 -> LM3 in 450ms on the real rig."""
    counts.observe(_msg(30, LM3))
    counts.observe(_msg(30, LM1))
    counts.observe(_msg(30, LM3))
    assert counts.snapshot(packs_online=[30])['byAntenna'] == {'MBS LM 3': 1}


def test_a_pack_is_never_counted_twice(counts):
    counts.observe(_msg(30, LM3))
    counts.observe(_msg(30, LM1))
    snap = counts.snapshot(packs_online=[30])
    assert sum(snap['byAntenna'].values()) == 1


def test_counts_sum_to_the_packs_online(counts):
    for bp, node in [(2, LM1), (4, LM1), (6, LM2), (30, LM3)]:
        counts.observe(_msg(bp, node))
    snap = counts.snapshot(packs_online=[2, 4, 6, 30])
    assert sum(snap['byAntenna'].values()) == 4


def test_a_pack_that_goes_offline_stops_being_counted(counts):
    counts.observe(_msg(2, LM1))
    counts.observe(_msg(4, LM2))
    snap = counts.snapshot(packs_online=[2])          # 4 dropped off
    assert snap['converged'] is True
    assert snap['byAntenna'] == {'MBS LM 1': 1}


def test_non_beltpack_audio_ports_are_ignored(counts):
    """id.type 1 is a beltpack. Anything else is a different port kind and must
    not inflate a beltpack count."""
    counts.observe(_msg(99, LM1, port_type=7))
    assert counts.snapshot(packs_online=[])['byAntenna'] == {}


def test_an_unregistered_port_does_not_attribute(counts):
    """Never observed on the real rig, but the field exists, so honour it."""
    counts.observe(_msg(2, LM1, registered=False))
    assert counts.snapshot(packs_online=[2])['converged'] is False


def test_an_unknown_node_id_is_named_rather_than_dropped(counts):
    counts.observe(_msg(2, 55555))
    snap = counts.snapshot(packs_online=[2])
    assert snap['converged'] is True
    assert list(snap['byAntenna']) == ['Antenna 55555']


def test_messages_without_audio_ports_are_harmless(counts):
    counts.observe({'nodeStatus': [{'nodeId': LM2}]})
    counts.observe({'pong': 'pong'})
    counts.observe({})
    assert counts.snapshot(packs_online=[])['converged'] is True


# ── listener lifecycle ───────────────────────────────────────────────────────
#
# Characterisation, not driven: the listener class was written alongside these
# rather than before them. Recorded as such rather than presented as TDD. The
# accumulator above WAS driven test-first.
#
# No socket is opened here — start() with an unroutable host exercises the
# lifecycle and the error path without touching the network.

from app.integrations.bolero_ws import BoleroAntennaListener


@pytest.fixture
def listener():
    lis = BoleroAntennaListener(host='127.0.0.1:1', counts=BoleroAntennaCounts())
    yield lis
    lis.stop(timeout=2)


def test_it_is_stopped_before_it_is_started(listener):
    assert listener.status()['state'] == 'stopped'


def test_starting_twice_is_harmless(listener):
    assert listener.start() is True
    assert listener.start() is False, 'a second start must not spawn a thread'


def test_stopping_a_stopped_listener_is_harmless(listener):
    assert listener.stop(timeout=2) is True
    assert listener.stop(timeout=2) is True


def test_status_carries_no_credentials(listener):
    blob = repr(listener.status())
    assert 'userPass' not in blob and 'password' not in blob


def test_status_reports_the_contract_fields(listener):
    """The field list the hardening plan's Task 3.1 specifies, so the runtime
    manager can register this unchanged."""
    st = listener.status()
    for field in ('name', 'category', 'state', 'startedAt', 'lastSuccessAt',
                  'lastErrorAt', 'lastErrorSummary', 'workCount',
                  'restartCount', 'interface'):
        assert field in st, field


def test_it_reports_degraded_rather_than_raising_when_it_cannot_connect(listener):
    listener.start()
    for _ in range(40):
        if listener.status()['state'] == 'degraded':
            break
        time.sleep(0.1)
    st = listener.status()
    assert st['state'] == 'degraded'
    assert st['lastErrorSummary']
    assert st['restartCount'] >= 1
