"""Adapter mapping, against payloads captured verbatim from the dish.

The fixtures are real responses, not composed ones. A Starlink firmware update
can move fields, which is why every read is a .get() with a default and why
these tests exist: they say what the panel will show for a payload we have
actually seen.

Two things the captured payload settled that the design could not, because the
design sample was truncated at 1400 characters:

1. There is no `state` field. `device_state` carries uptime and nothing else,
   so the old `state == 'CONNECTED'` test could never have been true.
2. `dish_get_history.outages[]` is stamped on an uncorrected clock reading
   2016, ten years and change behind `event_log.events[]`, which is stamped on
   wall clock. Anything time-based must come from the event log.
"""

import copy
import json
import pathlib
from unittest.mock import patch

import pytest

FIXTURES = pathlib.Path(__file__).parent / 'fixtures'
STATUS = json.loads((FIXTURES / 'starlink_get_status.json').read_text())
HISTORY = json.loads((FIXTURES / 'starlink_get_history.json').read_text())

DISH = STATUS['dish_get_status']
HIST = HISTORY['dish_get_history']

CALL = 'app.integrations.starlink_grpc_client.call'


def _adapter():
    from app.integrations.starlink import StarlinkAdapter
    return StarlinkAdapter()


def _fake_call(name, **kw):
    return {'get_status': STATUS, 'get_history': HISTORY}[name]


def _status_from(status=None, history=None):
    """Run _real_status() against a possibly-edited copy of the fixtures."""
    payloads = {'get_status': status or STATUS, 'get_history': history or HISTORY}

    def call(name, **kw):
        return payloads[name]

    with patch(CALL, side_effect=call):
        return _adapter()._real_status()


def _edited_status(**dish_fields):
    edited = copy.deepcopy(STATUS)
    edited['dish_get_status'].update(dish_fields)
    return edited


# ---------------------------------------------------------------------------
# The panel's contract
# ---------------------------------------------------------------------------


def test_the_captured_status_maps_to_every_key_the_panel_reads():
    s = _status_from()

    assert s['available'] is True
    for key in ('state', 'online', 'uptimeS', 'downMbps', 'upMbps', 'latencyMs',
                'obstructionPct', 'snrAboveNoiseFloor', 'hardwareAlerts',
                'outagesLastHour', 'outageLog'):
        assert key in s, f'panel reads {key} and the adapter did not supply it'


def test_throughput_is_reported_in_megabits_not_bits():
    """The dish reports bps; the panel's tiles say Mbps. A missing conversion
    would render 9217344.0 under a label reading Mbps."""
    s = _status_from()

    # Absolute tolerance, not relative: the adapter rounds to 2dp for the tile,
    # and the captured link was near idle. A missing conversion is off by 1e6.
    assert s['downMbps'] == pytest.approx(DISH['downlink_throughput_bps'] / 1e6, abs=0.01)
    assert s['upMbps'] == pytest.approx(DISH['uplink_throughput_bps'] / 1e6, abs=0.01)
    assert s['downMbps'] < 10_000        # a sanity bound no real link exceeds


def test_obstruction_is_a_percentage_not_a_fraction():
    """The dish reports fraction_obstructed 0..1 and the tile's unit is '%'.
    The captured payload reads 0.41, and rendering that under a % label would
    show a badly obstructed dish as healthy."""
    s = _status_from()

    frac = DISH['obstruction_stats']['fraction_obstructed']
    assert s['obstructionPct'] == pytest.approx(frac * 100, rel=1e-3)
    assert s['obstructionPct'] > 5       # the captured dish is genuinely obstructed


def test_uptime_comes_from_device_state_and_is_a_number():
    """uptime_s is nested under device_state and arrives as a STRING. The old
    code read a top-level 'uptime' that does not exist, and the panel formats
    this as a duration."""
    s = _status_from()

    assert s['uptimeS'] == int(DISH['device_state']['uptime_s'])
    assert isinstance(s['uptimeS'], int)


def test_device_info_reaches_the_panel():
    s = _status_from()

    info = DISH['device_info']
    assert s['hardwareVersion'] == info['hardware_version']
    assert s['softwareVersion'] == info['software_version']
    assert s['bootcount'] == info['bootcount']


def test_the_extra_status_fields_task_three_renders_are_present():
    s = _status_from()

    assert s['softwareUpdateState'] == DISH['software_update_state']
    assert s['gpsValid'] == DISH['gps_stats']['gps_valid']
    assert s['gpsSats'] == DISH['gps_stats']['gps_sats']
    assert s['ethSpeedMbps'] == DISH['eth_speed_mbps']
    assert s['mobilityClass'] == DISH['mobility_class']
    assert s['disablementCode'] == DISH['disablement_code']
    assert s['obstructionValidS'] == pytest.approx(
        DISH['obstruction_stats']['valid_s'])


def test_hardware_alerts_list_only_the_raised_ones():
    s = _status_from()

    assert s['hardwareAlerts'] == [k for k, v in DISH['alerts'].items() if v]
    assert 'install_pending' in s['hardwareAlerts']


# ---------------------------------------------------------------------------
# state and online — the question the design left open
# ---------------------------------------------------------------------------


def test_the_dish_reports_no_state_field_so_none_may_be_invented():
    """Pinning the finding itself. device_state holds uptime and nothing more,
    so `state == 'CONNECTED'` was unreachable and the panel's dot could never
    have gone green. If a firmware ever adds a real state field, this test is
    the one that should be revisited."""
    assert 'state' not in DISH
    assert set(DISH['device_state']) == {'uptime_s'}

    s = _status_from()
    assert s['state'] != 'CONNECTED', 'CONNECTED is not a word this dish says'


def test_a_healthy_dish_is_online_and_reads_as_ready():
    """Derived from the two fields that do carry it: disablement_code is OKAY
    and every ready_states subsystem is true."""
    assert DISH['disablement_code'] == 'OKAY'
    assert all(DISH['ready_states'].values())

    s = _status_from()
    assert s['online'] is True
    assert s['state'] == 'READY'


def test_a_disabled_dish_is_offline_and_the_state_is_the_dish_s_own_word():
    """The panel prints state verbatim next to the dot, so an operator should
    see the dish's own reason rather than a word this adapter made up."""
    s = _status_from(_edited_status(disablement_code='NO_ACTIVE_ACCOUNT'))

    assert s['online'] is False
    assert s['state'] == 'NO_ACTIVE_ACCOUNT'


def test_a_subsystem_that_is_not_ready_is_named():
    ready = dict(DISH['ready_states'], rf=False)
    s = _status_from(_edited_status(ready_states=ready))

    assert s['online'] is False
    assert 'rf' in s['state']


def test_a_payload_with_no_readiness_evidence_does_not_claim_online():
    """Absence of the fields is not evidence the dish is up. A firmware that
    drops ready_states must not silently turn the dot green."""
    edited = copy.deepcopy(STATUS)
    edited['dish_get_status'].pop('ready_states')
    edited['dish_get_status'].pop('disablement_code')

    s = _status_from(edited)
    assert s['online'] is False
    assert s['state'] == 'UNKNOWN'


def test_an_active_outage_is_offline_even_when_nothing_else_complains():
    """The dish reports an outage in progress as a nested `outage` field, and
    during an obstruction outage `disablement_code` stays OKAY and every
    ready_state stays true. Deriving online from those two alone reports READY
    while the dish is dropping out — precisely the moment the panel matters.

    This is also how sparky8512's wrapper derives its `state`: the absence of
    this field is the only thing behind its literal 'CONNECTED'.
    """
    assert 'outage' not in DISH, 'the captured dish was not in an outage'

    s = _status_from(_edited_status(outage={
        'cause': 'OBSTRUCTED',
        'start_timestamp_ns': '1786363474730245843',
        'duration_ns': '84269976877',
    }))

    assert s['online'] is False
    assert s['state'] == 'OBSTRUCTED'


def test_an_outage_with_no_named_cause_still_reads_as_an_outage():
    """protobuf omits an enum field at its zero value, so `cause` can be
    missing from a perfectly real outage."""
    s = _status_from(_edited_status(outage={'start_timestamp_ns': '1'}))

    assert s['online'] is False
    assert s['state'] == 'OUTAGE'


def test_a_disablement_outranks_an_active_outage():
    """Both can be set at once. The disablement is the root cause; the outage
    is its symptom, and the operator needs the former."""
    s = _status_from(_edited_status(disablement_code='NO_ACTIVE_ACCOUNT',
                                    outage={'cause': 'NO_PINGS'}))

    assert s['state'] == 'NO_ACTIVE_ACCOUNT'
    assert s['online'] is False


def test_a_dish_without_actuators_is_not_reported_as_stowed():
    """The old code derived stowed from the state field that does not exist.
    This dish reports HAS_ACTUATORS_NO, so it physically cannot stow."""
    assert DISH['alignment_stats']['has_actuators'] == 'HAS_ACTUATORS_NO'
    assert _status_from()['stowed'] is False


# ---------------------------------------------------------------------------
# Outages — and the two clocks
# ---------------------------------------------------------------------------


def test_the_outage_tiles_are_no_longer_hardcoded_empty():
    """These two were `None` and `[]` behind a `needs history_data(); v2`
    comment, so the panel's outage tile and log have always been blank — and
    ALERT_RULES has an outagesLastHour rule that could never fire."""
    s = _status_from()

    assert s['outagesLastHour'] is not None
    assert isinstance(s['outageLog'], list)
    assert s['outageLog'], 'the captured history has events and none reached the panel'
    entry = s['outageLog'][0]
    assert set(entry) >= {'ts', 'durationS', 'cause'}
    assert isinstance(entry['durationS'], (int, float))


def test_outage_timestamps_come_from_the_event_log_not_the_outages_list():
    """dish_get_history carries the same kind of record twice. outages[] is
    stamped on an uncorrected clock that reads 2016; event_log.events[] is on
    wall clock. Reading the wrong one puts every outage ten years in the past,
    which the panel would render and the last-hour count would never see."""
    outages_ns = int(HIST['outages'][0]['start_timestamp_ns'])
    events_ns = int(HIST['event_log']['events'][0]['start_timestamp_ns'])
    assert events_ns - outages_ns > 3.1e17, 'fixture no longer shows the two clocks'

    s = _status_from()
    earliest = min(e['ts'] for e in s['outageLog'])
    assert earliest > 1.7e9, 'outage timestamps came from the 2016 clock'


def test_outages_last_hour_is_counted_against_the_dish_s_own_clock():
    """Not the host's. The dish stamps its events, the dish says what time it
    thinks it is in event_log.current_timestamp_ns, and using anything else
    makes the count drift with clock skew — and makes this test expire."""
    now_ns = int(HIST['event_log']['current_timestamp_ns'])
    expected = sum(
        1 for e in HIST['event_log']['events']
        if now_ns - int(e['start_timestamp_ns']) <= 3600 * 1e9)

    assert _status_from()['outagesLastHour'] == expected
    assert expected > 0, 'fixture no longer exercises the last-hour window'


def test_outage_causes_are_readable_rather_than_enum_constants():
    """The panel prints cause verbatim. EVENT_REASON_OUTAGE_OBSTRUCTED in a
    log line is noise around the one word that matters."""
    causes = {e['cause'] for e in _status_from()['outageLog']}

    assert 'OBSTRUCTED' in causes
    assert not any(c.startswith('EVENT_REASON') for c in causes)


def test_the_outage_log_is_newest_first():
    """The sim builds it reversed, so the panel already expects that order."""
    stamps = [e['ts'] for e in _status_from()['outageLog']]
    assert stamps == sorted(stamps, reverse=True)


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


def test_an_unreachable_dish_is_unavailable_not_an_exception():
    """The adapter is polled on a timer; a raise here would surface as a 500
    on every cycle rather than a panel that says the dish is not answering."""
    with patch(CALL, side_effect=OSError('dish unreachable')):
        s = _adapter()._real_status()

    assert s['available'] is False
    assert 'reason' in s


def test_a_history_failure_does_not_lose_the_status():
    """Two independent calls. If get_history fails, the dish's live state is
    still worth showing — half a read must not cost the other half."""
    def only_status(name, **kw):
        if name == 'get_history':
            raise OSError('timeout')
        return STATUS

    with patch(CALL, side_effect=only_status):
        s = _adapter()._real_status()

    assert s['available'] is True
    assert s['latencyMs'] is not None
    assert s['outagesLastHour'] is None      # honest about what is missing
    assert s['outageLog'] == []


def test_the_dependency_message_names_installable_packages():
    """The old text told operators to `pip install starlink-grpc-tools`, which
    does not exist on PyPI. Whatever replaces it must be runnable."""
    import inspect
    from app.integrations import starlink
    src = inspect.getsource(starlink)
    assert 'starlink-grpc-tools' not in src
    assert 'starlink_grpc' not in src.replace('starlink_grpc_client', '')
