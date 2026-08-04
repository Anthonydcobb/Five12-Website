"""Astera adapter — the FIVE12_ASTERA_TOOLS gate contract.

Agreed with Hermes (KB: Hermes/Reviews/2026-07-29-hermes-response-to-claude-
five12-art7-review.md): the gate is a behavior, not a config constant.

  * With FIVE12_ASTERA_TOOLS=0 (the default), NO Astera network request is
    made — no DNS resolution, no TCP probe, no HTTP.
  * The UI may show the adapter as disabled/not configured, but it must not
    imply the ART7 was searched for and found absent.
  * Gate enabled but no host configured: the adapter reports the exact setup
    requirement and still makes no request.

The no-network claim is enforced here by poisoning every path the adapter
could use to reach the wire; a single call fails the test.
"""

import socket

import pytest
import requests

from app.integrations.astera import AsteraAdapter


@pytest.fixture
def no_network(monkeypatch):
    """Any attempt to touch the network fails the test loudly."""
    def _refuse(*args, **kwargs):
        raise AssertionError('network access attempted while gated off')
    monkeypatch.setattr(socket, 'getaddrinfo', _refuse)
    monkeypatch.setattr(socket, 'create_connection', _refuse)
    monkeypatch.setattr(requests, 'get', _refuse)
    monkeypatch.setattr(requests, 'request', _refuse)


@pytest.fixture
def gate_off(monkeypatch):
    monkeypatch.delenv('FIVE12_ASTERA_TOOLS', raising=False)
    # A configured host must make no difference while the gate is off.
    monkeypatch.setenv('FIVE12_ASTERA_HOST', '192.168.1.50')


def test_gate_off_detect_makes_no_request_and_says_disabled(gate_off, no_network):
    det = AsteraAdapter(sim=False).detect()
    assert det['found'] is False
    assert det['address'] is None
    assert 'FIVE12_ASTERA_TOOLS' in det['detail']
    # Honesty: "disabled" must not read as "searched and absent".
    for word in ('unreachable', 'not found', 'absent'):
        assert word not in det['detail'].lower()


def test_gate_off_status_makes_no_request(gate_off, no_network):
    status = AsteraAdapter(sim=False).get_status()
    assert status['available'] is False
    assert 'FIVE12_ASTERA_TOOLS' in status['reason']
    assert status['alerts'] == []


def test_gate_off_wins_over_sim(gate_off, no_network, monkeypatch):
    """Sim mode is still Astera functionality; the gate governs it too."""
    monkeypatch.setenv('FIVE12_DEVICE_SIM', '1')
    det = AsteraAdapter(sim=True).detect()
    assert det['found'] is False
    assert 'FIVE12_ASTERA_TOOLS' in det['detail']


def test_gate_explicit_zero_is_off(no_network, monkeypatch):
    monkeypatch.setenv('FIVE12_ASTERA_TOOLS', '0')
    assert AsteraAdapter(sim=False).detect()['found'] is False


def test_gate_on_without_host_names_the_setting_and_stays_offline(no_network, monkeypatch):
    monkeypatch.setenv('FIVE12_ASTERA_TOOLS', '1')
    monkeypatch.delenv('FIVE12_ASTERA_HOST', raising=False)
    det = AsteraAdapter(sim=False).detect()
    assert det['found'] is False
    assert 'FIVE12_ASTERA_HOST' in det['detail']


def test_gate_off_status_carries_an_explicit_disabled_flag(gate_off, no_network):
    """The UI must distinguish 'we never looked' from 'we looked and failed'.
    A flag is a firmer contract than the reason string's wording."""
    status = AsteraAdapter(sim=False).get_status()
    assert status['disabled'] is True


def test_a_real_failure_is_not_marked_disabled(monkeypatch):
    monkeypatch.setenv('FIVE12_ASTERA_TOOLS', '1')
    monkeypatch.setenv('FIVE12_ASTERA_HOST', '192.168.1.50')
    adapter = AsteraAdapter(sim=False)
    def boom(key):
        raise ValueError('refused redirect (HTTP 302)')
    monkeypatch.setattr(adapter, '_fetch_json', boom)
    status = adapter.get_status()
    assert status['available'] is False
    assert status.get('disabled') is not True
