import ipaddress
from flask import Blueprint, jsonify, request
from datetime import datetime
from . import db
from .models import NetworkSubnet, NetworkDevice, LocationSnapshot, LocationDevice, _utc_iso
from .scanner import validate_sweep_hints

net = Blueprint('network', __name__, url_prefix='/api/network')


@net.get('/subnets')
def list_subnets():
    subnets = NetworkSubnet.query.order_by(NetworkSubnet.id).all()
    return jsonify([s.to_dict() for s in subnets])


def _reject_bad_hints(raw, subnet_cidr):
    """400 payload for invalid sweep hints, or None when they are acceptable.

    Validated here rather than only at scan time. Storing a hint the scanner
    will ignore, and echoing it back as configuration, is the API claiming a
    setting was applied while the code does something else.
    """
    _accepted, errors = validate_sweep_hints(raw, subnet_cidr)
    if not errors:
        return None
    return jsonify({'error': 'invalid sweepHints', 'details': errors}), 400


@net.post('/subnets')
def create_subnet():
    data = request.get_json()
    if 'sweepHints' in data:
        bad = _reject_bad_hints(data.get('sweepHints'), data.get('cidr'))
        if bad:
            return bad
    subnet = NetworkSubnet(
        label=data['label'],
        cidr=data['cidr'],
        interface_hint=data.get('interfaceHint'),
        color=data.get('color', '#7dd3fc'),
        ignore_cidrs=data.get('ignoreCidrs') or None,
        sweep_hints=data.get('sweepHints') or None,
    )
    db.session.add(subnet)
    db.session.commit()
    return jsonify(subnet.to_dict()), 201


#: Fields this route will change. Deliberately just the one it was built for.
#: A general subnet PATCH could rewrite `cidr`, which leaves every attached
#: device's `subnet_id` semantically stale, or `active`, which silently stops a
#: subnet being scanned — neither should ride in on a convenience route added to
#: set sweep hints. Widen this only alongside validation and tests for each
#: field added.
_PATCHABLE = {'sweepHints': 'sweep_hints', 'ignoreCidrs': 'ignore_cidrs'}


def _reject_bad_ignores(raw, subnet_cidr):
    """400 with a reason per bad entry, or None.

    Same contract as `_reject_bad_hints`: a stored value the scanner will
    silently ignore is worse than a rejected one, because the API would be
    claiming a setting was applied while the code did something else.
    """
    if raw is None or not str(raw).strip():
        return None
    errors = []
    try:
        subnet = ipaddress.ip_network(subnet_cidr, strict=False)
    except (ValueError, TypeError):
        return jsonify({'error': f'the subnet CIDR {subnet_cidr!r} is not a network'}), 400
    for piece in str(raw).split(','):
        piece = piece.strip()
        if not piece:
            continue
        try:
            entry = ipaddress.ip_network(piece, strict=False)
        except ValueError:
            errors.append(f'{piece!r} is not a CIDR block')
            continue
        if entry.version != subnet.version:
            errors.append(f'{entry} is IPv{entry.version} but {subnet} is '
                          f'IPv{subnet.version}')
            continue
        if not entry.subnet_of(subnet):
            errors.append(f'{entry} is outside {subnet}')
    if errors:
        return jsonify({'error': 'invalid ignoreCidrs', 'details': errors}), 400
    return None


@net.patch('/subnets/<int:subnet_id>')
def update_subnet(subnet_id):
    """Partial update, restricted to `sweepHints` and `ignoreCidrs`.

    Exists because sweep hints are most needed on the subnets that already
    exist, and without this the only way to add them was to delete and
    recreate a subnet — which nulls `subnet_id` on every device attached to
    it, losing the grouping the operator built up.

    An unsupported field is a 400 rather than a silent no-op: a caller that
    thinks it changed `cidr` and got a 200 has been misled.
    """
    subnet = db.session.get(NetworkSubnet, subnet_id)
    if subnet is None:
        return jsonify({'error': 'not found'}), 404

    data = request.get_json() or {}
    unsupported = sorted(set(data) - set(_PATCHABLE))
    if unsupported:
        return jsonify({
            'error': 'unsupported field(s)',
            'details': unsupported,
            'supported': sorted(_PATCHABLE),
        }), 400

    if 'sweepHints' in data:
        bad = _reject_bad_hints(data.get('sweepHints'), subnet.cidr)
        if bad:
            return bad

    if 'ignoreCidrs' in data:
        bad = _reject_bad_ignores(data.get('ignoreCidrs'), subnet.cidr)
        if bad:
            return bad

    for key, attr in _PATCHABLE.items():
        if key not in data:
            continue
        value = data[key]
        # Empty string clears the column rather than storing ''.
        setattr(subnet, attr, value if value else None)

    db.session.commit()
    return jsonify(subnet.to_dict())


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


@net.get('/devices/<mac>/ports')
def device_ports(mac):
    """Per-port patch for a DMX node, read live, falling back to the sweep.

    Enrichment only runs on the 300s discovery sweep, so the stored copy can be
    five minutes behind — and it is out of date at exactly the moment an
    operator is repatching the node and looking at this panel. So the node is
    re-read on demand.

    Strictly read-only: it never writes vendor_data. A live value that
    disagrees with the stored one is not evidence the sweep was wrong, and
    writing here would race the scanner.
    """
    from . import vendors

    device = db.session.get(NetworkDevice, mac)
    if device is None:
        return jsonify({'error': 'not found'}), 404

    if device.last_ip:
        live = vendors.read_port_status(device.last_ip)
        if live.get('ports'):
            # A live read has a well-defined "as of": right now. Always
            # returning asOf keeps the shape identical to the fallback
            # branch below instead of leaving consumers to treat a missing
            # key and an explicit null as two different kinds of "no value".
            return jsonify({
                'ports': live['ports'],
                'live': True,
                'asOf': _utc_iso(datetime.utcnow()),
            })

    return jsonify({
        'ports': (device.vendor_data or {}).get('ports') or [],
        'live': False,
        'asOf': _utc_iso(device.last_seen),
    })


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
