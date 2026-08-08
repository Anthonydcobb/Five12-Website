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

    # CHANGE: asOf is the stored `portsAsOf` — the moment /model/status was
    # last read successfully — not `last_seen`. last_seen tracks ICMP
    # liveness: quick_reprobe refreshes it every 20s and explicitly does NOT
    # enrich (pinned by test_reprobe_never_sweeps_or_enriches). Returning it
    # here presented the ping clock as the patch's provenance, so a node whose
    # HTTP stack is wedged but which still answers ping showed an hours-old
    # patch labelled "as of 10s ago" — and somebody can repatch that node from
    # its front panel while the operator believes the table.
    #
    # Rows swept before this change carry no portsAsOf, so this is None for
    # them; the panel degrades to "time unknown", which is the truth. No
    # migration — the next sweep of a reachable node fills it in.
    stored = device.vendor_data or {}
    return jsonify({
        'ports': stored.get('ports') or [],
        'live': False,
        'asOf': stored.get('portsAsOf'),
    })


@net.get('/devices/<mac>/switch-ports')
def device_switch_ports(mac):
    """Which MACs are behind each port of a managed switch, live then cached.

    Read-only in both directions: SNMP GET/WALK only toward the switch (the
    rig is live), and no database write here — the scanner updates this row
    concurrently.
    """
    from . import vendors

    device = db.session.get(NetworkDevice, mac)
    if device is None:
        return jsonify({'error': 'not found'}), 404

    if device.last_ip:
        live = vendors.read_switch_ports(device.last_ip)
        if live.get('switchPorts'):
            return jsonify({
                'switchPorts': live['switchPorts'],
                'live': True,
                'asOf': _utc_iso(datetime.utcnow()),
            })

    # The map's own timestamp, never last_seen — last_seen is the ICMP clock
    # that quick_reprobe refreshes every 20s without walking SNMP.
    stored = device.vendor_data or {}
    return jsonify({
        'switchPorts': stored.get('switchPorts') or [],
        'live': False,
        'asOf': stored.get('switchPortsAsOf'),
    })


@net.get('/devices/<mac>/uplink')
def device_uplink(mac):
    """Which switch port this device sits behind.

    Pure computation over stored maps — issues no SNMP at all. Answering this
    live would mean walking every switch on every device selection.

    `deviceCount` is part of the answer, not decoration: only a count of one
    proves direct attachment, and the caller must word itself accordingly.

    `asOf` is the other half of that. The stored maps never expire — a switch
    that stops answering keeps its last map in the database indefinitely,
    across restarts — so a count of one from a three-hour-old map is not
    present-tense evidence of anything. /switch-ports already serves this
    timestamp and its pane renders it; this route serves the same stored maps
    and must not be the one consumer that hides their age.
    """
    from . import vendors

    device = db.session.get(NetworkDevice, mac)
    if device is None:
        return jsonify({'error': 'not found'}), 404

    switches = [
        {'mac': s.mac_address, 'label': s.label,
         'switchPorts': (s.vendor_data or {}).get('switchPorts'),
         # The map's OWN timestamp, same field /switch-ports serves, so the
         # answer can be aged. It is None on every row swept before stamping.
         'asOf': (s.vendor_data or {}).get('switchPortsAsOf')}
        for s in NetworkDevice.query.filter(NetworkDevice.mac_address != mac).all()
        if (s.vendor_data or {}).get('switchPorts')
    ]
    hit = vendors.find_switch_port(mac, switches)
    if hit is None:
        return jsonify({'found': False})
    return jsonify({'found': True, **hit})


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


@net.post('/snapshot')
def import_snapshot():
    """Import a saved NETGEAR AV UI Overview page.

    The switch is identified by its MANAGEMENT IP, not by the base MAC the
    page prints.

    [VERIFIED 2026-08-06 on the rig] those are different addresses. The page's
    "Base MAC Address" is the chassis MAC; the management interface ARPs with a
    different one, so the scanner's row never carries the value the page
    reports. Every observed pair differs by exactly 3 -- switch 60 3A:02/3A:05,
    switch 73 3C:DE/3C:E1, switch 52 47:02/47:05, switch 76 3C:1A/3C:1D -- but
    that offset is NOT used here. Four samples of one firmware is not a rule,
    and deriving an identity from a guessed arithmetic relationship is exactly
    the silent misattribution this route exists to prevent. Matching on base
    MAC refused every switch on the rig; the unit tests missed it because they
    fabricated the device row from the page's own base MAC, the one value
    guaranteed to agree with itself.

    The page's baseMac is still stored in vendor_data for reference -- it is
    the chassis identity and worth having -- it is simply not the matcher.

    Refuses rather than guesses. An unmatched IP does NOT create a row: a
    switch the scanner has never seen is a discovery problem, not something to
    invent a record for out of a pasted document. An IP claimed by more than
    one row is refused too, because picking one would be a coin toss.

    Merges rather than replaces, so the operator's label and notes, and any
    live SNMP fields already present, survive. The next sweep merges SNMP over
    this (scanner._process_discovered_device), which is the intended
    precedence: SNMP is live, a snapshot is not.
    """
    from datetime import datetime

    from .models import _utc_iso
    from .vendors.netgear_snapshot import parse_snapshot

    payload = request.get_json(silent=True) or {}
    parsed = parse_snapshot(payload.get('html') or '')

    ip = (parsed.get('managementIp') or '').strip()
    if not ip or not parsed.get('serial'):
        return jsonify({
            'error': 'unrecognised_page',
            'detail': 'No NETGEAR serial and management IP found. Paste the rendered '
                      'Configure -> Overview page (document.documentElement.outerHTML), '
                      'not a view-source of the page shell.',
        }), 422

    matches = (db.session.query(NetworkDevice)
               .filter(NetworkDevice.last_ip == ip).all())
    if not matches:
        return jsonify({
            'error': 'unknown_device',
            'detail': f'No device known at {ip}. Let the scanner discover the '
                      f'switch first, then import.',
        }), 404
    if len(matches) > 1:
        macs = ', '.join(sorted(d.mac_address for d in matches))
        return jsonify({
            'error': 'ambiguous_device',
            'detail': f'{len(matches)} devices are recorded at {ip} ({macs}). '
                      f'Nothing was changed -- resolve the duplicate first.',
        }), 409
    device = matches[0]

    stored = device.vendor_data or {}
    known_serial = stored.get('serial')
    if known_serial and known_serial != parsed['serial']:
        return jsonify({
            'error': 'serial_conflict',
            'detail': f'{ip} is recorded with serial {known_serial}, but this page '
                      f'reports {parsed["serial"]}. Nothing was changed.',
        }), 409

    parsed['source'] = 'html-snapshot'
    parsed['snapshotAsOf'] = _utc_iso(datetime.utcnow())
    device.vendor_data = {**stored, **parsed}
    db.session.commit()

    return jsonify({
        'macAddress': device.mac_address,
        'managementIp': ip,
        'systemName': parsed.get('systemName'),
        'profileCount': len(parsed.get('profiles', [])),
        'portCount': len(parsed.get('netgearPorts', [])),
        'hostDataAvailable': parsed.get('netgearPortHostsAvailable', False),
        'snapshotAsOf': parsed['snapshotAsOf'],
    })
