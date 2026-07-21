import threading
import time
import subprocess
from concurrent.futures import ThreadPoolExecutor
import ipaddress
import re
import logging
from datetime import datetime, timedelta

from .local_ifaces import local_ipv4s

log = logging.getLogger(__name__)

# Widest prefix we will enumerate address-by-address (a /22). Past this, a
# sweep stops being a sweep: measured on this host a /24 takes ~2.6s, so a /16
# is ~11min and the configured sACN /8 is ~47h — one subnet stalls the whole
# sequential loop for days. Wider ranges are reduced to candidate /24s by
# `_sweep_targets` instead of being enumerated.
MAX_SWEEP_ADDRESSES = 1024

# A device that hasn't answered a sweep is kept (shown offline) so its
# label/notes survive going offline and coming back on a new DHCP IP —
# persistence is keyed on MAC, not IP. Only truly anonymous devices
# (no label AND no notes) are pruned, and only after this long offline.
UNLABELED_PRUNE_AGE = timedelta(hours=24)

# How long without a sighting before a device counts as offline. MUST match
# `isOnline` in app/src/pages/NetworkMonitor.jsx, which paints a device red at
# 90s — the "remove offline devices" button clears exactly what the operator
# sees as red, so a disagreement here silently clears the wrong set.
OFFLINE_THRESHOLD = timedelta(seconds=90)


def _ignored_networks(ignore_cidrs: str | None) -> list:
    """Parse a subnet's comma-separated `ignore_cidrs` into networks.

    An unparseable entry is skipped rather than raised: this is operator-typed
    text, and one typo must not take the whole subnet's scan down with it.
    """
    if not ignore_cidrs:
        return []
    nets = []
    for part in ignore_cidrs.split(','):
        part = part.strip()
        if not part:
            continue
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            log.warning('ignoring unparseable ignore_cidr %r', part)
    return nets


def _is_ignored_ip(ip: str, nets) -> bool:
    """True if `ip` falls in any ignored range — never persisted as a device."""
    if not nets:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in nets)


def _is_host_mac(mac: str) -> bool:
    """False for addresses that are not a real host: broadcast, all-zero
    (incomplete ARP entry), and IPv4/IPv6 multicast. `arp -a` lists all three,
    and each was previously persisted as its own NetworkDevice row."""
    m = mac.upper().replace('-', ':')
    if m in ('FF:FF:FF:FF:FF:FF', '00:00:00:00:00:00'):
        return False
    return not m.startswith(('01:00:5E', '33:33'))


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


def _scapy_scan(cidr: str) -> list[tuple[str, str]]:
    """Active ARP sweep via scapy. Raises if scapy is unusable."""
    from scapy.all import ARP, Ether, srp
    ans, _ = srp(Ether(dst='ff:ff:ff:ff:ff:ff') / ARP(pdst=cidr),
                 timeout=2, verbose=False)
    return [(rcv.psrc, rcv.hwsrc.upper()) for _, rcv in ans]


def _warm_arp_cache(cidr: str) -> None:
    """Ping every host in `cidr` so the OS ARP cache is populated before we
    read it.

    Without this the cache-based path is purely passive: it only sees devices
    something else happened to talk to recently. A quiet device — the second
    Bolero antenna at 192.168.1.12 was the case that exposed this — ages out
    and becomes invisible. Skipped for prefixes wider than /22: a /8 sweep is
    16M pings and would never finish (see docs/network-state.md, "wide sweeps
    time out").
    """
    try:
        net = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return
    if net.num_addresses > MAX_SWEEP_ADDRESSES:
        return
    with ThreadPoolExecutor(max_workers=64) as pool:
        for host in net.hosts():
            pool.submit(subprocess.run,
                        ['ping', '-n', '1', '-w', '200', str(host)],
                        capture_output=True, timeout=5)


def _merge_pairs(primary: list[tuple[str, str]],
                 secondary: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Union of two (ip, mac) lists, `primary` winning on a conflicting IP."""
    merged = {ip: mac for ip, mac in secondary}
    merged.update({ip: mac for ip, mac in primary})
    return sorted(merged.items())


def _sweep_targets(cidr: str, known_ips=()) -> list[str]:
    """The ranges actually worth enumerating inside `cidr`.

    A prefix at or under MAX_SWEEP_ADDRESSES is swept whole. Anything wider is
    reduced to the /24s that hold either a local NIC or a previously-seen
    device: the configured ranges are deliberately loose (sACN is a whole /8)
    but real hardware clusters into a handful of /24s. That turns 16.7M probes
    into ~1k while still covering every address a device has ever been seen on.

    Returns [] when a wide range has no known occupants — nothing to aim at.
    The `arp -a` fallback in `_arp_scan` still covers the full CIDR, so this
    narrows the ACTIVE probe only; it never narrows what can be discovered
    from the cache.
    """
    try:
        net = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return []
    if net.num_addresses <= MAX_SWEEP_ADDRESSES:
        return [str(net)]

    targets = set()
    for ip in list(local_ipv4s()) + list(known_ips):
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if addr in net:
            targets.add(str(ipaddress.ip_network(f'{ip}/24', strict=False)))
    return sorted(targets)


def _arp_scan(cidr: str, known_ips=()) -> list[tuple[str, str]]:
    """Discover (ip, mac) pairs using BOTH the active scapy sweep and the OS
    ARP cache.

    CHANGE: the old version returned the scapy result and only consulted the
    cache inside `except`. On Windows without Npcap/admin, scapy imports and
    runs fine but sends nothing, so `srp` returns ZERO answers and raises
    NOTHING — the fallback never fired and this returned []. Discovery was
    silently dead: device_type never refreshed (Netgear switches stayed
    'unknown' after the OUI table gained them) and quiet devices were never
    found at all. Empty is not proof of an empty network, so the two sources
    are now merged rather than one being preferred.

    CHANGE: the sweep is now aimed at `_sweep_targets(cidr)` rather than the
    raw CIDR. Sweeping the configured range verbatim meant ~11min per /16 and
    ~47h for the sACN /8, so the sequential scan loop never reached the later
    subnets at all.
    """
    scapy_pairs = []
    for target in _sweep_targets(cidr, known_ips):
        try:
            found = _scapy_scan(target)
        except Exception as e:
            log.debug('scapy ARP sweep unavailable on %s: %s', target, e)
            found = []
        if found:
            scapy_pairs.extend(found)
        else:
            # scapy contributed nothing here, so the cache is the only source
            # for this range — make it worth reading before we read it.
            _warm_arp_cache(target)

    # Always over the FULL cidr: `arp -a` is a single cheap command and the
    # cache may hold devices outside any swept /24.
    return _merge_pairs(scapy_pairs, _arp_fallback(cidr))


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
        # Any sighting un-hides. "Remove offline devices" is a soft hide, so a
        # device that plugs back in reappears here — with the label and notes
        # the operator typed on it still attached.
        device.hidden = False
        if vendor_data:
            device.vendor_data = vendor_data

        # CHANGE: dropped the `is_new` guard. Auto-labelling only ever fired on
        # a row's first sighting, so a device already in the table when the OUI
        # map gained its vendor kept label=None forever — the seven Netgear
        # switches were sitting unlabelled for exactly this reason. Labelling
        # any UNLABELLED row instead backfills them on the next sweep. An
        # operator-typed label is still never overwritten.
        if not device.label and device_type != 'unknown':
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
    from .vendors import is_randomized_mac
    from . import db

    with app.app_context():
        subnets = db.session.execute(
            NetworkSubnet.__table__.select().where(NetworkSubnet.active == True)
        ).fetchall()

    for row in subnets:
        subnet_id, cidr = row.id, row.cidr
        ignored = _ignored_networks(row.ignore_cidrs)
        log.info('Scanning %s', cidr)
        try:
            net = ipaddress.ip_network(cidr, strict=False)
            excluded = {str(net.network_address), str(net.broadcast_address)}
            # CHANGE: drop locally-administered (randomized) MACs. The venue
            # Wi-Fi client subnet sits inside the Management /16, so ~50 phones
            # were being persisted as NetworkDevice rows — each keyed on a MAC
            # that changes on the next association, so they accumulated as
            # permanent unlabeled junk that the prune could only clear 24h late.
            # Lighting infrastructure never randomizes its MAC.
            # Previously-seen addresses aim the sweep inside a wide CIDR —
            # see _sweep_targets. Cheap query, and it means a device that has
            # ever been seen keeps getting actively probed on its own /24.
            with app.app_context():
                known_ips = [r[0] for r in db.session.query(
                    NetworkDevice.last_ip).filter(
                    NetworkDevice.last_ip.isnot(None)).all()]
            # `ignore_cidrs` drops addresses inside a range the operator has
            # declared not-ours — the venue Wi-Fi /23 nested in the Management
            # /16. Same treatment randomized MACs get: filtered before persist,
            # so those rows never exist rather than being cleaned up later.
            pairs = [(ip, mac) for ip, mac in _arp_scan(cidr, known_ips)
                     if ip not in excluded and _is_host_mac(mac)
                     and not is_randomized_mac(mac)
                     and not _is_ignored_ip(ip, ignored)]
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
