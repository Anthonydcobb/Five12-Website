"""OUI classification and vendor enrichment.

The ACPD fixtures below are the real bodies served by the rack on the sACN
segment (10.9.15.101-.121) on 2026-08-05, captured from the devices themselves
rather than composed by hand.
"""

from unittest.mock import patch

from app import vendors


# Verbatim GET http://10.9.15.101/model/device — 15 identical units answered
# this, same firmware on every one.
ACPD_MODEL_DEVICE = {
    'modelName': 'PDXND-4-1',
    'bootSwVersionStr': 'V01.03.1.baadd5.745838908',
    'swVersionStr': 'V01.06.2.ee8877.992774699',
    'hwVersionStr': 'V01.00-b',
    'macAddresses': ['04:11:19:90:01:c0'],
    'uids': ['006f:00020700', '006f:00020701', '006f:00020702', '006f:00020703'],
    'longArtNetName': 'ACPD NODE ENET/DMX (PDXND-4-1)',
    'shortArtNetName': 'PDXND-4-1',
    'artNetMode': 1,
}


class _Resp:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_acpd_oui_is_classified():
    """04:11:19 was 'unknown', so fifteen DMX nodes sat unnamed in the Network
    tab. The OUI is not in the IEEE registry snapshot scapy ships, so the
    identification comes from the devices' own /model/device report."""
    assert vendors.detect_vendor_type('04:11:19:90:00:9B') == 'acpd'


def test_acpd_oui_is_classified_in_dash_form():
    assert vendors.detect_vendor_type('04-11-19-90-00-9B') == 'acpd'


def test_acpd_lowercase_mac_is_classified():
    assert vendors.detect_vendor_type('04:11:19:90:01:c0') == 'acpd'


def test_a_neighbouring_oui_is_not_swept_in():
    """The map is keyed on the full 3-octet OUI, not a 2-octet prefix. 04:11:1A
    belongs to somebody else and must not inherit this label."""
    assert vendors.detect_vendor_type('04:11:1A:00:00:01') == 'unknown'


def test_acpd_enrichment_reads_the_device_report():
    """These nodes serve the same /model/device contract the Swisson enricher
    already speaks, so the type must reach an enricher rather than fall through
    to {} — that is what puts model, firmware and port count in the tab."""
    with patch('app.vendors.requests.get', return_value=_Resp(ACPD_MODEL_DEVICE)):
        data = vendors.enrich_device('10.9.15.101', '04:11:19:90:01:C0', 'acpd')

    assert data['model'] == 'PDXND-4-1'
    assert data['firmware'] == 'V01.06.2.ee8877.992774699'
    assert data['hwVersion'] == 'V01.00-b'
    assert data['portCount'] == 4          # one per RDM UID
    assert data['longName'] == 'ACPD NODE ENET/DMX (PDXND-4-1)'


def test_acpd_enrichment_survives_an_unreachable_node():
    """A node that has gone offline must yield {} rather than raise — the
    scanner enriches inside the sweep and one dead device cannot take it down."""
    with patch('app.vendors.requests.get', side_effect=OSError('unreachable')):
        assert vendors.enrich_device('10.9.15.101', '04:11:19:90:01:C0', 'acpd') == {}


def test_known_ouis_still_classify():
    """Guards the table itself against a careless edit."""
    assert vendors.detect_vendor_type('28:94:01:00:00:01') == 'netgear'
    assert vendors.detect_vendor_type('00:19:7C:00:00:01') == 'bolero'
    assert vendors.detect_vendor_type('E4:5F:01:00:00:01') == 'stardust'


def test_an_unmapped_oui_is_unknown():
    assert vendors.detect_vendor_type('AA:BB:CC:00:00:01') == 'unknown'


def test_acronym_types_keep_their_case_in_display():
    """The scanner auto-labels from the type, and str.capitalize() turns an
    acronym into 'Acpd'. Types that are acronyms need their real casing."""
    assert vendors.display_name('acpd') == 'ACPD'


def test_display_name_falls_back_to_capitalize():
    """Types that are ordinary words keep the existing behaviour, so this
    change cannot quietly restyle every other label in the tab."""
    assert vendors.display_name('netgear') == 'Netgear'
    assert vendors.display_name('swisson') == 'Swisson'
    assert vendors.display_name('unknown') == 'Unknown'


# Verbatim GET http://10.31.8.51/model/status on 2026-08-05, the Swisson
# XND-8. Universes 21/42/91/104 on ports 1-4 matched the device's own web
# GUI in a screenshot taken at the same moment.
XND8_MODEL_STATUS = {
    'modelName': 'XND-8',
    'locate': False,
    'longArtNetName': 'SWISSON XND-8',
    'artNetMode': 1,
    'addressDisplayMode': 0,
    'ports': [
        {'status': 3, 'direction': 1, 'protocol': 2, 'universe': 21},
        {'status': 3, 'direction': 1, 'protocol': 2, 'universe': 42},
        {'status': 3, 'direction': 1, 'protocol': 2, 'universe': 91},
        {'status': 3, 'direction': 1, 'protocol': 2, 'universe': 104},
        {'status': 3, 'direction': 1, 'protocol': 2, 'universe': 44},
        {'status': 3, 'direction': 1, 'protocol': 2, 'universe': 41},
        {'status': 3, 'direction': 1, 'protocol': 2, 'universe': 41},
        {'status': 3, 'direction': 1, 'protocol': 2, 'universe': 1},
    ],
}

# Verbatim GET http://10.9.15.101/model/status on 2026-08-05. Same contract,
# four ports instead of eight — which is why one reader serves both vendors.
ACPD_MODEL_STATUS = {
    'modelName': 'PDXND-4-1',
    'locate': False,
    'longArtNetName': 'ACPD NODE ENET/DMX (PDXND-4-1)',
    'artNetMode': 1,
    'addressDisplayMode': 0,
    'ports': [
        {'status': 3, 'direction': 1, 'protocol': 2, 'universe': 1},
        {'status': 3, 'direction': 1, 'protocol': 2, 'universe': 2},
        {'status': 3, 'direction': 1, 'protocol': 2, 'universe': 3},
        {'status': 3, 'direction': 1, 'protocol': 2, 'universe': 4},
    ],
}


def test_port_status_numbers_ports_from_one():
    """Array index is the port number, zero-based — the operator reads
    "Port 1" off the node's front panel, so the API must say 1, not 0."""
    with patch('app.vendors.requests.get', return_value=_Resp(XND8_MODEL_STATUS)):
        ports = vendors.read_port_status('10.31.8.51')['ports']

    assert len(ports) == 8
    assert [p['port'] for p in ports] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert [p['universe'] for p in ports] == [21, 42, 91, 104, 44, 41, 41, 1]


def test_port_status_decodes_confirmed_enums():
    with patch('app.vendors.requests.get', return_value=_Resp(XND8_MODEL_STATUS)):
        port1 = vendors.read_port_status('10.31.8.51')['ports'][0]

    assert port1['protocol'] == 'sACN'
    assert port1['direction'] == 'Output'
    assert port1['status'] == 'OK'


def test_port_status_reads_the_acpd_identically():
    """Both vendors serve this contract, so one reader covers all 16 nodes."""
    with patch('app.vendors.requests.get', return_value=_Resp(ACPD_MODEL_STATUS)):
        ports = vendors.read_port_status('10.9.15.101')['ports']

    assert len(ports) == 4
    assert [p['universe'] for p in ports] == [1, 2, 3, 4]


def test_an_unseen_code_is_shown_raw_not_guessed():
    """Every one of the 68 ports on the rig reads status 3 / direction 1 /
    protocol 2, so input, disabled and dead ports are genuinely undecoded. A
    confidently wrong status on a troubleshooting screen is worse than a raw
    number, because the operator stops looking at it."""
    payload = {'ports': [{'status': 9, 'direction': 7, 'protocol': 5, 'universe': 12}]}
    with patch('app.vendors.requests.get', return_value=_Resp(payload)):
        port1 = vendors.read_port_status('10.31.8.51')['ports'][0]

    assert port1['status'] == 'code 9'
    assert port1['direction'] == 'code 7'
    assert port1['protocol'] == 'code 5'
    assert port1['universe'] == 12       # the row is still emitted


def test_port_status_survives_an_unreachable_node():
    """The scanner enriches inside the sweep; one dead node cannot raise."""
    with patch('app.vendors.requests.get', side_effect=OSError('unreachable')):
        assert vendors.read_port_status('10.31.8.51') == {}


def test_port_status_ignores_a_body_without_ports():
    """A node answering some other JSON must yield {} rather than a KeyError,
    so the caller's `if vendor_data:` guard keeps the last known patch."""
    with patch('app.vendors.requests.get', return_value=_Resp({'modelName': 'XND-8'})):
        assert vendors.read_port_status('10.31.8.51') == {}


def test_enrichment_attaches_ports_to_vendor_data():
    """This is what puts the table in the Network tab — reached through the
    same enricher both vendors already share for /model/device."""
    with patch('app.vendors.requests.get', return_value=_Resp(XND8_MODEL_STATUS)):
        data = vendors.enrich_device('10.31.8.51', '28:36:38:C0:39:C0', 'swisson')

    assert [p['universe'] for p in data['ports']] == [21, 42, 91, 104, 44, 41, 41, 1]


def test_port_status_survives_a_non_dict_port_entry():
    """A node answering HTTP 200 with a `ports` array that has a malformed
    element (a bare string instead of a port object) used to raise
    AttributeError from `p.get(...)` — the comprehension ran outside the
    try/except, so a single bad element aborted the whole subnet sweep,
    including its stale-device prune, every cycle until the node was fixed."""
    payload = {
        'ports': [
            {'status': 3, 'direction': 1, 'protocol': 2, 'universe': 21},
            'garbage-not-a-dict',
        ],
    }
    with patch('app.vendors.requests.get', return_value=_Resp(payload)):
        assert vendors.read_port_status('10.31.8.51') == {}


def test_port_status_survives_an_unhashable_enum_value():
    """`table.get(code, ...)` raises TypeError when `code` is unhashable (a
    node reporting a list where an int enum code is expected). Same failure
    mode as the non-dict element above: it must yield {} rather than raise,
    so one malformed node cannot take down the rest of the subnet sweep."""
    payload = {'ports': [{'status': [], 'direction': 1, 'protocol': 2, 'universe': 21}]}
    with patch('app.vendors.requests.get', return_value=_Resp(payload)):
        assert vendors.read_port_status('10.31.8.51') == {}


def _model_device_only(url, **kwargs):
    """URL-discriminating mock: /model/device answers, /model/status fails."""
    if url.endswith('/model/device'):
        return _Resp(ACPD_MODEL_DEVICE)
    raise OSError('unreachable')


def _model_status_only(url, **kwargs):
    """URL-discriminating mock: /model/status answers, /model/device fails."""
    if url.endswith('/model/status'):
        return _Resp(ACPD_MODEL_STATUS)
    raise OSError('unreachable')


def test_enrichment_keeps_device_fields_when_status_endpoint_fails():
    """/model/device and /model/status are merged independently so a node
    answering one but not the other still contributes what it has. Every
    existing test mocks both endpoints with the same body, so this behaviour
    was never actually pinned — a node with /model/status down (but /model/device
    up) must still surface model/firmware/hwVersion/portCount/longName."""
    with patch('app.vendors.requests.get', side_effect=_model_device_only):
        data = vendors._enrich_model_device_api('10.9.15.101')

    assert data['model'] == 'PDXND-4-1'
    assert data['firmware'] == 'V01.06.2.ee8877.992774699'
    assert data['hwVersion'] == 'V01.00-b'
    assert data['portCount'] == 4
    assert data['longName'] == 'ACPD NODE ENET/DMX (PDXND-4-1)'
    assert 'ports' not in data


def test_enrichment_keeps_ports_when_device_endpoint_fails():
    """Mirror of the above: a node with /model/device down (but /model/status
    up) must still surface the per-port table."""
    with patch('app.vendors.requests.get', side_effect=_model_status_only):
        data = vendors._enrich_model_device_api('10.9.15.101')

    assert [p['universe'] for p in data['ports']] == [1, 2, 3, 4]
    assert 'model' not in data
