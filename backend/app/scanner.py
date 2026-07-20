import threading
import time
import subprocess
import ipaddress
import re
import logging
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

# A device that hasn't answered a sweep is kept (shown offline) so its
# label/notes survive going offline and coming back on a new DHCP IP —
# persistence is keyed on MAC, not IP. Only truly anonymous devices
# (no label AND no notes) are pruned, and only after this long offline.
UNLABELED_PRUNE_AGE = timedelta(hours=24)


def _arp_fallback(cidr: str) -> list[tuple[str, str]]:
    """Parse the OS ARP cache via `arp -a`. No elevated privileges needed."""
    results = []
    try:
        net = ipaddress.ip_network(cidr, strict=False)
        out = subprocess.check_output(['arp', '-a'], text=True, timeout=10)
        for line in out.splitlines():
            m = re.search(r'(\d+\.\d+\.\d+\.\d+)\s+([0-9a-f-]{17})', line, re.IGNORECASE)
            if m:
                ip, mac = m.group(1), m.group(2).replace('-', ':').upper()
                if ipaddress.ip_address(ip) in net:
                    results.append((ip, mac))
    except Exception as e:
        log.warning('arp_fallback error: %s', e)
    return results


def _arp_scan(cidr: str) -> list[tuple[str, str]]:
    """Try scapy ARP sweep; fall back to OS ARP cache on failure."""
    try:
        from scapy.all import ARP, Ether, srp
        ans, _ = srp(Ether(dst='ff:ff:ff:ff:ff:ff') / ARP(pdst=cidr),
                     timeout=2, verbose=False)
        return [(rcv.psrc, rcv.hwsrc.upper()) for _, rcv in ans]
    except Exception:
        return _arp_fallback(cidr)


def _process_discovered_device(ip: str, mac: str, subnet_id: int, app) -> None:
    from .models import NetworkDevice
    from .vendors import detect_vendor_type, enrich_device
    from . import db

    with app.app_context():
        device_type = detect_vendor_type(mac)
        vendor_data = enrich_device(ip, mac, device_type)

        device = db.session.get(NetworkDevice, mac)
        is_new = device is None
        if is_new:
            device = NetworkDevice(mac_address=mac)
            db.session.add(device)

        device.last_ip = ip
        device.last_seen = datetime.utcnow()
        device.device_type = device_type
        device.subnet_id = subnet_id
        if vendor_data:
            device.vendor_data = vendor_data

        if is_new and not device.label and device_type != 'unknown':
            model = vendor_data.get('model') if vendor_data else None
            device.label = f"{device_type.capitalize()} {model}".strip() if model else device_type.capitalize()

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            log.error('Failed to save device %s: %s', mac, e)


def _subnet_id_for_ip(ip: str, subnets) -> int | None:
    """Which active subnet contains `ip`, by CIDR. None if none match —
    NetworkDevice.subnet_id is nullable, and the prune step is scoped per
    subnet, so an unmatched device is simply never pruned."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    for row in subnets:
        try:
            if addr in ipaddress.ip_network(row.cidr, strict=False):
                return row.id
        except ValueError:
            continue
    return None


def _scan_artnet(app, subnets) -> None:
    """Discover Stardust units over Art-Net and upsert them.

    Art-Net discovery rather than the ARP sweep because these devices sit on
    interfaces the default-route sweep does not reach — an ArtPollReply is
    the reliable way to see them.
    """
    from .models import NetworkDevice
    from .integrations.stardust import StardustAdapter
    from . import db

    try:
        units = StardustAdapter(sim=False).discover_units()
    except Exception as e:
        log.warning('Art-Net discovery failed: %s', e)
        return

    with app.app_context():
        for unit in units:
            mac = unit['mac']
            device = db.session.get(NetworkDevice, mac)
            if device is None:
                device = NetworkDevice(mac_address=mac)
                db.session.add(device)

            device.last_ip = unit['ip']
            device.last_seen = datetime.utcnow()
            device.device_type = 'stardust'
            device.subnet_id = _subnet_id_for_ip(unit['ip'], subnets)
            device.vendor_data = {
                'model': unit.get('longName') or unit.get('shortName'),
                'firmware': unit.get('firmware'),
                'shortName': unit.get('shortName'),
                'estaMan': unit.get('estaMan'),
                'universesOutputting': unit.get('universesOutputting') or [],
                'webUrl': f"http://{unit['ip']}",
            }
            # Auto-label so the anonymous-device prune keeps this row.
            if not device.label:
                device.label = unit.get('longName') or unit.get('shortName') or 'Stardust'

        try:
            db.session.commit()
            if units:
                log.info('Art-Net: %d Stardust unit(s) upserted', len(units))
        except Exception as e:
            db.session.rollback()
            log.error('Failed to save Art-Net devices: %s', e)


def run_scan_now(app) -> None:
    from .models import NetworkSubnet, NetworkDevice
    from . import db

    with app.app_context():
        subnets = db.session.execute(
            NetworkSubnet.__table__.select().where(NetworkSubnet.active == True)
        ).fetchall()

    for row in subnets:
        subnet_id, cidr = row.id, row.cidr
        log.info('Scanning %s', cidr)
        try:
            net = ipaddress.ip_network(cidr, strict=False)
            excluded = {str(net.network_address), str(net.broadcast_address)}
            pairs = [(ip, mac) for ip, mac in _arp_scan(cidr) if ip not in excluded]
            found_macs = set()
            for ip, mac in pairs:
                found_macs.add(mac)
                _process_discovered_device(ip, mac, subnet_id, app)
            # CHANGE: the old code deleted every device in this subnet that
            # wasn't seen in the current sweep. That destroyed the whole
            # point of MAC-keyed labels — a DHCP device that briefly dropped
            # offline lost its label/notes, and came back (often on a new IP)
            # as a blank row. Now we KEEP unseen devices (they render offline
            # via last_seen) and prune ONLY anonymous ones — no label and no
            # notes — that have been offline longer than UNLABELED_PRUNE_AGE.
            with app.app_context():
                cutoff = datetime.utcnow() - UNLABELED_PRUNE_AGE
                q = NetworkDevice.query.filter(
                    NetworkDevice.subnet_id == subnet_id,
                    db.or_(NetworkDevice.label.is_(None),
                           NetworkDevice.label == ''),
                    db.or_(NetworkDevice.notes.is_(None),
                           NetworkDevice.notes == ''),
                    db.or_(NetworkDevice.last_seen.is_(None),
                           NetworkDevice.last_seen < cutoff),
                )
                if found_macs:
                    q = q.filter(NetworkDevice.mac_address.notin_(found_macs))
                q.delete(synchronize_session=False)
                db.session.commit()
        except Exception as e:
            log.error('Scan error on %s: %s', cidr, e)

    # Once per sweep, not per subnet: ArtPoll is a broadcast from every local
    # interface, so it is independent of the configured CIDR list. Runs after
    # the prune so a freshly-seen unit is never pruned in the same pass.
    _scan_artnet(app, subnets)


def start_scanner(app) -> None:
    def _loop():
        while True:
            try:
                run_scan_now(app)
            except Exception as e:
                log.error('Scanner loop error: %s', e)
            time.sleep(30)

    t = threading.Thread(target=_loop, daemon=True, name='arp-scanner')
    t.start()
    log.info('ARP scanner started')
