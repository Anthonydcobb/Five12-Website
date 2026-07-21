from flask import Blueprint, jsonify, request
from datetime import datetime
from . import db
from .models import NetworkSubnet, NetworkDevice, LocationSnapshot, LocationDevice

net = Blueprint('network', __name__, url_prefix='/api/network')


@net.get('/subnets')
def list_subnets():
    subnets = NetworkSubnet.query.order_by(NetworkSubnet.id).all()
    return jsonify([s.to_dict() for s in subnets])


@net.post('/subnets')
def create_subnet():
    data = request.get_json()
    subnet = NetworkSubnet(
        label=data['label'],
        cidr=data['cidr'],
        interface_hint=data.get('interfaceHint'),
        color=data.get('color', '#7dd3fc'),
        ignore_cidrs=data.get('ignoreCidrs') or None,
    )
    db.session.add(subnet)
    db.session.commit()
    return jsonify(subnet.to_dict()), 201


@net.delete('/subnets/<int:subnet_id>')
def delete_subnet(subnet_id):
    subnet = db.session.get(NetworkSubnet, subnet_id)
    if subnet is None:
        return jsonify({'error': 'not found'}), 404
    NetworkDevice.query.filter_by(subnet_id=subnet_id).update({'subnet_id': None})
    db.session.delete(subnet)
    db.session.commit()
    return '', 204


@net.get('/devices')
def list_devices():
    """Hidden devices are omitted by default — that is what makes the
    "remove offline devices" button look like a removal. `?includeHidden=1`
    is the escape hatch for confirming a row still exists with its notes."""
    q = NetworkDevice.query
    if request.args.get('includeHidden') not in ('1', 'true'):
        q = q.filter(NetworkDevice.hidden.is_(False))
    devices = q.order_by(NetworkDevice.last_seen.desc()).all()
    return jsonify([d.to_dict() for d in devices])


@net.post('/subnets/<int:subnet_id>/clear-offline')
def clear_offline_devices(subnet_id):
    """Hide every offline device on one subnet. A HIDE, never a delete:
    label, notes and vendor data stay on the row, and the next sighting
    un-hides it (see scanner._process_discovered_device). Offline is
    scanner.OFFLINE_THRESHOLD, which matches the 90s the UI paints red."""
    from .scanner import OFFLINE_THRESHOLD

    subnet = db.session.get(NetworkSubnet, subnet_id)
    if subnet is None:
        return jsonify({'error': 'not found'}), 404

    cutoff = datetime.utcnow() - OFFLINE_THRESHOLD
    count = NetworkDevice.query.filter(
        NetworkDevice.subnet_id == subnet_id,
        NetworkDevice.hidden.is_(False),
        db.or_(NetworkDevice.last_seen.is_(None),
               NetworkDevice.last_seen < cutoff),
    ).update({'hidden': True}, synchronize_session=False)
    db.session.commit()
    return jsonify({'hidden': count})


@net.patch('/devices/<mac>')
def update_device(mac):
    device = db.session.get(NetworkDevice, mac)
    if device is None:
        return jsonify({'error': 'not found'}), 404
    data = request.get_json()
    if 'label' in data:
        device.label = data['label']
    if 'notes' in data:
        device.notes = data['notes']
    db.session.commit()
    return jsonify(device.to_dict())


@net.delete('/devices/<mac>')
def delete_device(mac):
    device = db.session.get(NetworkDevice, mac)
    if device is None:
        return jsonify({'error': 'not found'}), 404
    db.session.delete(device)
    db.session.commit()
    return '', 204


@net.post('/scan/trigger')
def trigger_scan():
    from flask import current_app
    from .scanner import run_scan_now
    import threading
    app = current_app._get_current_object()
    threading.Thread(target=run_scan_now, args=(app,), daemon=True).start()
    return jsonify({'status': 'scanning'}), 202


@net.get('/sacn')
def sacn_state():
    """Live E1.31 universes and their sources. In-memory only — see
    sacn_listener.py; nothing here touches the database.

    Returns listening=false with a reason rather than an empty list when the
    socket could not be opened, so the UI can distinguish "the wire is quiet"
    from "we never got to listen".
    """
    from .sacn_listener import get_listener
    listener = get_listener()
    if listener is None:
        return jsonify({'listening': False,
                        'error': 'sACN listener not started',
                        'interfaces': [], 'universes': []})
    return jsonify(listener.api_state())


@net.get('/locations')
def list_locations():
    locs = LocationSnapshot.query.order_by(LocationSnapshot.created_at.desc()).all()
    return jsonify([l.to_dict() for l in locs])


@net.post('/locations')
def create_location():
    data = request.get_json()
    snap = LocationSnapshot(name=data['name'], created_at=datetime.utcnow())
    db.session.add(snap)
    db.session.flush()

    devices = NetworkDevice.query.all()
    for dev in devices:
        ld = LocationDevice(
            location_id=snap.id,
            mac_address=dev.mac_address,
            ip_at_time=dev.last_ip,
            online_at_time=dev.last_seen is not None,
            vendor_data_at_time=dev.vendor_data,
        )
        db.session.add(ld)

    db.session.commit()
    return jsonify(snap.to_dict()), 201


@net.get('/locations/<int:loc_id>')
def get_location(loc_id):
    snap = db.session.get(LocationSnapshot, loc_id)
    if snap is None:
        return jsonify({'error': 'not found'}), 404
    return jsonify({
        **snap.to_dict(),
        'devices': [d.to_dict() for d in snap.devices],
    })


@net.delete('/locations/<int:loc_id>')
def delete_location(loc_id):
    snap = db.session.get(LocationSnapshot, loc_id)
    if snap is None:
        return jsonify({'error': 'not found'}), 404
    db.session.delete(snap)
    db.session.commit()
    return '', 204
