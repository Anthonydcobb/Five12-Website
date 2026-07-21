"""Timestamps must cross the API as unambiguous UTC instants.

[ROOT CAUSE 2026-07-21] Every device showed permanently ONLINE even when it
was off the network. `to_dict()` serialized `datetime.utcnow()` values with a
bare `.isoformat()`, producing e.g. "2026-07-21T20:57:05" — no `Z`, no offset.
Per the ECMAScript spec a date-time string WITHOUT an offset is parsed as LOCAL
time, so the browser read a UTC instant as local and placed it 4 hours in the
future (UTC-4). `isOnline` then computed a NEGATIVE elapsed time, and
`negative < 90_000` is always true, so nothing was ever offline. The device
detail pane showed the tell: "LAST SEEN -12910s ago".

This also disabled the "remove offline devices" button, whose count is computed
from the same predicate — the backend endpoint was correct, the UI just never
believed anything was offline.
"""

from datetime import datetime, timezone

from app.models import NetworkDevice, NetworkSubnet, LocationSnapshot


SEEN = datetime(2026, 7, 21, 20, 57, 5)  # naive UTC, as the columns store it


def _assert_utc_instant(text, expected_naive_utc):
    """The string must pin an absolute moment, not a wall-clock reading."""
    assert text is not None
    parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
    assert parsed.tzinfo is not None, (
        f'{text!r} has no timezone designator — JS parses this as LOCAL time')
    assert parsed == expected_naive_utc.replace(tzinfo=timezone.utc)


def test_last_seen_is_an_unambiguous_utc_instant(db):
    device = NetworkDevice(mac_address='AA:BB:CC:00:00:20', last_seen=SEEN)
    db.session.add(device)
    db.session.flush()
    _assert_utc_instant(device.to_dict()['lastSeen'], SEEN)


def test_device_created_at_is_an_unambiguous_utc_instant(db):
    device = NetworkDevice(mac_address='AA:BB:CC:00:00:21', created_at=SEEN)
    db.session.add(device)
    db.session.flush()
    _assert_utc_instant(device.to_dict()['createdAt'], SEEN)


def test_snapshot_created_at_is_an_unambiguous_utc_instant(db):
    """`formatDate` renders this one as a calendar date, so a 4h shift can
    print the wrong DAY for anything saved late in the evening."""
    snap = LocationSnapshot(name='Rig check', created_at=SEEN)
    db.session.add(snap)
    db.session.flush()
    _assert_utc_instant(snap.to_dict()['createdAt'], SEEN)


def test_null_timestamps_stay_null(db):
    """A device that has never been seen must serialize as null, not a
    string — `isOnline` short-circuits on falsy lastSeen."""
    device = NetworkDevice(mac_address='AA:BB:CC:00:00:22', last_seen=None)
    db.session.add(device)
    db.session.flush()
    assert device.to_dict()['lastSeen'] is None


def test_an_offline_device_reads_as_offline_not_online(db):
    """The reported bug, end to end at the serialization boundary.

    A device last seen 27 minutes ago must produce a POSITIVE elapsed time.
    Negative elapsed is what made `elapsed < 90_000` always true.
    """
    from datetime import timedelta
    seen = datetime.utcnow() - timedelta(minutes=27)
    device = NetworkDevice(mac_address='00:90:A1:26:12:71', label='Hobbs',
                           last_seen=seen)
    db.session.add(device)
    db.session.flush()

    text = device.to_dict()['lastSeen']
    parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
    elapsed = (datetime.now(timezone.utc) - parsed).total_seconds()

    assert elapsed > 0, f'elapsed is negative ({elapsed}s) — timestamp reads as future'
    assert elapsed > 90, 'a device seen 27 minutes ago must be offline'


def test_subnet_dict_has_no_naive_timestamp_leak(db):
    """NetworkSubnet.to_dict() exposes no timestamp today. If one is ever
    added it must go through the same helper, so this guards the shape."""
    subnet = NetworkSubnet(label='Hognet', cidr='172.31.0.0/16')
    db.session.add(subnet)
    db.session.flush()
    for key, value in subnet.to_dict().items():
        if isinstance(value, str) and 'T' in value and value[:4].isdigit():
            _assert_utc_instant(value, None)
