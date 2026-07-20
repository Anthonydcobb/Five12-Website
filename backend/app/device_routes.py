"""Device integration routes — read-only telemetry for Starlink / Bolero /
Stardust (research doc 2026-07-04). One consistent surface, three adapters.

Sim mode: append ?sim=1 (or set FIVE12_DEVICE_SIM=1) to get fabricated,
realistic telemetry for development without the hardware.

Security: adapters only ever contact fixed or operator-configured PRIVATE
addresses (see integrations/__init__.require_private_host). No target is
ever taken from request input.
"""

from datetime import datetime

from flask import Blueprint, jsonify, request

from . import db
from .integrations import ALL_DEVICE_IDS, get_adapter, sim_enabled
from .models import NetworkDevice, PatchRow, PatchSheet

devices = Blueprint('devices', __name__, url_prefix='/api/devices')


def _adapter_or_404(device_id):
    adapter = get_adapter(device_id, sim_enabled(request.args))
    return adapter


@devices.get('')
def list_devices():
    """Auto-detect all known device types (the Network-Monitor extension:
    'we found a Starlink / a Bolero / a Stardust — open its dashboard')."""
    sim = sim_enabled(request.args)
    out = []
    for device_id in ALL_DEVICE_IDS:
        adapter = get_adapter(device_id, sim)
        det = adapter.detect()
        out.append({
            'id': adapter.id,
            'name': adapter.name,
            'found': det['found'],
            'address': det.get('address'),
            'detail': det.get('detail'),
            'sim': sim,
        })
    return jsonify(out)


@devices.get('/<device_id>/status')
def device_status(device_id):
    adapter = _adapter_or_404(device_id)
    if adapter is None:
        return jsonify({'error': 'unknown device'}), 404
    return jsonify(adapter.get_status())


@devices.get('/<device_id>/history')
def device_history(device_id):
    adapter = _adapter_or_404(device_id)
    if adapter is None:
        return jsonify({'error': 'unknown device'}), 404
    n = min(int(request.args.get('n', 240)), 2880)
    return jsonify(adapter.get_history(n))


@devices.get('/stardust/units')
def stardust_units():
    """All Stardust units on the network with their MAC + persisted label, so
    a physical unit is recognisable whatever DHCP IP it lands on."""
    adapter = get_adapter('stardust', sim_enabled(request.args))
    units = adapter.discover_units()
    macs = [u['mac'] for u in units if u.get('mac')]
    labels = {}
    if macs:
        for d in NetworkDevice.query.filter(NetworkDevice.mac_address.in_(macs)).all():
            labels[d.mac_address] = d.label
    for u in units:
        u['label'] = labels.get(u.get('mac'))
    return jsonify(units)


@devices.put('/stardust/label')
def stardust_set_label():
    """Set/clear a MAC-keyed label for a Stardust. Reuses the NetworkDevice
    table (same MAC-keyed store the Network Monitor labels use), so a label is
    shared across both views and survives IP changes and restarts."""
    body = request.get_json(silent=True) or {}
    mac = (body.get('mac') or '').strip().upper()
    label = (body.get('label') or '').strip()
    if not mac:
        return jsonify({'error': 'mac is required'}), 400
    dev = db.session.get(NetworkDevice, mac)
    if dev is None:
        dev = NetworkDevice(mac_address=mac, device_type='stardust')
        db.session.add(dev)
    dev.label = label or None
    dev.last_seen = datetime.utcnow()
    if dev.device_type in (None, '', 'unknown'):
        dev.device_type = 'stardust'
    db.session.commit()
    return jsonify({'mac': mac, 'label': dev.label})


@devices.get('/stardust/reconcile/<int:patch_id>')
def stardust_reconcile(patch_id):
    """RDM discovery vs PatchSheet — 'patched at U1/45 but reports U1/50'."""
    adapter = _adapter_or_404('stardust')
    sheet = PatchSheet.query.get(patch_id)
    if sheet is None:
        return jsonify({'error': 'patch sheet not found'}), 404
    rows = PatchRow.query.filter_by(patch_id=patch_id).all()
    result = adapter.reconcile(rows)
    result['patchSheetId'] = patch_id
    return jsonify(result)
