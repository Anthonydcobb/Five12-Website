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

# The keep-alive re-probe (`quick_reprobe`) runs this often; the slow wide
# discovery sweep (`run_scan_now`) runs on its own thread this often. A full
# discovery pass measured ~165s on the rig (a /8 + two /16s + SNMP retries),
# far longer than OFFLINE_THRESHOLD, so if `last_seen` only refreshed on the
# discovery pass every device would sawtooth across 90s and flap offline. The
# keep-alive re-probes only the already-known device IPs — a few dozen exact
# pings, no sweep and no SNMP — so real gear's `last_seen` never ages past the
# threshold between discovery passes. Keep KEEPALIVE_INTERVAL well under
# OFFLINE_THRESHOLD. See docs/handoff-2026-07-22-network-monitor-flap.md.
KEEPALIVE_INTERVAL = 20    # seconds between keep-alive re-probes of known gear
DISCOVERY_INTERVAL = 300   # seconds between full discovery sweeps


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


def _probe_address(cidr: str) -> str | None:
    """One usable address inside `cidr`, for asking the routing table which
    interface reaches it. None when `cidr` is not a network."""
    try:
        net = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return None
    for host in net.hosts():
        return str(host)
    # /32 (and /31) have no "hosts" — the network address is the address.
    return str(net.network_address)


def _sweep_ifaces(conf, cidr: str) -> list:
    """Every interface worth sweeping `cidr` from.

    The routing table's answer comes first, then any interface whose own
    address falls inside the range. Both matter, for different reasons:

    * Without the first, `srp` sends on the GLOBAL `conf.iface`, which on a
      multi-homed host is not necessarily a show NIC. That is the fault this
      function exists for — see the CHANGE note in `_scapy_scan`.
    * Without the second, a device that answers on only one of several
      overlapping interfaces stays invisible. `local_ifaces.py` records that
      exact behaviour on this host for Art-Net and sACN: "the devices are
      reachable ONLY from one of them, so a single socket on the default route
      finds zero nodes. Fanning out across every interface is what makes
      discovery work."
    """
    ifaces = []
    seen = set()

    probe = _probe_address(cidr)
    if probe:
        try:
            device = conf.route.route(probe)[0]
        except Exception as e:  # routing table unavailable; fan-out may still work
            log.debug('no route lookup for %s: %s', probe, e)
            device = None
        if device:
            ifaces.append(device)
            seen.add(str(device))

    try:
        net = ipaddress.ip_network(cidr, strict=False)
        candidates = list(conf.ifaces.data.values())
    except (ValueError, AttributeError):
        return ifaces

    for iface in candidates:
        ip = getattr(iface, 'ip', None)
        if not ip:
            continue
        try:
            if ipaddress.ip_address(ip) not in net:
                continue
        except ValueError:
            continue
        key = str(getattr(iface, 'network_name', None) or getattr(iface, 'name', iface))
        if key in seen:
            continue
        seen.add(key)
        ifaces.append(iface)

    return ifaces


def _scapy_scan(cidr: str) -> list[tuple[str, str]]:
    """Active ARP sweep via scapy. Raises if scapy is unusable.

    CHANGE: the sweep is now sent on explicitly named interfaces. `srp` is a
    layer-2 send, so without `iface` it uses scapy's GLOBAL `conf.iface` rather
    than routing per destination. On this multi-homed host that default is not
    any show NIC, so every sweep left by the wrong adapter, matched nothing,
    and returned [] WITHOUT RAISING — `_arp_scan` logged it at debug and fell
    through to the ARP cache, leaving active discovery dead in silence.

    Measured on the rig 2026-07-29, against a SideCar node that answered ping
    in 1ms:

        srp(...)                 -> 0 answers
        srp(..., iface='sACN')   -> [('10.9.15.111', '04:11:19:90:04:be')]

    Empty is still not proof of an empty network (see `_arp_scan`), so the
    cache path stays as it is.
    """
    from scapy.all import ARP, Ether, srp, conf

    found: dict[str, str] = {}
    failures: list[Exception] = []
    attempted = 0

    # `[None]` keeps the old behaviour when no interface can be resolved at
    # all: better to sweep on scapy's default than not to sweep.
    for iface in _sweep_ifaces(conf, cidr) or [None]:
        attempted += 1
        packet = Ether(dst='ff:ff:ff:ff:ff:ff') / ARP(pdst=cidr)
        try:
            if iface is None:
                ans, _ = srp(packet, timeout=2, verbose=False)
            else:
                ans, _ = srp(packet, timeout=2, verbose=False, iface=iface)
        except Exception as exc:  # noqa: BLE001
            # Isolate the failure. One unusable interface — a VPN adapter that
            # cannot send, a NIC that went away mid-sweep — must not stop the
            # remaining candidates, or a single bad adapter reproduces the
            # original fault: a sweep that finds nothing and says nothing.
            log.debug('ARP sweep failed on %s: %s', iface, exc)
            failures.append(exc)
            continue
        for _, rcv in ans:
            found[rcv.psrc] = rcv.hwsrc.upper()

    # Only when EVERY interface failed is scapy itself the problem. Re-raise so
    # `_arp_scan` still learns the sweep was unusable and warms the ARP cache
    # instead; swallowing it would silently disable the fallback.
    if failures and len(failures) == attempted:
        raise failures[-1]

    return sorted(found.items())


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


def validate_sweep_hints(raw, subnet_cidr: str) -> tuple[list[str], list[str]]:
    """Split sweep hints into (accepted, errors).

    One function so the API and the scanner cannot disagree about what a valid
    hint is. The API rejects anything in `errors` with a 400; the scanner
    ignores it defensively. Before this existed the API accepted any string,
    stored it, echoed it back as configuration, and the scanner silently
    ignored it — the API claiming a setting was applied while the code did
    something else, which is the same disease as every other fault in this
    file's history.

    Four rules, each with a reason:

    * unparseable is rejected rather than dropped, so a typo is visible;
    * anything that is not IPv4 is rejected. The sweep sends ARP, and ARP is
      IPv4-only — there is no ARP request for an IPv6 host. This rule was first
      written as "the hint must match the subnet", which is the wrong invariant:
      it caught an IPv6 hint on an IPv4 subnet (`subnet_of` raises TypeError
      across families, and `_hint_networks('fd00::/120', '10.0.0.0/8')` used to
      abort the whole subnet's scan) but an IPv6 subnet with IPv6 hints agreed
      with itself and was accepted, then handed to a scanner that could not
      speak to it. Found by Hermes' re-review, 2026-07-30;
    * a hint outside its own subnet is rejected, so one bad row cannot aim the
      sweep at a range that is not ours;
    * a hint wider than MAX_SWEEP_ADDRESSES is rejected, or a /16 reinstates
      the ~11min sweep that limit exists to prevent and a /8 the ~47h one.
    """
    if raw is None or not str(raw).strip():
        return [], []
    try:
        subnet = ipaddress.ip_network(subnet_cidr, strict=False)
    except (ValueError, TypeError):
        return [], [f'the subnet CIDR {subnet_cidr!r} is not a network']
    if subnet.version != 4:
        # Reject at the subnet, not just per hint, so the reason names the real
        # problem instead of blaming each hint in turn.
        return [], [
            f'{subnet} is IPv{subnet.version}; the sweep sends ARP, which is '
            f'IPv4-only, so nothing inside it can be swept'
        ]

    accepted: list[str] = []
    errors: list[str] = []
    for piece in str(raw).split(','):
        piece = piece.strip()
        if not piece:
            continue
        try:
            hint = ipaddress.ip_network(piece, strict=False)
        except ValueError:
            errors.append(f'{piece!r} is not a CIDR block')
            continue
        if hint.version != 4:
            errors.append(
                f'{hint} is IPv{hint.version}; the sweep sends ARP, which is '
                f'IPv4-only'
            )
            continue
        if not hint.subnet_of(subnet):
            errors.append(f'{hint} is outside {subnet}')
            continue
        if hint.num_addresses > MAX_SWEEP_ADDRESSES:
            errors.append(
                f'{hint} covers {hint.num_addresses} addresses; the limit is '
                f'{MAX_SWEEP_ADDRESSES}'
            )
            continue
        accepted.append(str(hint))
    return accepted, errors


def _hint_networks(raw: str | None, subnet_cidr: str) -> list[str]:
    """The accepted hints only. Kept defensive on purpose: rows predating
    API-side validation, or edited directly in the database, must not be able
    to abort a scan."""
    accepted, errors = validate_sweep_hints(raw, subnet_cidr)
    for problem in errors:
        log.debug('ignoring sweep hint: %s', problem)
    return accepted


def _sweep_targets(cidr: str, known_ips=(), sweep_hints=None,
                   ignore_cidrs=None) -> list[str]:
    """The ranges actually worth enumerating inside `cidr`.

    A prefix at or under MAX_SWEEP_ADDRESSES is swept whole. Anything wider is
    reduced to the /24s that hold either a local NIC or a previously-seen
    device: the configured ranges are deliberately loose (sACN is a whole /8)
    but real hardware clusters into a handful of /24s. That turns 16.7M probes
    into ~1k while still covering every address a device has ever been seen on.

    Operator-supplied `sweep_hints` are added to whatever that finds. They are
    what makes a FRESH database work: local NICs and known devices are both
    circular sources — a device has to be found before it can be looked for —
    so on a rig where the gear sits in a /24 with no local interface, nothing
    ever aims there. Fifteen SideCar nodes were invisible for exactly that
    reason while answering ping in 1ms.

    Returns [] when a wide range has no known occupants and no hints — nothing
    to aim at. The `arp -a` fallback in `_arp_scan` still covers the full CIDR,
    so this narrows the ACTIVE probe only; it never narrows what can be
    discovered from the cache.
    """
    try:
        net = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return []
    if net.num_addresses <= MAX_SWEEP_ADDRESSES:
        return [str(net)]

    targets = set(_hint_networks(sweep_hints, cidr))
    for ip in list(local_ipv4s()) + list(known_ips):
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if addr in net:
            targets.add(str(ipaddress.ip_network(f'{ip}/24', strict=False)))

    # A range the operator has declared not-ours is not worth probing: every
    # answer from it is discarded at persist time anyway (see _is_ignored_ip in
    # run_scan_now). Dropping it here saves the probes as well as the rows.
    #
    # ENTIRELY inside, not merely overlapping. Ignoring 10.9.15.0/25 must not
    # stop the sweep of 10.9.15.0/24 and blind the half that is still ours.
    ignored = _ignored_networks(ignore_cidrs)
    if ignored:
        targets = {
            t for t in targets
            if not any(ipaddress.ip_network(t).subnet_of(bad)
                       for bad in ignored
                       if ipaddress.ip_network(t).version == bad.version)
        }
    return sorted(targets)


def _arp_scan(cidr: str, known_ips=(), sweep_hints=None,
              ignore_cidrs=None) -> list[tuple[str, str]]:
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
    for target in _sweep_targets(cidr, known_ips, sweep_hints, ignore_cidrs):
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
    from .vendors import detect_vendor_type, display_name, enrich_device
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
            shown = display_name(device_type)
            device.label = f"{shown} {model}".strip() if model else shown

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
            pairs = [(ip, mac) for ip, mac in _arp_scan(cidr, known_ips,
                                                        row.sweep_hints,
                                                        row.ignore_cidrs)
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


def _ping_hosts(ips) -> None:
    """Ping a specific list of hosts so the OS ARP cache holds them.

    Unlike `_warm_arp_cache`, which pings an entire /24, this targets only the
    exact IPs we already know about — a keep-alive is a few dozen pings, not 256
    per subnet, so it finishes in a couple of seconds and can run every cycle.
    """
    with ThreadPoolExecutor(max_workers=64) as pool:
        for ip in ips:
            pool.submit(subprocess.run,
                        ['ping', '-n', '1', '-w', '200', str(ip)],
                        capture_output=True, timeout=5)


def quick_reprobe(app) -> int:
    """Refresh `last_seen` for already-known devices, cheaply, every cycle.

    Pings the exact IPs of devices already in the table, re-reads the OS ARP
    cache, and bumps `last_seen` for every known MAC still answering. It does
    NOT sweep, warm whole /24s, enrich over SNMP, auto-label, discover new
    devices or prune — that is the slow discovery pass's job (`run_scan_now`).
    This exists purely so real gear does not age past OFFLINE_THRESHOLD in the
    ~165s between discovery passes and flap offline. Returns the count refreshed.

    A MAC seen on the wire that is NOT already in the table is ignored here: it
    could be a randomized/ignored address the discovery filters would drop, and
    persisting it without vendor detection would create a blank, unclassified
    row. New devices appear on the next discovery pass instead.
    """
    from .models import NetworkDevice
    from . import db

    with app.app_context():
        known_ips = [ip for (ip,) in db.session.query(NetworkDevice.last_ip)
                     .filter(NetworkDevice.last_ip.isnot(None)).all()]
    if not known_ips:
        return 0

    _ping_hosts(known_ips)

    now = datetime.utcnow()
    refreshed = 0
    with app.app_context():
        # 0.0.0.0/0 → the whole ARP table; we match by MAC, not by CIDR.
        for ip, mac in _arp_fallback('0.0.0.0/0'):
            device = db.session.get(NetworkDevice, mac)
            if device is None:
                continue
            device.last_ip = ip
            device.last_seen = now
            # A sighting un-hides, exactly as a discovery sighting does, so a
            # device hidden by "remove offline" that is back on the wire returns.
            device.hidden = False
            refreshed += 1
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            log.error('quick_reprobe commit failed: %s', e)
            return 0
    log.debug('quick_reprobe: refreshed %d device(s)', refreshed)
    return refreshed


def start_scanner(app) -> None:
    """Run discovery and keep-alive on two independent daemon threads.

    They are deliberately decoupled: the discovery sweep is slow (~165s) and its
    duration must not stall the keep-alive, or known gear would age past the
    offline threshold while a discovery pass is running and flap — the very bug
    this split fixes. Both write NetworkDevice rows; each wraps its commits in
    try/except so a rare concurrent-write conflict (SQLite) is a skipped beat,
    self-healed on the next pass, not a crash.
    """
    def _discovery_loop():
        while True:
            try:
                run_scan_now(app)
            except Exception as e:
                log.error('Discovery loop error: %s', e)
            time.sleep(DISCOVERY_INTERVAL)

    def _keepalive_loop():
        while True:
            try:
                quick_reprobe(app)
            except Exception as e:
                log.error('Keep-alive loop error: %s', e)
            time.sleep(KEEPALIVE_INTERVAL)

    threading.Thread(target=_discovery_loop, daemon=True,
                     name='arp-discovery').start()
    threading.Thread(target=_keepalive_loop, daemon=True,
                     name='arp-keepalive').start()
    log.info('ARP scanner started (discovery every %ds, keep-alive every %ds)',
             DISCOVERY_INTERVAL, KEEPALIVE_INTERVAL)
