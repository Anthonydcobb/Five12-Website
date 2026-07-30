"""The ARP sweep must leave by the interface that reaches the target range.

Diagnosed 2026-07-29 on the show rig. A SideCar node at 10.9.15.111 answered
ping in 1ms and ARPed as 04:11:19:90:04:be, yet `_scapy_scan` found nothing —
on that range, or on 10.220.220.0/24, or anywhere. Measured directly:

    srp(...)                    -> 0 answers
    srp(..., iface='sACN')      -> [('10.9.15.111', '04:11:19:90:04:be')]

scapy's own routing table resolved the correct device for the destination
(\\Device\\NPF_{21DA0B53...}, the sACN NIC, source 10.220.220.220) — but for a
layer-2 send `srp` uses the GLOBAL `conf.iface` unless told otherwise, and on
this multi-homed host that default is not any show NIC. So every ARP sweep the
app ever performed left by the wrong adapter, matched nothing, and returned []
without raising. `_arp_scan` logs that at debug and falls through to the ARP
cache, so active discovery has been dead in silence.

The repo already knew this lesson from the other direction: local_ifaces.py
records that the host has several overlapping 10/8 interfaces, devices are
reachable from only one of them, and fanning out is what makes discovery work.
That fix reached Art-Net and sACN but never the ARP sweep.

These tests use a stub scapy so they run anywhere, including interpreters that
have no scapy installed.
"""

import sys
import types

import pytest

from app import scanner


class _FakeAnswer:
    """One (sent, received) pair as scapy's srp returns them."""

    def __init__(self, psrc, hwsrc):
        self.psrc = psrc
        self.hwsrc = hwsrc


class _FakeIface:
    def __init__(self, name, ip, network_name=None):
        self.name = name
        self.ip = ip
        self.network_name = network_name or f"\\Device\\NPF_{{{name}}}"

    def __repr__(self):
        return f"<iface {self.name}>"


class _FakeRoute:
    def __init__(self, device):
        self._device = device

    def route(self, target):
        return (self._device, "10.220.220.220", "0.0.0.0")


class _FakeConf:
    def __init__(self, route_device="\\Device\\NPF_{SACN}", ifaces=()):
        self.route = _FakeRoute(route_device)
        self.ifaces = types.SimpleNamespace(
            data={i.name: i for i in ifaces}
        )


@pytest.fixture
def scapy_stub(monkeypatch):
    """Install a stub `scapy.all` and hand back the recorded srp calls."""
    calls = []
    answers_by_iface = {}
    raise_for_iface = {}

    def srp(pkt, timeout=None, verbose=None, iface=None, **kwargs):
        calls.append({"iface": iface, "timeout": timeout, "kwargs": kwargs})
        key = getattr(iface, "name", iface)
        if key in raise_for_iface:
            raise raise_for_iface[key]
        found = answers_by_iface.get(key, [])
        return ([(None, a) for a in found], [])

    module = types.ModuleType("scapy.all")
    module.ARP = lambda **kw: types.SimpleNamespace(**kw)
    module.Ether = lambda **kw: types.SimpleNamespace(
        **kw, __truediv__=lambda self, other: self
    )
    module.srp = srp
    module.conf = _FakeConf()

    # Ether()/ARP() has to produce something; a plain object is enough because
    # the stub srp never inspects the packet.
    class _Pkt:
        def __truediv__(self, other):
            return self

    module.Ether = lambda **kw: _Pkt()
    module.ARP = lambda **kw: _Pkt()

    monkeypatch.setitem(sys.modules, "scapy.all", module)
    return types.SimpleNamespace(
        module=module,
        calls=calls,
        answers_by_iface=answers_by_iface,
        raise_for_iface=raise_for_iface,
    )


def test_sweep_names_the_interface_that_routes_to_the_target(scapy_stub):
    """The bug, stated as a requirement: srp must be told where to send.

    Against the unfixed code this fails with iface=None, which is exactly the
    state in which the sweep silently found nothing on every show subnet.
    """
    scapy_stub.module.conf = _FakeConf(route_device="\\Device\\NPF_{SACN}")

    scanner._scapy_scan("10.9.15.0/24")

    assert scapy_stub.calls, "srp was never called"
    assert scapy_stub.calls[0]["iface"] is not None, (
        "srp was called without an interface, so it goes out scapy's global "
        "conf.iface — the fault this test exists for"
    )
    assert scapy_stub.calls[0]["iface"] == "\\Device\\NPF_{SACN}"


def test_sweep_returns_what_the_right_interface_found(scapy_stub):
    scapy_stub.module.conf = _FakeConf(route_device="\\Device\\NPF_{SACN}")
    scapy_stub.answers_by_iface["\\Device\\NPF_{SACN}"] = [
        _FakeAnswer("10.9.15.111", "04:11:19:90:04:be")
    ]

    found = scanner._scapy_scan("10.9.15.0/24")

    assert found == [("10.9.15.111", "04:11:19:90:04:BE")]


def test_sweep_fans_out_across_every_interface_inside_the_range(scapy_stub):
    """local_ifaces.py's lesson, applied to ARP.

    The host has several overlapping 10/8 interfaces and a device may answer on
    only one of them, so one route lookup is not necessarily enough.
    """
    sacn = _FakeIface("sACN", "10.220.220.220")
    lan = _FakeIface("Local Area Connection", "10.0.0.1")
    scapy_stub.module.conf = _FakeConf(
        route_device=sacn.network_name, ifaces=(sacn, lan)
    )

    scanner._scapy_scan("10.0.0.0/8")

    used = {str(getattr(c["iface"], "name", c["iface"])) for c in scapy_stub.calls}
    assert sacn.network_name in used or "sACN" in used
    assert "Local Area Connection" in used, "the second 10/8 interface was never swept"


def test_sweep_merges_and_dedupes_across_interfaces(scapy_stub):
    sacn = _FakeIface("sACN", "10.220.220.220")
    lan = _FakeIface("Local Area Connection", "10.0.0.1")
    scapy_stub.module.conf = _FakeConf(
        route_device=sacn.network_name, ifaces=(sacn, lan)
    )
    scapy_stub.answers_by_iface[sacn.network_name] = [
        _FakeAnswer("10.9.15.111", "04:11:19:90:04:be")
    ]
    scapy_stub.answers_by_iface["Local Area Connection"] = [
        _FakeAnswer("10.9.15.111", "04:11:19:90:04:be"),
        _FakeAnswer("10.0.0.5", "aa:bb:cc:dd:ee:ff"),
    ]

    found = scanner._scapy_scan("10.0.0.0/8")

    assert found == [
        ("10.0.0.5", "AA:BB:CC:DD:EE:FF"),
        ("10.9.15.111", "04:11:19:90:04:BE"),
    ]


def test_sweep_still_runs_when_no_interface_can_be_resolved(scapy_stub):
    """Degrade to the old behaviour rather than skipping the sweep entirely."""

    class _DeadRoute:
        def route(self, target):
            raise OSError("no route")

    conf = _FakeConf()
    conf.route = _DeadRoute()
    conf.ifaces = types.SimpleNamespace(data={})
    scapy_stub.module.conf = conf

    scanner._scapy_scan("10.9.15.0/24")

    assert scapy_stub.calls, "the sweep must still be attempted"


@pytest.mark.parametrize(
    "cidr,expected",
    [
        ("10.9.15.0/24", "10.9.15.1"),
        ("10.9.15.111/32", "10.9.15.111"),
        ("192.168.1.0/30", "192.168.1.1"),
    ],
)
def test_probe_address_picks_a_usable_host(cidr, expected):
    assert scanner._probe_address(cidr) == expected


def test_probe_address_rejects_nonsense():
    assert scanner._probe_address("not-a-cidr") is None


# ---------------------------------------------------------------------------
# Raised in review: one bad interface must not take the sweep with it
# ---------------------------------------------------------------------------


def test_one_unusable_interface_does_not_stop_the_others(scapy_stub):
    """A single failing interface used to abort the sweep for that target, which
    reproduces the original fault exactly: nothing found, nothing said."""
    dead = _FakeIface("NordLynx", "10.1.0.1")
    alive = _FakeIface("sACN", "10.2.0.1")
    scapy_stub.module.conf = _FakeConf(
        route_device=dead.network_name, ifaces=(dead, alive)
    )
    scapy_stub.answers_by_iface["sACN"] = [_FakeAnswer("10.9.15.111", "04:11:19:90:04:be")]
    scapy_stub.raise_for_iface[dead.network_name] = OSError("cannot send on this adapter")

    found = scanner._scapy_scan("10.0.0.0/8")

    assert found == [("10.9.15.111", "04:11:19:90:04:BE")], (
        "the working interface must still have been swept"
    )


def test_it_still_reports_scapy_unusable_when_every_interface_fails(scapy_stub):
    """`_arp_scan` relies on an exception to learn the sweep is dead and warm the
    ARP cache instead. Swallowing every failure would silently disable that
    fallback — which is how the sweep stayed broken for so long."""
    only = _FakeIface("sACN", "10.2.0.1")
    scapy_stub.module.conf = _FakeConf(route_device=only.network_name, ifaces=(only,))
    scapy_stub.raise_for_iface[only.network_name] = OSError("npcap missing")

    with pytest.raises(OSError):
        scanner._scapy_scan("10.0.0.0/8")


def test_production_shaped_call_aims_at_the_hinted_range(scapy_stub):
    """Review point: the fan-out test drove `_scapy_scan` with a /8 directly,
    but production `_arp_scan` reduces a wide subnet to /24 targets first — so
    that test proved something production never does. This drives the real path:
    a wide configured subnet, a hint, and the sweep landing on the hinted /24.
    """
    sacn = _FakeIface("sACN", "10.220.220.220")
    scapy_stub.module.conf = _FakeConf(route_device=sacn.network_name, ifaces=(sacn,))
    scapy_stub.answers_by_iface[sacn.network_name] = [
        _FakeAnswer("10.9.15.111", "04:11:19:90:04:be")
    ]

    pairs = scanner._arp_scan("10.0.0.0/8", known_ips=[], sweep_hints="10.9.15.0/24")

    assert ("10.9.15.111", "04:11:19:90:04:BE") in pairs
    assert scapy_stub.calls, "the sweep must actually have been attempted"
    assert all(c["iface"] is not None for c in scapy_stub.calls), (
        "every sweep must name its interface"
    )
