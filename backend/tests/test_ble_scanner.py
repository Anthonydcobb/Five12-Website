"""The scan service filters what bleak reports and feeds the registry.

handle_advertisement is pure with respect to bleak — it takes plain values, so
the whole filter/decode/store path is testable with no radio and no event loop.

The adapter lock is exercised with real subprocesses. An advisory lock exists
to exclude other *processes*; two objects in one interpreter would prove
nothing about the property that actually matters.
"""

import os
import subprocess
import sys
import threading
import time

import pytest

from app.five12_ble import constants as c
from app.five12_ble import scanner as scanner_mod
from app.five12_ble.scanner import BleScanService

# scanner_mod.__file__ is backend/app/five12_ble/scanner.py, so it takes THREE
# dirnames to reach backend/ — the directory that has to be on sys.path for
# `import app.five12_ble.scanner` to resolve. Two got you backend/app, and the
# children only worked because the cwd supplied backend/ when the suite was run
# from there. From the repository root the documented command failed here, in
# the child, for reasons that had nothing to do with the code under test.
BACKEND_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(scanner_mod.__file__)))
)

# Prelude every lock child shares: import the module under test from this
# checkout rather than whatever happens to be installed.
_CHILD_PRELUDE = (
    'import sys\n'
    'sys.path.insert(0, %r)\n'
    'from app.five12_ble.scanner import BleScanService\n' % BACKEND_DIR
)


def _run_child(body, timeout=60):
    """Run a snippet in a real second interpreter and return its stdout."""
    proc = subprocess.run(
        [sys.executable, '-c', _CHILD_PRELUDE + body],
        capture_output=True, text=True, timeout=timeout,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def adapter_lock_status():
    """Whether this process can take the machine-wide BLE adapter lock.

    Returns `(True, None)`, or `(False, reason)` naming what is holding it and
    the switch responsible. The lock is machine-wide by design — one radio, one
    owner — so an unrelated Five12 instance is enough to make every test that
    takes it fail, and the bare assertion failure points at the scanner instead
    of at the machine.
    """
    service = BleScanService()
    if service._acquire_adapter_lock():
        service._release_adapter_lock()
        return True, None
    return False, (
        'another process already holds the Five12 Bluetooth adapter lock. '
        'That is almost certainly the Five12 app running with '
        'FIVE12_BLE_TOOLS=1 — the app being up is not enough on its own, the '
        'BLE gate has to be on. Stop it, or start it with FIVE12_BLE_TOOLS=0, '
        'then re-run: these tests need to take the adapter lock themselves.'
    )


needs_adapter_lock = pytest.mark.skipif(
    not adapter_lock_status()[0],
    reason=adapter_lock_status()[1] or '',
)


def _live_scan_threads():
    return [t for t in threading.enumerate()
            if t.name == 'five12-ble-scan' and t.is_alive()]

TIMOTWO_UUIDS = [c.TIMOTWO_SERVICE_UUID]
MFR = {0xFFFF: bytes.fromhex('03F14000004C55F140')}


def test_timotwo_advertisement_is_recorded():
    svc = BleScanService()
    svc.handle_advertisement('os-1', 'F12L - 1946', -41, TIMOTWO_UUIDS, MFR, now=100.0)
    assert svc.registry.count() == 1
    assert svc.registry.get('os-1').local_name == 'F12L - 1946'


def test_unrelated_ble_device_is_ignored():
    """A room full of phones, headphones, and laptops must not fill the roster."""
    svc = BleScanService()
    svc.handle_advertisement('os-phone', 'Someones iPhone', -55,
                             ['0000180f-0000-1000-8000-00805f9b34fb'],
                             {0x004C: b'\x01\x02'}, now=100.0)
    assert svc.registry.count() == 0


def test_manufacturer_data_alone_is_enough_evidence():
    """Some stacks drop service UUIDs from the advertisement; matching
    manufacturer data still identifies the platform."""
    svc = BleScanService()
    svc.handle_advertisement('os-1', 'F12L - 1946', -41, [], MFR, now=100.0)
    assert svc.registry.count() == 1


def test_service_uuid_alone_is_enough_evidence():
    svc = BleScanService()
    svc.handle_advertisement('os-1', 'F12L - 1946', -41, TIMOTWO_UUIDS, {}, now=100.0)
    assert svc.registry.count() == 1
    assert 'service-uuid' in svc.registry.get('os-1').advert['evidence']


def test_uppercase_service_uuid_still_matches():
    svc = BleScanService()
    svc.handle_advertisement('os-1', 'n', -41,
                             [c.TIMOTWO_SERVICE_UUID.upper()], {}, now=100.0)
    assert svc.registry.count() == 1


def test_malformed_manufacturer_data_does_not_raise():
    svc = BleScanService()
    svc.handle_advertisement('os-1', 'n', -41, TIMOTWO_UUIDS, {0xFFFF: b'\x03'}, now=100.0)
    assert svc.registry.count() == 1
    assert svc.registry.get('os-1').advert['hardwareId'] is None


def test_repeat_advertisements_coalesce():
    svc = BleScanService()
    for i in range(10):
        svc.handle_advertisement('os-1', 'n', -50, TIMOTWO_UUIDS, MFR, now=100.0 + i)
    assert svc.registry.count() == 1


def test_sim_service_populates_registry_without_hardware():
    svc = BleScanService(sim=True)
    svc.poll_sim(now=100.0)
    assert svc.registry.count() == 2
    assert svc.status()['sim'] is True


def test_status_reports_not_running_before_start():
    svc = BleScanService()
    st = svc.status()
    assert st['running'] is False
    assert st['deviceCount'] == 0


def test_sim_status_reports_adapter_available():
    """Sim mode must never claim it needs hardware, or the panel shows a
    hardware error during a demo."""
    svc = BleScanService(sim=True)
    assert svc.status()['adapterAvailable'] is True


# ── adapter lock ─────────────────────────────────────────────────────────────
@needs_adapter_lock
def test_second_process_cannot_take_the_adapter_and_reports_not_owner():
    """Under gunicorn every worker imports this module. Only one may drive the
    radio; the rest must stand down instead of fighting for it."""
    svc = BleScanService()
    assert svc._acquire_adapter_lock() is True
    try:
        out = _run_child(
            'svc = BleScanService()\n'
            'svc.start()\n'
            'print(svc._lock_handle is None, svc.status()["lastError"],'
            '      svc.status()["running"], svc._thread is None)\n'
        )
        assert out == 'True not-owner False True'
    finally:
        svc._release_adapter_lock()


@needs_adapter_lock
def test_releasing_the_lock_lets_another_process_acquire():
    svc = BleScanService()
    assert svc._acquire_adapter_lock() is True
    svc._release_adapter_lock()

    out = _run_child(
        'svc = BleScanService()\n'
        'got = svc._acquire_adapter_lock()\n'
        'svc._release_adapter_lock()\n'
        'print(got)\n'
    )
    assert out == 'True'


@needs_adapter_lock
def test_lock_is_released_when_the_holding_process_dies():
    """No heartbeat, no staleness timeout: the kernel drops the lock when the
    owner dies, however it dies. A killed worker must not wedge the adapter."""
    holder = subprocess.Popen(
        [sys.executable, '-c', _CHILD_PRELUDE +
         'svc = BleScanService()\n'
         'assert svc._acquire_adapter_lock()\n'
         'print("HELD", flush=True)\n'
         'import time; time.sleep(120)\n'],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        assert holder.stdout.readline().strip() == 'HELD'
        svc = BleScanService()
        assert svc._acquire_adapter_lock() is False, 'live holder was ignored'
    finally:
        holder.kill()
        holder.wait(timeout=30)

    # The dead process called no release path whatsoever.
    deadline = time.time() + 10
    while True:
        svc = BleScanService()
        if svc._acquire_adapter_lock():
            svc._release_adapter_lock()
            break
        assert time.time() < deadline, 'lock survived the death of its owner'
        time.sleep(0.1)


def test_sim_services_bypass_the_lock_entirely():
    """Simulated devices need no radio, so sim must never contend for it."""
    a, b = BleScanService(sim=True), BleScanService(sim=True)
    assert a._acquire_adapter_lock() is True
    assert b._acquire_adapter_lock() is True
    assert a._lock_handle is None and b._lock_handle is None


def test_stop_then_start_does_not_leave_two_scan_threads():
    """stop() used to leave the old thread sleeping, and start() then cleared
    the Event they shared — un-stopping it and losing the reference."""
    assert _live_scan_threads() == []
    svc = BleScanService(sim=True)
    svc.start()
    first = svc._thread
    svc.stop()
    assert not first.is_alive()

    svc.start()
    try:
        assert svc._thread is not first
        assert not first.is_alive()
        assert len(_live_scan_threads()) == 1
    finally:
        svc.stop()
    assert _live_scan_threads() == []


def test_stop_is_safe_when_nothing_was_ever_started():
    BleScanService().stop()
    BleScanService(sim=True).stop()


@needs_adapter_lock
def test_stop_keeps_the_lock_when_the_join_times_out(monkeypatch):
    """A join() that times out must not be treated as "the thread is gone".
    Releasing the lock anyway would let an immediate start() acquire a fresh
    lock and spawn a second live scan thread while the first is still
    running — a same-process replay of the two-owners-of-one-radio failure
    the lock exists to prevent."""
    monkeypatch.setattr(scanner_mod, 'STOP_JOIN_TIMEOUT', 0.1)
    release = threading.Event()

    def _wedged_loop(self, stop):
        # Stands in for a thread stuck in bleak's async teardown, or behind
        # a hung radio driver: it ignores `stop` far longer than the
        # (patched) join timeout, but does eventually exit.
        release.wait(5)

    monkeypatch.setattr(BleScanService, '_run_loop', _wedged_loop)

    svc = BleScanService(sim=False)
    svc.start()
    assert svc._lock_handle is not None
    old_thread = svc._thread
    try:
        svc.stop()
        assert old_thread.is_alive(), 'test setup bug: thread exited before join timed out'
        assert svc._lock_handle is not None, \
            'lock released while its scan thread is still alive'

        # Without the fix, the freed lock lets a second thread spawn here.
        svc.start()
        assert svc._thread is old_thread, 'start() must not spawn a second thread'
        assert len(_live_scan_threads()) == 1
        assert svc._last_error == 'previous-scan-thread-still-running'
    finally:
        release.set()
        old_thread.join(timeout=5)
        svc._release_adapter_lock()
    assert _live_scan_threads() == []


@needs_adapter_lock
def test_stop_logs_a_warning_when_the_join_times_out(monkeypatch, caplog):
    monkeypatch.setattr(scanner_mod, 'STOP_JOIN_TIMEOUT', 0.1)
    release = threading.Event()

    def _wedged_loop(self, stop):
        release.wait(5)

    monkeypatch.setattr(BleScanService, '_run_loop', _wedged_loop)

    svc = BleScanService(sim=False)
    svc.start()
    thread = svc._thread
    try:
        with caplog.at_level('WARNING', logger=scanner_mod.log.name):
            svc.stop()
        assert any(rec.levelname == 'WARNING' and 'did not stop' in rec.getMessage()
                   for rec in caplog.records), \
            'join timeout must be logged, not silent'
        assert '0.1' in caplog.text
    finally:
        release.set()
        thread.join(timeout=5)
        svc._release_adapter_lock()


# ── The adapter lock is machine-wide, so the environment can break these ──────
#
# Every test above that takes the lock fails as `assert '' == 'HELD'` when
# something else on the machine already holds it. That reads like a defect in
# the scanner. It is not: it is the Five12 app running with FIVE12_BLE_TOOLS=1,
# which takes the adapter lock at startup and keeps it.
#
# Observed three times on 2026-07-30 while working on unrelated branches, and
# misdiagnosed the first time as "the app is running" — the app being up is not
# sufficient, it has to be up with the BLE gate on. Nothing in the failure said
# either thing.

@needs_adapter_lock
def test_it_reports_the_real_reason_when_the_adapter_is_held_elsewhere():
    """With the lock held by another process the report must name that, and
    name the switch that causes it, rather than leaving `assert '' == 'HELD'`."""
    holder = subprocess.Popen(
        [sys.executable, '-c', _CHILD_PRELUDE +
         'svc = BleScanService()\n'
         'assert svc._acquire_adapter_lock()\n'
         'print("HELD", flush=True)\n'
         'import time; time.sleep(120)\n'],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        assert holder.stdout.readline().strip() == 'HELD'

        available, reason = adapter_lock_status()

        assert available is False
        assert 'adapter lock' in reason.lower()
        assert 'FIVE12_BLE_TOOLS' in reason
    finally:
        holder.kill()
        holder.wait(timeout=10)


@needs_adapter_lock
def test_it_reports_available_when_nothing_holds_the_adapter():
    available, reason = adapter_lock_status()
    assert available is True
    assert reason is None
