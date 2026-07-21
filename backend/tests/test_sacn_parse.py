"""sACN parser + registry tests.

The parsers are the part of the listener most likely to be silently wrong — a
one-byte offset error yields plausible-looking garbage rather than a crash — and
the one part testable without hardware. So they get the tests.

[NEEDS VERIFICATION] These packets are BUILT to the E1.31 spec by _data_packet
below, not captured from the rig. That makes these round-trip tests: they prove
the parser agrees with our reading of the standard, and would NOT catch a case
where that reading is wrong in the same direction for both. Replace the builders
with captured hex constants once a capture exists, and mark this [VERIFIED].
"""

import struct

import pytest

from app.sacn_listener import (
    UniverseRegistry,
    parse_data_packet,
    parse_discovery_packet,
    _universe_group,
)

CID = bytes(range(16))


def _root(vector: int, length: int = 638) -> bytes:
    pkt = bytearray(38)
    pkt[0:2] = struct.pack('!H', 0x0010)          # preamble size
    pkt[2:4] = struct.pack('!H', 0x0000)          # postamble size
    pkt[4:16] = b'ASC-E1.17\x00\x00\x00'          # ACN packet identifier
    pkt[16:18] = struct.pack('!H', 0x7000 | length)
    pkt[18:22] = struct.pack('!I', vector)
    pkt[22:38] = CID
    return bytes(pkt)


def _data_packet(universe=1, name='Processor, Netnumber 2, Output 1',
                 priority=100, sequence=7, options=0, slots=512):
    pkt = bytearray(_root(0x00000004))
    pkt += bytearray(638 - 38)
    pkt[38:40] = struct.pack('!H', 0x7000 | 638)
    pkt[40:44] = struct.pack('!I', 0x00000002)    # framing vector
    pkt[44:108] = name.encode('utf-8').ljust(64, b'\x00')
    pkt[108] = priority
    pkt[109:111] = struct.pack('!H', 0)           # synchronization address
    pkt[111] = sequence
    pkt[112] = options
    pkt[113:115] = struct.pack('!H', universe)
    pkt[115:117] = struct.pack('!H', 0x7000 | (slots + 11))
    pkt[117] = 0x02                               # DMP vector
    return bytes(pkt)


def _discovery_packet(universes=(1, 2, 3), name='Console', page=0, last_page=0):
    pkt = bytearray(_root(0x00000008))
    pkt += bytearray(120 - 38)
    pkt[40:44] = struct.pack('!I', 0x00000002)    # framing vector
    pkt[44:108] = name.encode('utf-8').ljust(64, b'\x00')
    pkt[114:118] = struct.pack('!I', 0x00000001)  # discovery layer vector
    pkt[118] = page
    pkt[119] = last_page
    return bytes(pkt) + b''.join(struct.pack('!H', u) for u in universes)


# ── data packets ──

def test_data_packet_round_trip():
    got = parse_data_packet(_data_packet(universe=6, priority=120, sequence=42))
    assert got is not None
    assert got['universe'] == 6
    assert got['name'] == 'Processor, Netnumber 2, Output 1'
    assert got['priority'] == 120
    assert got['sequence'] == 42
    assert got['cid'] == CID.hex()
    assert got['preview'] is False
    assert got['terminated'] is False


def test_high_universe_number_is_big_endian():
    # A byte-order slip is invisible on universe 1 and obvious on 0x0102.
    assert parse_data_packet(_data_packet(universe=258))['universe'] == 258


def test_option_bits_follow_the_standard_not_the_design_doc():
    # E1.31-2018: bit 7 (0x80) preview, bit 6 (0x40) stream terminated.
    assert parse_data_packet(_data_packet(options=0x80))['preview'] is True
    assert parse_data_packet(_data_packet(options=0x80))['terminated'] is False
    assert parse_data_packet(_data_packet(options=0x40))['terminated'] is True
    assert parse_data_packet(_data_packet(options=0x40))['preview'] is False


def test_source_name_is_nul_terminated_not_padded_through():
    assert parse_data_packet(_data_packet(name='Hog'))['name'] == 'Hog'


@pytest.mark.parametrize('bad', [
    b'',
    b'\x00' * 125,                                       # one byte too short
    _data_packet()[:100],                                # truncated
    bytearray(_data_packet())[:4] + b'NOT-E1.17aaa' + bytes(_data_packet()[16:]),
])
def test_malformed_data_returns_none(bad):
    assert parse_data_packet(bytes(bad)) is None


def test_wrong_root_vector_returns_none():
    # A discovery packet must not parse as a data packet.
    assert parse_data_packet(_discovery_packet()) is None


def test_wrong_framing_vector_returns_none():
    pkt = bytearray(_data_packet())
    pkt[40:44] = struct.pack('!I', 0x00000099)
    assert parse_data_packet(bytes(pkt)) is None


# ── discovery packets ──

def test_discovery_round_trip():
    got = parse_discovery_packet(_discovery_packet(universes=(1, 2, 6, 258)))
    assert got is not None
    assert got['universes'] == [1, 2, 6, 258]
    assert got['name'] == 'Console'


def test_discovery_empty_universe_list_is_legal():
    got = parse_discovery_packet(_discovery_packet(universes=()))
    assert got is not None and got['universes'] == []


def test_discovery_ignores_trailing_odd_byte():
    got = parse_discovery_packet(_discovery_packet(universes=(1, 2)) + b'\x07')
    assert got['universes'] == [1, 2]


def test_data_packet_does_not_parse_as_discovery():
    assert parse_discovery_packet(_data_packet()) is None


# ── multicast group mapping ──

@pytest.mark.parametrize('universe,group', [
    (1, '239.255.0.1'),
    (16, '239.255.0.16'),
    (255, '239.255.0.255'),
    (256, '239.255.1.0'),
    (258, '239.255.1.2'),
])
def test_universe_group(universe, group):
    assert _universe_group(universe) == group


# ── registry, with an injected clock (no sleeping) ──

class FakeClock:
    def __init__(self):
        self.t = 1_000.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def registry(clock):
    return UniverseRegistry(clock=clock)


def _record(registry, universe=1, ip='10.0.0.2', priority=100, cid=None):
    packet = parse_data_packet(_data_packet(universe=universe, priority=priority))
    if cid:
        packet['cid'] = cid
    registry.record_data(packet, ip)


def test_source_is_active_then_goes_inactive_at_the_e131_timeout(registry, clock):
    _record(registry)
    assert registry.snapshot()[0]['sources'][0]['active'] is True
    clock.advance(3.0)                       # past SOURCE_ACTIVE_AGE 2.5
    snap = registry.snapshot()[0]
    assert snap['sources'][0]['active'] is False
    assert snap['active'] is False
    assert snap['priority'] is None          # no ACTIVE source -> no priority


def test_source_is_purged_after_15s(registry, clock):
    _record(registry)
    clock.advance(16.0)
    registry.expire()
    assert registry.snapshot() == []         # universe went too, never announced


def test_terminated_stream_drops_the_source_immediately(registry):
    _record(registry)
    terminated = parse_data_packet(_data_packet(universe=1, options=0x40))
    registry.record_data(terminated, '10.0.0.2')
    assert registry.snapshot()[0]['sources'] == []


def test_universe_priority_is_the_highest_among_active_sources(registry):
    _record(registry, priority=100, cid='a' * 32, ip='10.0.0.2')
    _record(registry, priority=180, cid='b' * 32, ip='10.0.0.3')
    snap = registry.snapshot()[0]
    assert snap['priority'] == 180
    assert [s['ip'] for s in snap['sources']] == ['10.0.0.3', '10.0.0.2']


def test_two_sources_on_one_universe_are_both_kept(registry):
    # This is the conflict a tech is looking for; collapsing them would hide it.
    _record(registry, cid='a' * 32, ip='10.0.0.2')
    _record(registry, cid='b' * 32, ip='10.0.0.3')
    assert len(registry.snapshot()[0]['sources']) == 2


def test_announced_universe_survives_with_no_sources(registry, clock):
    registry.record_discovery(parse_discovery_packet(_discovery_packet(universes=(4,))))
    clock.advance(30.0)
    registry.expire()
    assert [u['universe'] for u in registry.snapshot()] == [4]
    assert registry.snapshot()[0]['active'] is False


def test_announced_universe_is_purged_after_60s(registry, clock):
    registry.record_discovery(parse_discovery_packet(_discovery_packet(universes=(4,))))
    clock.advance(61.0)
    registry.expire()
    assert registry.snapshot() == []


def test_joins_track_announced_and_sourced_universes(registry, clock):
    registry.record_discovery(parse_discovery_packet(_discovery_packet(universes=(4,))))
    _record(registry, universe=9)
    assert registry.announced_universes() == {4, 9}
    clock.advance(61.0)                      # past JOIN_DROP_AGE
    assert registry.announced_universes() == set()


def test_universes_are_sorted_ascending(registry):
    for u in (7, 2, 300):
        _record(registry, universe=u)
    assert [u['universe'] for u in registry.snapshot()] == [2, 7, 300]


def test_rename_takes_the_newest_name(registry):
    _record(registry)
    renamed = parse_data_packet(_data_packet(universe=1, name='Renamed Desk'))
    registry.record_data(renamed, '10.0.0.2')
    sources = registry.snapshot()[0]['sources']
    assert len(sources) == 1 and sources[0]['name'] == 'Renamed Desk'
