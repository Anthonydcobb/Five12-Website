"""The gate is the load-bearing safety property: with FIVE12_MIRROR_TOOLS
unset, this feature must not spawn a process. subprocess.run is poisoned so a
single call fails the suite."""
import pytest

from app.integrations import android_mirror


@pytest.fixture
def poisoned(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError('subprocess was spawned with the gate off')
    monkeypatch.setattr(android_mirror.subprocess, 'run', boom)


def test_gate_off_detect_spawns_nothing(monkeypatch, poisoned):
    monkeypatch.delenv('FIVE12_MIRROR_TOOLS', raising=False)
    monkeypatch.setenv('FIVE12_MIRROR_SERIAL', 'TESTSERIAL')
    result = android_mirror.AndroidMirrorAdapter().detect()
    assert result['found'] is False
    assert result['address'] is None
    assert 'FIVE12_MIRROR_TOOLS' in result['detail']


def test_gate_explicitly_zero_spawns_nothing(monkeypatch, poisoned):
    monkeypatch.setenv('FIVE12_MIRROR_TOOLS', '0')
    monkeypatch.setenv('FIVE12_MIRROR_SERIAL', 'TESTSERIAL')
    assert android_mirror.AndroidMirrorAdapter().detect()['found'] is False


def test_gate_on_without_serial_spawns_nothing(monkeypatch, poisoned):
    monkeypatch.setenv('FIVE12_MIRROR_TOOLS', '1')
    monkeypatch.delenv('FIVE12_MIRROR_SERIAL', raising=False)
    result = android_mirror.AndroidMirrorAdapter().detect()
    assert result['found'] is False
    assert 'FIVE12_MIRROR_SERIAL' in result['detail']


def test_serial_is_never_read_from_a_caller(monkeypatch):
    """The adapter exposes no way to pass a serial in. If this ever fails,
    a request could name a target — the exact thing the security model forbids."""
    import inspect
    monkeypatch.setenv('FIVE12_MIRROR_SERIAL', 'FROMCONFIG')
    sig = inspect.signature(android_mirror.AndroidMirrorAdapter.__init__)
    assert set(sig.parameters) <= {'self', 'sim'}
    assert android_mirror._serial() == 'FROMCONFIG'


def test_detect_reports_online_device(monkeypatch):
    monkeypatch.setenv('FIVE12_MIRROR_TOOLS', '1')
    monkeypatch.setenv('FIVE12_MIRROR_SERIAL', 'TESTSERIAL')
    calls = []

    def fake_run(args, timeout, binary=False):
        calls.append(args)
        return True, 'List of devices attached\nTESTSERIAL\tdevice\n', ''

    monkeypatch.setattr(android_mirror, '_run_adb', fake_run)
    result = android_mirror.AndroidMirrorAdapter().detect()
    assert result['found'] is True
    assert result['address'] == 'TESTSERIAL'
    assert calls == [['devices']]


def test_detect_reports_offline_device(monkeypatch):
    monkeypatch.setenv('FIVE12_MIRROR_TOOLS', '1')
    monkeypatch.setenv('FIVE12_MIRROR_SERIAL', 'TESTSERIAL')
    monkeypatch.setattr(
        android_mirror, '_run_adb',
        lambda args, timeout, binary=False: (True, 'List of devices attached\nTESTSERIAL\toffline\n', ''))
    result = android_mirror.AndroidMirrorAdapter().detect()
    assert result['found'] is False
    assert 'offline' in result['detail']
