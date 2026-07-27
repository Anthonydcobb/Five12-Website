"""Bluetooth device routes — read-only CRMX/TimoTwo discovery.

Registered ONLY when ENABLE_BLE_TOOLS is set, so with the gate off these
routes do not exist rather than returning 403.

Every route here is a GET. This module contains no write path: configuration
writes, TX Link, and RX Unlink are a later, separately gated piece of work.
"""

import asyncio
import logging
import sys
from concurrent.futures import TimeoutError as FutureTimeoutError

from flask import Blueprint, jsonify, request

from .five12_ble.errors import (
    BleError,
    DeviceNotFound,
    OperationTimeout,
    ScanLoopUnavailable,
    UnexpectedBleFailure,
)
from .five12_ble.gatt_client import build_sim_snapshot, build_snapshot
from .five12_ble.scanner import get_scan_service
from .integrations import sim_enabled

log = logging.getLogger(__name__)

ble = Blueprint('ble', __name__, url_prefix='/api/ble')

# Generous outer bound on waiting for the scan-loop future to resolve. The
# real timeouts — connect, per-characteristic read, disconnect — are already
# enforced inside connection_manager/gatt_client; this is only a backstop so
# a hang in something those bounds don't cover cannot wedge the Flask request
# thread (and, transitively, the caller) forever.
SNAPSHOT_FUTURE_TIMEOUT = 90.0


def _platform_supported():
    """bleak supports Windows 10+ / macOS / Linux with BlueZ. Five12's target
    is Windows 11; anything else is 'works, unverified' rather than a hard no."""
    return sys.platform in ('win32', 'darwin', 'linux')


def _service():
    return get_scan_service(sim_enabled(request.args))


@ble.get('/capabilities')
def capabilities():
    st = _service().status()
    return jsonify({
        'bleToolsEnabled': True,   # this route only exists when the gate is on
        'adapterAvailable': st['adapterAvailable'],
        'platformSupported': _platform_supported(),
        'sim': st['sim'],
    })


@ble.get('/status')
def status():
    return jsonify(_service().status())


@ble.get('/devices')
def list_devices():
    """Nearby radios, from passive advertisements only.

    NEARBY IS NOT CONNECTED — entries carry no GATT fields. Battery, firmware,
    and mode appear only after an explicit snapshot request.
    """
    service = _service()
    if service.sim:
        service.poll_sim()
    devices = [d.to_dict() for d in service.registry.all()]
    return jsonify({'deviceCount': len(devices), 'devices': devices})


@ble.get('/devices/<os_id>/snapshot')
def device_snapshot(os_id):
    """Connect, read the allowlisted characteristics, disconnect.

    This runs on the scan service's OWN bleak event loop rather than a fresh
    one opened here. bleak/WinRT only tolerates one loop driving the adapter
    at a time; the scan service already owns such a loop for the life of the
    process (see BleScanService.loop), so this route submits its coroutine to
    that loop instead of racing it with a second one on the request thread.
    """
    service = _service()

    if service.sim:
        # Sim snapshots are fully synchronous — no bleak, no event loop, so
        # this must stay entirely outside the branch below.
        snap = build_sim_snapshot(os_id)
        if snap is None:
            return jsonify(DeviceNotFound(detail=os_id).to_dict()), 404
        return jsonify(snap)

    if service.registry.get(os_id) is None:
        return jsonify(DeviceNotFound(detail=os_id).to_dict()), 404

    loop = service.loop
    if loop is None:
        # No scan thread is currently driving the adapter — either the
        # service was never started or it failed to acquire the adapter —
        # so there is no loop to submit to. Falling back to asyncio.run()
        # here would silently reintroduce the exact two-loops-one-adapter
        # hazard this route exists to avoid, so this is a typed error
        # instead of a fallback.
        return jsonify(ScanLoopUnavailable(detail=os_id).to_dict()), 409

    future = asyncio.run_coroutine_threadsafe(_read_snapshot(os_id), loop)
    try:
        result = future.result(timeout=SNAPSHOT_FUTURE_TIMEOUT)
    except BleError as exc:
        return jsonify(exc.to_dict()), 409
    except FutureTimeoutError:
        # The future itself never resolved inside our backstop window.
        # Cancel it so a wedged operation doesn't keep the scan loop (and the
        # adapter) tied up indefinitely after we've already given up on it.
        future.cancel()
        return jsonify(OperationTimeout(detail=os_id).to_dict()), 409
    except Exception as exc:
        # Anything untranslated — an OSError from a disabled adapter, a
        # WinRT-backend exception bleak doesn't wrap, a RuntimeError from
        # loop handling — must still reach the client as the typed shape the
        # frontend expects, never a raw 500 with a traceback. The real
        # exception is logged server-side for diagnosis; the client gets an
        # honest, non-leaking, operator-actionable message instead.
        log.error(
            'BLE: unexpected error reading snapshot for %s: %s',
            os_id, exc, exc_info=True,
        )
        return jsonify(UnexpectedBleFailure(detail=os_id).to_dict()), 409

    return jsonify(result)


async def _read_snapshot(os_id):
    from .five12_ble.connection_manager import connect
    async with connect(os_id) as client:
        return await build_snapshot(client, os_id)
