"""Read-only per-port device map for Luminex GigaCore switches.

The fixtures are verbatim SNMP payloads captured from the GigaCore12 at
172.16.1.21 ("CARL") on 2026-08-06, not composed by hand. The forwarding
database is a LIVE, ageing table — CARL's uplink read 79 MACs in one probe
and 74 minutes later — so these are frozen captures and no test here may
assert that a real switch still reports a given number.
"""

from unittest.mock import patch

from app import vendors


# dot1dTpFdbPort, 1.3.6.1.2.1.17.4.3.1.2 — OID suffix is the six octets of
# the MAC in decimal; the value is the BRIDGE port number (not ifIndex).
GIGACORE_FDB = {
    '0.25.124.2.224.91': 5,        # 00:19:7C:02:E0:5B  Bolero antenna
    '0.25.124.2.225.86': 6,        # 00:19:7C:02:E1:56  Bolero antenna
    '0.25.124.21.228.151': 11,     # 00:19:7C:15:E4:97  not in the device table
    '0.224.76.48.126.254': 1,      # 00:E0:4C:30:7E:FE
    '4.17.25.144.1.192': 12,       # 04:11:19:90:01:C0  ACPD, via the uplink
    '40.54.56.192.57.192': 12,     # 28:36:38:C0:39:C0  Swisson, via the uplink
    # Bridge port 0 is the switch's OWN management MAC. It has no
    # dot1dBasePortIfIndex entry and is not a physical port.
    '208.105.158.4.120.114': 0,    # D0:69:9E:04:78:72  CARL itself
}

# dot1dBasePortIfIndex — bridge port -> ifIndex. Note there is no entry for 0.
GIGACORE_BP2IF = {str(i): i for i in range(1, 13)}

# ifDescr — BYTES, and the real device pads to a fixed width: b'Port  1'.
GIGACORE_IFDESCR = {str(i): f'Port {i:>2}'.encode() for i in range(1, 13)}

# ifOperStatus — 1 is up, 2 is down.
GIGACORE_IFOPER = {str(i): (1 if i in (1, 5, 6, 11, 12) else 2) for i in range(1, 13)}


def _fake_walks(fdb=None):
    """Dispatch a walk by OID, the way a real switch would."""
    tables = {
        '1.3.6.1.2.1.17.4.3.1.2': GIGACORE_FDB if fdb is None else fdb,
        '1.3.6.1.2.1.17.1.4.1.2': GIGACORE_BP2IF,
        '1.3.6.1.2.1.2.2.1.2': GIGACORE_IFDESCR,
        '1.3.6.1.2.1.2.2.1.8': GIGACORE_IFOPER,
    }
    def walk(ip, oid):
        return dict(tables[oid])
    return walk


def test_suffix_walk_keeps_the_whole_mac():
    """_snmp_walk_map keys on the LAST OID arc, which is right for interface
    tables indexed by one integer and destroys the FDB, whose index is the six
    octets of a MAC — it would return '91' where the answer is a device."""
    rows = [('1.3.6.1.2.1.17.4.3.1.2.0.25.124.2.224.91', 5)]

    class _Row:
        def __init__(self, oid, value):
            self.oid, self.value = oid, value

    # Patch the module attribute itself, not `.walk` beneath it: on the
    # default test interpreter (no puresnmp installed) `vendors.puresnmp` is
    # None, and patching an attribute of None raises AttributeError before
    # the test body ever runs. Patching the name wholesale replaces it with
    # a MagicMock regardless of what it currently holds, on both
    # interpreters, and still exercises the real `_snmp_walk_suffix` body.
    with patch('app.vendors.puresnmp') as mock_puresnmp:
        mock_puresnmp.walk.return_value = [_Row(*r) for r in rows]
        out = vendors._snmp_walk_suffix('172.16.1.21', '1.3.6.1.2.1.17.4.3.1.2')

    assert out == {'0.25.124.2.224.91': 5}


def test_a_single_mac_port_names_one_device():
    with patch('app.vendors._snmp_walk_suffix', side_effect=lambda ip, oid: _fake_walks()(ip, oid)), \
         patch('app.vendors._snmp_walk_map', side_effect=lambda ip, oid: _fake_walks()(ip, oid)):
        ports = vendors.read_switch_ports('172.16.1.21')['switchPorts']

    p5 = next(p for p in ports if p['port'] == 5)
    assert p5['macs'] == ['00:19:7C:02:E0:5B']
    assert p5['deviceCount'] == 1
    assert p5['name'] == 'Port 5'          # collapsed from b'Port  5'
    assert p5['link'] == 'up'


def test_an_uplink_port_keeps_every_mac_and_its_count():
    """The count is what lets the UI refuse to call this a patch point."""
    with patch('app.vendors._snmp_walk_suffix', side_effect=lambda ip, oid: _fake_walks()(ip, oid)), \
         patch('app.vendors._snmp_walk_map', side_effect=lambda ip, oid: _fake_walks()(ip, oid)):
        ports = vendors.read_switch_ports('172.16.1.21')['switchPorts']

    p12 = next(p for p in ports if p['port'] == 12)
    assert p12['deviceCount'] == 2
    assert sorted(p12['macs']) == ['04:11:19:90:01:C0', '28:36:38:C0:39:C0']


def test_the_switchs_own_mac_is_not_given_a_port():
    """Bridge port 0 has no dot1dBasePortIfIndex entry — it is the switch's
    management MAC, not a physical port. Rendering it as a mystery port would
    invent hardware that does not exist."""
    with patch('app.vendors._snmp_walk_suffix', side_effect=lambda ip, oid: _fake_walks()(ip, oid)), \
         patch('app.vendors._snmp_walk_map', side_effect=lambda ip, oid: _fake_walks()(ip, oid)):
        ports = vendors.read_switch_ports('172.16.1.21')['switchPorts']

    every_mac = [m for p in ports for m in p['macs']]
    assert 'D0:69:9E:04:78:72' not in every_mac
    assert all(p['port'] != 0 for p in ports)


def test_every_physical_port_appears_even_with_nothing_on_it():
    """An empty port is a fact worth showing — it is how you find a free one."""
    with patch('app.vendors._snmp_walk_suffix', side_effect=lambda ip, oid: _fake_walks()(ip, oid)), \
         patch('app.vendors._snmp_walk_map', side_effect=lambda ip, oid: _fake_walks()(ip, oid)):
        ports = vendors.read_switch_ports('172.16.1.21')['switchPorts']

    assert [p['port'] for p in ports] == list(range(1, 13))
    p2 = next(p for p in ports if p['port'] == 2)
    assert p2['macs'] == [] and p2['deviceCount'] == 0 and p2['link'] == 'down'


def test_the_read_is_stamped_with_its_own_time():
    with patch('app.vendors._snmp_walk_suffix', side_effect=lambda ip, oid: _fake_walks()(ip, oid)), \
         patch('app.vendors._snmp_walk_map', side_effect=lambda ip, oid: _fake_walks()(ip, oid)):
        data = vendors.read_switch_ports('172.16.1.21')

    assert data['switchPortsAsOf'].endswith('Z')


def test_an_unreachable_switch_yields_empty_not_an_exception():
    """172.16.1.12 answers neither SNMP nor HTTP. This runs inside the sweep;
    one dead switch must not take it down, and the scanner's merge keeps the
    last good map only if we return {} rather than a partial one."""
    with patch('app.vendors._snmp_walk_suffix', side_effect=OSError('timeout')):
        assert vendors.read_switch_ports('172.16.1.12') == {}


def test_a_switch_with_no_bridge_table_yields_empty():
    with patch('app.vendors._snmp_walk_suffix', return_value={}), \
         patch('app.vendors._snmp_walk_map', return_value={}):
        assert vendors.read_switch_ports('172.16.1.21') == {}


class _NotIntConvertible:
    """Stands in for an unexpected ASN.1 type puresnmp could hand back — it
    stringifies to a plausible bridge-port number but has no __int__, so
    int() on it raises TypeError rather than ValueError."""
    def __str__(self):
        return '5'


def test_a_non_integer_bridge_port_key_yields_empty_not_an_exception():
    """dot1dBasePortIfIndex keyed by something int() can't parse — a
    malformed MIB response or firmware quirk — used to raise ValueError out
    of `by_port = {int(bp): [] for bp in bp2if}`, which sat outside the
    function's try/except. That escapes read_switch_ports, contradicting its
    own 'returns {} on any failure' contract, and reaches enrich_device
    inside the scanner's per-subnet sweep — same failure class fixed for
    /model/status parsing in 7033761."""
    bad_bp2if = {'not-a-number': 1}
    with patch('app.vendors._snmp_walk_suffix', side_effect=lambda ip, oid: _fake_walks()(ip, oid)), \
         patch('app.vendors._snmp_walk_map', side_effect=lambda ip, oid: (
             bad_bp2if if oid == '1.3.6.1.2.1.17.1.4.1.2' else _fake_walks()(ip, oid)
         )):
        assert vendors.read_switch_ports('172.16.1.21') == {}


def test_a_non_integer_fdb_value_yields_empty_not_an_exception():
    """A forwarding-database entry whose bridge-port value passes the
    `str(bridge_port) not in bp2if` membership check (so it isn't skipped as
    a phantom port) but isn't int()-convertible used to raise TypeError out
    of `by_port[int(bridge_port)].append(mac)`, uncaught, for the same
    reason as above."""
    bad_fdb = {'0.25.124.2.224.91': _NotIntConvertible()}
    with patch('app.vendors._snmp_walk_suffix', side_effect=lambda ip, oid: _fake_walks(fdb=bad_fdb)(ip, oid)), \
         patch('app.vendors._snmp_walk_map', side_effect=lambda ip, oid: _fake_walks()(ip, oid)):
        assert vendors.read_switch_ports('172.16.1.21') == {}


def test_a_non_canonical_bp2if_key_yields_empty_not_an_exception():
    """dot1dBasePortIfIndex keyed by something that IS int()-convertible but
    doesn't round-trip through str(int(x)) == x — a leading zero like '05' —
    used to pass the `by_port` construction (int('05') == 5 succeeds) but
    then raise KeyError out of `bp2if[str(bridge_port)]` in the ports-build
    loop, which sat outside the try/except. Genuine puresnmp walk output
    always yields plain unsigned-decimal arcs, so this is a narrow case, but
    the function's contract is 'returns {} on any failure' and this loop is
    part of the same port-map derivation as the guarded block above it —
    same failure class fixed for /model/status parsing in 7033761."""
    odd_bp2if = {'05': 5}
    with patch('app.vendors._snmp_walk_suffix', side_effect=lambda ip, oid: _fake_walks()(ip, oid)), \
         patch('app.vendors._snmp_walk_map', side_effect=lambda ip, oid: (
             odd_bp2if if oid == '1.3.6.1.2.1.17.1.4.1.2' else _fake_walks()(ip, oid)
         )):
        assert vendors.read_switch_ports('172.16.1.21') == {}


def test_mac_from_oid_suffix_rejects_an_out_of_range_octet():
    """int('300') succeeds, so without an explicit range check this would
    format as '12C' and return a plausible-but-wrong MAC instead of being
    rejected — silently naming the wrong device on a port."""
    assert vendors._mac_from_oid_suffix('0.25.124.2.224.300') is None


def test_mac_from_oid_suffix_rejects_a_negative_octet():
    """int('-5') succeeds too, formatting as '-5' rather than a hex byte."""
    assert vendors._mac_from_oid_suffix('0.25.124.2.224.-5') is None


def test_the_vendors_module_issues_no_snmp_writes():
    """BINDING: the rig is live. This module may GET and WALK, never SET.

    Asserted against the module's own source so that ADDING a write fails the
    suite, rather than relying on nobody having called one during a test run.
    """
    import inspect
    src = inspect.getsource(vendors)
    for forbidden in ('puresnmp.set', 'puresnmp.multiset', '.bulkset('):
        assert forbidden not in src, f'SNMP write {forbidden!r} in vendors'
