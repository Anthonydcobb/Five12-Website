import threading
import time
import subprocess
import ipaddress
import re
import logging
from datetime import datetime

log = logging.getLogger(__name__)


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
        if device is None:
            device = NetworkDevice(mac_address=mac)
            db.session.add(device)

        device.last_ip = ip
        device.last_seen = datetime.utcnow()
        device.device_type = device_type
        device.subnet_id = subnet_id
        if vendor_data:
            device.vendor_data = vendor_data

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            log.error('Failed to save device %s: %s', mac, e)


def run_scan_now(app) -> None:
    from .models import NetworkSubnet
    from . import db

    with app.app_context():
        subnets = db.session.execute(
            NetworkSubnet.__table__.select().where(NetworkSubnet.active == True)
        ).fetchall()

    for row in subnets:
        subnet_id, cidr = row.id, row.cidr
        log.info('Scanning %s', cidr)
        try:
            pairs = _arp_scan(cidr)
            for ip, mac in pairs:
                _process_discovered_device(ip, mac, subnet_id, app)
        except Exception as e:
            log.error('Scan error on %s: %s', cidr, e)


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
