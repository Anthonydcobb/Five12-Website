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


# ── W1 (Hermes review 2026-08-03): non-mapping payloads ─────────────────────
# The protocol is unverified, so "valid JSON of an unexpected shape" is a real
# possibility, not a hypothetical. It must read as unavailable-with-a-reason,
# never as a 500 and never as fabricated data.

@pytest.mark.parametrize('bad', [None, [], 'a string', 42])
def test_non_mapping_status_payload_reads_as_unavailable(adapter, monkeypatch, bad):
    _wire(monkeypatch, adapter, status=bad)
    s = adapter.get_status()
    assert s['available'] is False
    assert 'unexpected' in s['reason'].lower()
    assert s['alerts'] == []


@pytest.mark.parametrize('bad', [None, [], 'a string', 42])
def test_non_mapping_targets_payload_reads_as_unavailable(adapter, monkeypatch, bad):
    _wire(monkeypatch, adapter, targets=bad)
    s = adapter.get_status()
    assert s['available'] is False
    assert 'unexpected' in s['reason'].lower()


def test_non_mapping_bridge_field_does_not_crash(adapter, monkeypatch):
    """A nested field of the wrong type is likelier than a wrong top level:
    one renamed key in an unverified payload is enough."""
    _wire(monkeypatch, adapter, status={**RAW_STATUS, 'bridge': []})
    s = adapter.get_status()
    assert s['available'] is True
    assert s['bridge'] == {'name': None, 'batteryPct': None}


def test_non_mapping_targets_list_entries_are_skipped(adapter, monkeypatch):
    _wire(monkeypatch, adapter,
          targets={'targets': ['nonsense', None, RAW_TARGETS['targets'][0]]})
    s = adapter.get_status()
    assert s['targetCount'] == 1
    assert s['targets'][0]['name'] == 'Key Tubes'


def test_targets_key_of_the_wrong_type_yields_no_targets(adapter, monkeypatch):
    _wire(monkeypatch, adapter, targets={'targets': 'not a list'})
    s = adapter.get_status()
    assert s['available'] is True
    assert s['targets'] == []


# ── S1 (Hermes review 2026-08-03): alias width ──────────────────────────────

def test_pin_alias_is_wide_enough_to_distinguish_every_four_digit_pin():
    """A 4-hex alias is 16 bits; across the 10 000 possible PINs collisions are
    near-certain, and a collision reads as 'the PIN did not change' — the exact
    confidently-wrong-value failure this project keeps hitting. Widened to 8."""
    from app.integrations.astera import _pin_alias
    aliases = {_pin_alias(pin) for pin in range(10000)}
    assert len(aliases) == 10000
    assert len(_pin_alias(1234)) == len('PIN-') + 8
