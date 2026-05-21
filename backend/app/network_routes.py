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
    )
    db.session.add(subnet)
    db.session.commit()
    return jsonify(subnet.to_dict()), 201


@net.delete('/subnets/<int:subnet_id>')
def delete_subnet(subnet_id):
    subnet = db.session.get(NetworkSubnet, subnet_id)
    if subnet is None:
        return jsonify({'error': 'not found'}), 404
    db.session.delete(subnet)
    db.session.commit()
    return '', 204


@net.get('/devices')
def list_devices():
    devices = NetworkDevice.query.order_by(NetworkDevice.last_seen.desc()).all()
    return jsonify([d.to_dict() for d in devices])


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
