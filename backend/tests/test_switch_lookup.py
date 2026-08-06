"""Where is this device? — inverted from the switches' stored port maps.

The numbers below are the real measured situation on 2026-08-06. A device
appears in the forwarding database of EVERY switch on its path, so picking the
right one matters, and admitting when the best answer is still not an
attachment point matters more.
"""

from app import vendors


# Bolero Antenna #1 really is in CARL port 5 — one MAC behind that port.
# It ALSO appears behind two uplinks, with 73 and 74 other devices.
ANTENNA_1 = '00:19:7C:02:E0:5B'
# Bolero Antenna #3's best candidate is an uplink with 73 devices behind it.
# It is plugged into something else — most likely the switch that is offline.
ANTENNA_3 = '00:19:7C:15:E4:97'

SWITCHES = [
    {'mac': 'D0:69:9E:04:78:72', 'label': 'Luminex (CARL)', 'switchPorts': [
        {'port': 5, 'name': 'Port 5', 'link': 'up',
         'macs': [ANTENNA_1], 'deviceCount': 1},
        {'port': 12, 'name': 'Port 12', 'link': 'up',
         'macs': [ANTENNA_3] + [f'AA:BB:CC:00:00:{i:02X}' for i in range(73)],
         'deviceCount': 74},
    ]},
    {'mac': 'D0:69:9E:04:77:C8', 'label': 'Luminex', 'switchPorts': [
        {'port': 12, 'name': 'Port 12', 'link': 'up',
         'macs': [ANTENNA_1, ANTENNA_3] + [f'AA:BB:CC:00:00:{i:02X}' for i in range(71)],
         'deviceCount': 73},
    ]},
]


def test_a_directly_attached_device_resolves_to_its_real_port():
    hit = vendors.find_switch_port(ANTENNA_1, SWITCHES)
    assert hit['switchLabel'] == 'Luminex (CARL)'
    assert hit['port'] == 5
    assert hit['deviceCount'] == 1          # what proves it is direct


def test_a_device_seen_only_through_uplinks_reports_the_count_not_a_patch_point():
    """Antenna #3 is NOT in port 12 — 73 other devices share that port, so it
    is a path. The count is returned so the caller can say "behind", never
    "on". Losing it here is what would make the UI lie."""
    hit = vendors.find_switch_port(ANTENNA_3, SWITCHES)
    assert hit['deviceCount'] == 73
    assert hit['port'] == 12
    assert hit['switchMac'] == 'D0:69:9E:04:77:C8'   # the 73, not the 74


def test_a_device_no_switch_has_seen_returns_none():
    assert vendors.find_switch_port('00:00:00:00:00:01', SWITCHES) is None


def test_the_lookup_is_case_insensitive():
    """MACs reach us from SNMP uppercase and from the device table in mixed
    case; a case mismatch would silently report every device as unseen."""
    assert vendors.find_switch_port(ANTENNA_1.lower(), SWITCHES)['port'] == 5


def test_a_switch_with_no_stored_map_is_skipped_not_crashed():
    switches = [{'mac': 'D0:69:9E:04:75:B9', 'label': 'Luminex'}] + SWITCHES
    assert vendors.find_switch_port(ANTENNA_1, switches)['port'] == 5


def test_a_tie_in_device_count_resolves_the_same_way_regardless_of_input_order():
    """Two switches report the SAME lowest deviceCount for a MAC. Which one
    wins must depend only on the data (switch MAC, then port number), never
    on which switch happened to be queried — or come back from the database
    — first. A non-deterministic answer here would read as the device having
    moved between switches on a refresh where nothing physically changed."""
    mac = '00:11:22:33:44:55'
    switch_a = {'mac': 'AA:AA:AA:AA:AA:AA', 'label': 'Switch A', 'switchPorts': [
        {'port': 3, 'name': 'Port 3', 'link': 'up', 'macs': [mac], 'deviceCount': 1},
    ]}
    switch_b = {'mac': 'BB:BB:BB:BB:BB:BB', 'label': 'Switch B', 'switchPorts': [
        {'port': 1, 'name': 'Port 1', 'link': 'up', 'macs': [mac], 'deviceCount': 1},
    ]}
    forward = vendors.find_switch_port(mac, [switch_a, switch_b])
    reversed_ = vendors.find_switch_port(mac, [switch_b, switch_a])
    assert forward == reversed_
    # Switch A's MAC sorts first, so it is the stable, documented winner.
    assert forward['switchMac'] == 'AA:AA:AA:AA:AA:AA'


def test_a_null_device_count_falls_back_to_the_length_of_macs_instead_of_crashing():
    """deviceCount present but explicitly None is a plausible shape for a
    nullable or half-written JSON column. It must not blow up the
    comparison against a genuine integer count from another port."""
    mac = '00:11:22:33:44:55'
    switches = [
        {'mac': 'AA:AA:AA:AA:AA:AA', 'label': 'Switch A', 'switchPorts': [
            {'port': 3, 'name': 'Port 3', 'link': 'up', 'macs': [mac], 'deviceCount': None},
        ]},
        {'mac': 'BB:BB:BB:BB:BB:BB', 'label': 'Switch B', 'switchPorts': [
            {'port': 1, 'name': 'Port 1', 'link': 'up', 'macs': [mac], 'deviceCount': 5},
        ]},
    ]
    hit = vendors.find_switch_port(mac, switches)
    # None falls back to len(macs) == 1, which beats the genuine count of 5.
    assert hit['deviceCount'] == 1
    assert hit['switchMac'] == 'AA:AA:AA:AA:AA:AA'


def test_a_non_string_entry_in_macs_is_skipped_not_crashed():
    """macs is a stored JSON list; a malformed element inside it (e.g. a
    null slipped in by a half-written row) must be skipped, not crash the
    whole lookup for every device behind that port."""
    mac = '00:11:22:33:44:55'
    switches = [
        {'mac': 'AA:AA:AA:AA:AA:AA', 'label': 'Switch A', 'switchPorts': [
            {'port': 3, 'name': 'Port 3', 'link': 'up',
             'macs': [mac, None], 'deviceCount': 2},
        ]},
    ]
    hit = vendors.find_switch_port(mac, switches)
    assert hit['port'] == 3
    assert hit['deviceCount'] == 2


def test_a_tie_with_a_missing_port_number_does_not_crash():
    """Two ports on the SAME switch tie on deviceCount, so the tie-break
    falls through to the port number. If one port dict is missing its
    'port' key entirely — the same half-written-row shape that forced the
    deviceCount and macs-element defenses above — the comparison must not
    reach `None < int` and raise. It must still return an answer."""
    mac = '00:11:22:33:44:55'
    switches = [
        {'mac': 'AA:AA:AA:AA:AA:AA', 'label': 'Switch A', 'switchPorts': [
            {'name': 'No Port Field', 'link': 'up',
             'macs': [mac], 'deviceCount': 1},
            {'port': 5, 'name': 'Port 5', 'link': 'up',
             'macs': [mac], 'deviceCount': 1},
        ]},
    ]
    hit = vendors.find_switch_port(mac, switches)
    assert hit is not None


def test_unusable_device_count_falls_back_to_the_deduped_seen_count():
    """When deviceCount is unusable, the fallback must count the VETTED set
    of real MAC strings, not the raw macs list. A junk (non-string) entry
    sitting alongside one real MAC must not inflate a genuinely single
    device port's reported count from 1 to 2 — that misclassification is
    exactly what turns "on Port X" into a false "shared with others"."""
    mac = '00:11:22:33:44:55'
    switches = [
        {'mac': 'AA:AA:AA:AA:AA:AA', 'label': 'Switch A', 'switchPorts': [
            {'port': 3, 'name': 'Port 3', 'link': 'up',
             'macs': [mac, None], 'deviceCount': None},
        ]},
    ]
    hit = vendors.find_switch_port(mac, switches)
    assert hit['deviceCount'] == 1
