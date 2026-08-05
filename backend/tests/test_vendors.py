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
