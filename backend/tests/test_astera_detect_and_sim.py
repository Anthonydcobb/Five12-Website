"""Astera adapter — detect() with a host, and the simulator contract.

Simulator rule (agreed direction): simulated data is always labeled
simulated, and models only the normalized Five12 contract — it must not be
mistakable for observed protocol evidence. It makes no network requests.
"""

import socket

import pytest
import requests

from app.integrations import astera
from app.integrations.astera import AsteraAdapter


@pytest.fixture
def gate_on(monkeypatch):
    monkeypatch.setenv('FIVE12_ASTERA_TOOLS', '1')


@pytest.fixture
def no_network(monkeypatch):
    def _refuse(*args, **kwargs):
        raise AssertionError('network access attempted in sim mode')
    monkeypatch.setattr(socket, 'getaddrinfo', _refuse)
    monkeypatch.setattr(socket, 'create_connection', _refuse)
    monkeypatch.setattr(requests, 'get', _refuse)


# ── detect() with a configured host ─────────────────────────────────────────

def test_detect_probes_the_asteranext_port(gate_on, monkeypatch):
    monkeypatch.setenv('FIVE12_ASTERA_HOST', '192.168.1.50')
    probed = {}
    monkeypatch.setattr(astera, 'require_private_host', lambda h: '192.168.1.50')
    def fake_reachable(ip, port, timeout=0.6):
        probed['target'] = (ip, port)
        return True
    monkeypatch.setattr(astera, 'tcp_reachable', fake_reachable)
    det = AsteraAdapter(sim=False).detect()
    assert det['found'] is True
    assert det['address'] == '192.168.1.50'
    assert probed['target'] == ('192.168.1.50', 8080)


def test_detect_refuses_non_private_host(gate_on, monkeypatch):
    monkeypatch.setenv('FIVE12_ASTERA_HOST', 'example.com')
    def refuse(h):
        raise ValueError(f'{h!r} resolves to non-private 93.184.216.34 — refused')
    monkeypatch.setattr(astera, 'require_private_host', refuse)
    det = AsteraAdapter(sim=False).detect()
    assert det['found'] is False
    assert 'refused' in det['detail']


def test_detect_reports_unreachable_without_claiming_absent(gate_on, monkeypatch):
    monkeypatch.setenv('FIVE12_ASTERA_HOST', '192.168.1.50')
    monkeypatch.setattr(astera, 'require_private_host', lambda h: '192.168.1.50')
    monkeypatch.setattr(astera, 'tcp_reachable', lambda *a, **k: False)
    det = AsteraAdapter(sim=False).detect()
    assert det['found'] is False
    assert det['detail']  # says why, e.g. port closed


# ── simulator ───────────────────────────────────────────────────────────────

def test_sim_detect_is_labeled_simulated(gate_on, no_network):
    det = AsteraAdapter(sim=True).detect()
    assert det['found'] is True
    assert det['detail'] == 'simulated'


def test_sim_status_is_labeled_and_makes_no_request(gate_on, no_network):
    status = AsteraAdapter(sim=True).get_status()
    assert status['available'] is True
    assert status['simulated'] is True
    assert status['appOnline'] is True
    assert isinstance(status['bridge']['batteryPct'], int)
    assert status['alerts'] is not None


def test_sim_never_leaks_a_raw_radio_pin(gate_on, no_network):
    import json
    blob = json.dumps(AsteraAdapter(sim=True).get_status())
    assert 'radioPinAlias' in blob
    assert 'radioPin"' not in blob  # no raw pin key
