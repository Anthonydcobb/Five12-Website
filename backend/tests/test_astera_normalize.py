"""Astera adapter — normalization of AsteraNext /api/status and /api/targets.

[UNVERIFIED] These payload shapes are hypotheses from static analysis of
AsteraNext 13.18 — no live server has been captured. The adapter therefore
labels every real read protocolVerified=False, and the normalizer must not
crash on missing fields. The fixtures below are the shapes we EXPECT; the
bench session will correct them.

PIN hygiene (agreed direction): the raw Radio PIN never appears in a status
payload, log, or history sample — only a deterministic alias.
"""

import json

import pytest

from app.integrations.astera import AsteraAdapter

RAW_STATUS = {
    'online': True,
    'pin': 4321,
    'version': '13.18',
    'platform': 'Android',
    'hostIp': '192.168.1.50',
    'bridge': {'name': 'ART7 90210', 'battery': 82},
}

RAW_TARGETS = {
    'targets': [
        {'id': 1, 'uuid': 'aaa-1', 'name': 'Key Tubes', 'brightness': 80,
         'selected': True, 'x': 0, 'y': 0},
        {'id': 2, 'uuid': 'bbb-2', 'name': 'BG NYX', 'brightness': 45,
         'selected': False, 'x': 1, 'y': 0},
    ],
}


@pytest.fixture
def adapter(monkeypatch):
    monkeypatch.setenv('FIVE12_ASTERA_TOOLS', '1')
    monkeypatch.setenv('FIVE12_ASTERA_HOST', '192.168.1.50')
    return AsteraAdapter(sim=False)


def _wire(monkeypatch, adapter, status=RAW_STATUS, targets=RAW_TARGETS):
    payloads = {'status': status, 'targets': targets}
    monkeypatch.setattr(adapter, '_fetch_json', lambda key: payloads[key])


def test_status_normalizes_the_expected_shape(adapter, monkeypatch):
    _wire(monkeypatch, adapter)
    s = adapter.get_status()
    assert s['available'] is True
    assert s['simulated'] is False
    assert s['appOnline'] is True
    assert s['appVersion'] == '13.18'
    assert s['bridge'] == {'name': 'ART7 90210', 'batteryPct': 82}
    assert s['targetCount'] == 2
    assert [t['name'] for t in s['targets']] == ['Key Tubes', 'BG NYX']
    assert s['targets'][0]['selected'] is True
    assert s['targets'][0]['brightnessPct'] == 80


def test_real_reads_are_labeled_protocol_unverified(adapter, monkeypatch):
    _wire(monkeypatch, adapter)
    assert adapter.get_status()['protocolVerified'] is False


def test_raw_pin_never_appears_anywhere_in_status(adapter, monkeypatch):
    _wire(monkeypatch, adapter)
    s = adapter.get_status()
    history = [{k: v for k, v in sample.items() if k != 'ts'}
               for sample in adapter.get_history()]
    blob = json.dumps(s) + json.dumps(history)
    assert '4321' not in blob
    assert s['radioPinAlias'].startswith('PIN-')


def test_pin_alias_is_deterministic_and_pin_sensitive(adapter, monkeypatch):
    _wire(monkeypatch, adapter)
    first = adapter.get_status()['radioPinAlias']
    second = adapter.get_status()['radioPinAlias']
    assert first == second
    _wire(monkeypatch, adapter, status={**RAW_STATUS, 'pin': 1111})
    assert adapter.get_status()['radioPinAlias'] != first


def test_missing_fields_do_not_crash_the_normalizer(adapter, monkeypatch):
    _wire(monkeypatch, adapter, status={}, targets={})
    s = adapter.get_status()
    assert s['available'] is True
    assert s['appOnline'] is None
    assert s['bridge'] == {'name': None, 'batteryPct': None}
    assert s['targets'] == []
    assert s['radioPinAlias'] is None


def test_fetch_failure_reports_reason_not_fake_data(adapter, monkeypatch):
    def boom(key):
        raise ValueError('refused redirect (HTTP 302)')
    monkeypatch.setattr(adapter, '_fetch_json', boom)
    s = adapter.get_status()
    assert s['available'] is False
    assert 'redirect' in s['reason']
    assert s['alerts'] == []


def test_low_bridge_battery_raises_a_crit_alert(adapter, monkeypatch):
    _wire(monkeypatch, adapter,
          status={**RAW_STATUS, 'bridge': {'name': 'ART7', 'battery': 12}})
    alerts = adapter.get_status()['alerts']
    assert any(a['level'] == 'crit' and '12' in a['message'] for a in alerts)
