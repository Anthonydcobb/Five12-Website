"""The starlink-grpc-tools location is configuration, not a launch incantation.

`starlink_grpc` cannot be pip-installed, so its directory has to reach sys.path
somehow. PYTHONPATH works but only for whoever remembers to set it; start.ps1
does not, so live telemetry would quietly revert to unavailable the next time
anyone launched the app normally.
"""
import os
import sys

import pytest

from app.integrations.starlink import (
    GRPC_PATH_ENV, StarlinkAdapter, _ensure_grpc_path,
)


@pytest.fixture(autouse=True)
def _restore_sys_path(monkeypatch):
    original = list(sys.path)
    yield
    sys.path[:] = original


def test_unset_env_adds_nothing(monkeypatch):
    monkeypatch.delenv(GRPC_PATH_ENV, raising=False)
    before = list(sys.path)
    assert _ensure_grpc_path() is None
    assert sys.path == before


def test_configured_directory_is_added(monkeypatch, tmp_path):
    monkeypatch.setenv(GRPC_PATH_ENV, str(tmp_path))
    assert _ensure_grpc_path() == str(tmp_path)
    assert str(tmp_path) in sys.path


def test_adding_is_idempotent(monkeypatch, tmp_path):
    """Status is read repeatedly; sys.path must not grow without bound."""
    monkeypatch.setenv(GRPC_PATH_ENV, str(tmp_path))
    _ensure_grpc_path()
    _ensure_grpc_path()
    _ensure_grpc_path()
    assert sys.path.count(str(tmp_path)) == 1


def test_missing_directory_is_not_added(monkeypatch, tmp_path):
    """A typo must not silently look like the feature being switched off."""
    ghost = tmp_path / 'does-not-exist'
    monkeypatch.setenv(GRPC_PATH_ENV, str(ghost))
    before = list(sys.path)
    assert _ensure_grpc_path() is None
    assert sys.path == before


def test_quoted_windows_path_is_tolerated(monkeypatch, tmp_path):
    """set FIVE12_STARLINK_GRPC_PATH="C:\dev\..." keeps the quotes."""
    monkeypatch.setenv(GRPC_PATH_ENV, f'"{tmp_path}"')
    assert _ensure_grpc_path() == str(tmp_path)


def test_reason_names_the_env_var_when_unset(monkeypatch):
    monkeypatch.delenv(GRPC_PATH_ENV, raising=False)
    status = StarlinkAdapter()._real_status()
    if status.get('available'):
        pytest.skip('starlink_grpc importable in this environment')
    assert GRPC_PATH_ENV in status['reason']
    assert 'PYTHONPATH' not in status['reason'], 'should point at the config knob'


def test_reason_distinguishes_a_bad_path(monkeypatch, tmp_path):
    """'set it' and 'you set it wrong' need different actions."""
    ghost = tmp_path / 'nope'
    monkeypatch.setenv(GRPC_PATH_ENV, str(ghost))
    status = StarlinkAdapter()._real_status()
    if status.get('available'):
        pytest.skip('starlink_grpc importable in this environment')
    assert 'does not exist' in status['reason']
    assert str(ghost) in status['reason']
