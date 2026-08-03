"""Astera adapter — registration in the device framework.

Astera appears through the generic three routes like every device; the gate
governs behavior inside the adapter, so listing it while disabled shows an
honest 'disabled' card and triggers no network activity (test_astera_gate
proves the no-network half).
"""

from app.integrations import ALL_DEVICE_IDS, get_adapter
from app.integrations.astera import AsteraAdapter


def test_astera_is_a_known_device():
    assert 'astera' in ALL_DEVICE_IDS


def test_registry_returns_the_astera_adapter_cached():
    a = get_adapter('astera', sim=True)
    assert isinstance(a, AsteraAdapter)
    assert a.sim is True
    assert get_adapter('astera', sim=True) is a


def test_device_listing_shows_astera_disabled_by_default(client, monkeypatch):
    monkeypatch.delenv('FIVE12_ASTERA_TOOLS', raising=False)
    rows = {d['id']: d for d in client.get('/api/devices').get_json()}
    assert rows['astera']['found'] is False
    assert 'FIVE12_ASTERA_TOOLS' in rows['astera']['detail']


def test_config_gate_defaults_off_in_both_configs(monkeypatch):
    """The constant documents the gate for both runtimes; the adapter reads
    the env var directly at call time (registry instances outlive config)."""
    monkeypatch.delenv('FIVE12_ASTERA_TOOLS', raising=False)
    import importlib
    import config as config_module
    fresh = importlib.reload(config_module)
    assert fresh.DevelopmentConfig.ENABLE_ASTERA_TOOLS is False
    assert fresh.DesktopConfig.ENABLE_ASTERA_TOOLS is False
