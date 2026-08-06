"""A missed /model/status poll must not erase a node's stored patch.

Spec goal 3: "When a node stops answering, the last known patch is shown and
clearly labelled as stale rather than blanked or silently presented as
current."

This file exists because every OTHER test of that guarantee sits at the
`read_port_status` level, where the function merely returns {} — it has no
access to the caller, to the two-endpoint merge, or to the database, so it
cannot observe whether the stored patch actually survives. The guard lives in
`_process_discovered_device`, and nothing tested it.

The failure it now pins: `_enrich_model_device_api` merges two independent
GETs. When /model/device answers 200 and /model/status does not, the merged
result is TRUTHY but carries no `ports` key — so a wholesale
`device.vendor_data = vendor_data` deleted the last known patch of a node that
is up, pingable, and answering half its endpoints. The panel then rendered
nothing at all, with no message, for 300s or permanently.
"""

from datetime import datetime
from unittest.mock import patch

import pytest

from app.models import NetworkDevice
from app.scanner import _process_discovered_device


# 04:11:19 is the ACPD OUI, so this MAC routes through the shared
# /model/device + /model/status enricher — the real code path, not a stub.
ACPD_MAC = '04:11:19:90:01:C0'
ACPD_IP = '10.9.15.101'

MODEL_DEVICE = {
    'modelName': 'PDXND-4-1',
    'swVersionStr': 'V01.06.2.ee8877.992774699',
    'hwVersionStr': 'V01.00-b',
    'uids': ['006f:00020700', '006f:00020701', '006f:00020702', '006f:00020703'],
    'longArtNetName': 'ACPD NODE ENET/DMX (PDXND-4-1)',
}

MODEL_STATUS = {
    'modelName': 'PDXND-4-1',
    'ports': [
        {'status': 3, 'direction': 1, 'protocol': 2, 'universe': 11},
        {'status': 3, 'direction': 1, 'protocol': 2, 'universe': 12},
        {'status': 3, 'direction': 1, 'protocol': 2, 'universe': 13},
        {'status': 3, 'direction': 1, 'protocol': 2, 'universe': 14},
    ],
}

STORED_PORTS = [
    {'port': 1, 'universe': 21, 'protocol': 'sACN', 'direction': 'Output', 'status': 'OK'},
    {'port': 2, 'universe': 42, 'protocol': 'sACN', 'direction': 'Output', 'status': 'OK'},
]
STORED_AS_OF = '2026-08-05T18:00:00Z'
STORED_FIRMWARE = 'V01.05.9.old'


class _Resp:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _device_up_status_down(url, **kwargs):
    """The incident, verbatim: /model/device answers, /model/status times out.

    Two GETs 3s apart to a node that is also pushing DMX; one of them misses.
    """
    if url.endswith('/model/device'):
        return _Resp(MODEL_DEVICE)
    raise OSError('timed out')


def _both_up(url, **kwargs):
    if url.endswith('/model/device'):
        return _Resp(MODEL_DEVICE)
    return _Resp(MODEL_STATUS)


def _status_up_device_down(url, **kwargs):
    """The mirror incident: /model/status answers, /model/device times out."""
    if url.endswith('/model/status'):
        return _Resp(MODEL_STATUS)
    raise OSError('timed out')


@pytest.fixture
def node(db):
    row = NetworkDevice(
        mac_address=ACPD_MAC,
        device_type='acpd',
        last_ip=ACPD_IP,
        last_seen=datetime.utcnow(),
        vendor_data={'model': 'PDXND-4-1', 'firmware': STORED_FIRMWARE,
                     'ports': STORED_PORTS, 'portsAsOf': STORED_AS_OF},
    )
    db.session.add(row)
    db.session.commit()
    yield row
    db.session.delete(row)
    db.session.commit()


def test_a_status_endpoint_miss_does_not_erase_the_stored_patch(app, db, node):
    """The regression. A truthy-but-portless enrichment must not blank the
    patch of a node that is still up."""
    with patch('app.vendors.requests.get', side_effect=_device_up_status_down) as get:
        _process_discovered_device(ACPD_IP, ACPD_MAC, None, app)

    # Prove the discriminator did work — both endpoints were really attempted.
    urls = [c.args[0] for c in get.call_args_list]
    assert any(u.endswith('/model/device') for u in urls)
    assert any(u.endswith('/model/status') for u in urls)

    db.session.refresh(node)
    assert node.vendor_data['ports'] == STORED_PORTS
    # The half of the enrichment that DID answer still lands.
    assert node.vendor_data['firmware'] == 'V01.06.2.ee8877.992774699'


def test_a_preserved_patch_keeps_its_own_timestamp(app, db, node):
    """Carrying the ports forward without their `portsAsOf` would leave the
    route reporting a preserved patch under whatever timestamp came next —
    an old patch presented as recent, which is the same spec violation the
    carry-forward exists to prevent."""
    with patch('app.vendors.requests.get', side_effect=_device_up_status_down):
        _process_discovered_device(ACPD_IP, ACPD_MAC, None, app)

    db.session.refresh(node)
    assert node.vendor_data['portsAsOf'] == STORED_AS_OF


def test_a_successful_status_read_still_replaces_the_stored_patch(app, db, node):
    """The carry-forward must not pin a stale patch in place: when the node
    answers, the fresh reading wins and gets a fresh timestamp."""
    with patch('app.vendors.requests.get', side_effect=_both_up):
        _process_discovered_device(ACPD_IP, ACPD_MAC, None, app)

    db.session.refresh(node)
    assert [p['universe'] for p in node.vendor_data['ports']] == [11, 12, 13, 14]
    assert node.vendor_data['portsAsOf'] != STORED_AS_OF
    assert node.vendor_data['portsAsOf'].endswith('Z')


def test_a_node_that_never_had_a_patch_gains_no_ports_key(app, db):
    """The carry-forward only preserves what was actually there — it must not
    fabricate an empty `ports` list on a node that has never reported one."""
    row = NetworkDevice(mac_address='04:11:19:90:01:C1', device_type='acpd',
                        last_ip='10.9.15.102')
    db.session.add(row)
    db.session.commit()
    try:
        with patch('app.vendors.requests.get', side_effect=_device_up_status_down):
            _process_discovered_device('10.9.15.102', '04:11:19:90:01:C1', None, app)

        db.session.refresh(row)
        assert 'ports' not in row.vendor_data
        assert row.vendor_data['model'] == 'PDXND-4-1'
    finally:
        db.session.delete(row)
        db.session.commit()


def test_a_device_endpoint_miss_does_not_erase_the_stored_model_fields(app, db, node):
    """The mirror of the regression above: /model/device times out while
    /model/status answers. The first fix carried only `ports` forward, so
    this direction was still a wholesale `device.vendor_data = vendor_data`
    that deleted model/firmware/hwVersion/portCount/longName from a node that
    is up and pingable — FIRMWARE and HW VERSION went blank, and a
    first-seen node in this window got stuck labelled "ACPD" forever, never
    "ACPD PDXND-4-1", because the auto-label branch only fires once."""
    with patch('app.vendors.requests.get', side_effect=_status_up_device_down) as get:
        _process_discovered_device(ACPD_IP, ACPD_MAC, None, app)

    urls = [c.args[0] for c in get.call_args_list]
    assert any(u.endswith('/model/device') for u in urls)
    assert any(u.endswith('/model/status') for u in urls)

    db.session.refresh(node)
    # The stored model/firmware survive the /model/device miss.
    assert node.vendor_data['model'] == 'PDXND-4-1'
    assert node.vendor_data['firmware'] == STORED_FIRMWARE
    # The half that DID answer still lands, with a fresh timestamp.
    assert [p['universe'] for p in node.vendor_data['ports']] == [11, 12, 13, 14]
    assert node.vendor_data['portsAsOf'] != STORED_AS_OF
