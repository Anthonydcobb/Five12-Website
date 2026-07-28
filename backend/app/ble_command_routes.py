"""The ONLY mutating Bluetooth routes in the app.

Registered only when BOTH ENABLE_BLE_TOOLS and ENABLE_BLE_WRITE are set, so
with either gate off these endpoints do not exist rather than returning 403.

The request body names a COMMAND. It cannot name a characteristic UUID or a
payload byte — those live in command_service.COMMANDS and nowhere else. Extra
fields in the body are ignored, never honoured.
"""

import asyncio
import logging
from concurrent.futures import TimeoutError as FutureTimeoutError

from flask import Blueprint, jsonify, request

from .five12_ble.command_service import execute_command, prepare_command
from .five12_ble.errors import (
    BleError,
    DeviceNotFound,
    OperationTimeout,
    ScanLoopUnavailable,
    UnexpectedBleFailure,
)
from .five12_ble.scanner import get_scan_service
from .integrations import sim_enabled

log = logging.getLogger(__name__)

ble_write = Blueprint('ble_write', __name__, url_prefix='/api/ble')

# Generous outer bound. A mode write legitimately takes tens of seconds
# (write, reboot, rediscover, reconnect, re-read), so this must comfortably
# exceed REBOOT_REDISCOVERY_TIMEOUT_S without being unbounded.
COMMAND_FUTURE_TIMEOUT = 120.0


def _run(coro_factory, os_id, sim):
    """Run a command coroutine and translate every failure into the typed
    {code, message} shape the panel renders.

    Sim runs synchronously via asyncio.run: there is no radio and no shared
    loop to protect. The real path submits to the scan service's own loop for
    the same reason device_snapshot does — bleak/WinRT tolerates exactly one
    loop driving the adapter, and the scan service already owns it.
    """
    service = get_scan_service(sim)

    if sim:
        # The sim registry is populated lazily by whoever polls first. The read
        # route does this too; without it a command against a simulated radio
        # would 404 until the roster happened to be fetched. (Recorded in the
        # handoff as the split sim-polling responsibility.)
        service.poll_sim()
        try:
            return jsonify(asyncio.run(coro_factory(service.registry)))
        except BleError:
            # Command-service rejections (WrongMode, ConfirmationInvalid,
            # DeviceNotFound, ...) are translated by _catch_sim_errors, which
            # wraps this whole call; let them propagate there unchanged
            # rather than relabelling them as unexpected failures here.
            raise
        except Exception as exc:
            # Same contract as the real path below: asyncio.run() on this
            # branch can still raise something untranslated -- notably the
            # RuntimeError it raises when the request thread already has a
            # running event loop, the non-sync-worker caveat documented in
            # ble_routes.py. Never let that reach the client as a raw
            # 500/traceback; log it server-side and return the typed shape.
            log.error('BLE: unexpected error running sim command for %s: %s',
                      os_id, exc, exc_info=True)
            return jsonify(UnexpectedBleFailure(detail=os_id).to_dict()), 409

    if service.registry.get(os_id) is None:
        return jsonify(DeviceNotFound(detail=os_id).to_dict()), 404

    loop = service.loop
    if loop is None:
        return jsonify(ScanLoopUnavailable(detail=os_id).to_dict()), 409

    try:
        future = asyncio.run_coroutine_threadsafe(coro_factory(service.registry), loop)
        return jsonify(future.result(timeout=COMMAND_FUTURE_TIMEOUT))
    except FutureTimeoutError:
        future.cancel()
        return jsonify(OperationTimeout(detail=os_id).to_dict()), 409
    except BleError as exc:
        return jsonify(exc.to_dict()), 409
    except Exception as exc:
        # Never leak a traceback or a raw WinRT string to the operator; log it
        # server-side and return the typed shape the frontend expects.
        log.error('BLE: unexpected error running command for %s: %s',
                  os_id, exc, exc_info=True)
        return jsonify(UnexpectedBleFailure(detail=os_id).to_dict()), 409


def _catch_sim_errors(handler):
    """Translate command-service rejections into HTTP responses -- but only
    for the SIM path.

    On the real (non-sim) path, `_run` already returns a typed tuple for
    every BleError case itself (the registry pre-check's 404,
    ScanLoopUnavailable, the FutureTimeoutError translation, the generic
    Exception translation) before this wrapper is ever reached, so the
    `except DeviceNotFound` / `except BleError` below can never fire there --
    `_run` RETURNS rather than raises. The sim branch is different: it calls
    `coro_factory` directly and lets any BleError it raises (WrongMode,
    ConfirmationInvalid, DeviceNotFound, ...) propagate out of `_run`
    unhandled, so this is the only place those become HTTP responses.
    """
    try:
        return handler()
    except DeviceNotFound as exc:
        return jsonify(exc.to_dict()), 404
    except BleError as exc:
        return jsonify(exc.to_dict()), 409


@ble_write.post('/devices/<os_id>/commands/prepare')
def prepare(os_id):
    """Step one: read the radio's real mode and mint a confirmation bound to
    it. Nothing is written here."""
    sim = sim_enabled(request.args)
    command = (request.get_json(silent=True) or {}).get('command', '')
    return _catch_sim_errors(lambda: _run(
        lambda registry: prepare_command(os_id, command, registry, sim=sim),
        os_id, sim))


@ble_write.post('/devices/<os_id>/commands')
def execute(os_id):
    """Step two: re-check everything server-side and write."""
    sim = sim_enabled(request.args)
    body = request.get_json(silent=True) or {}
    command = body.get('command', '')
    expected_mode = body.get('expectedMode')
    token = body.get('confirmationToken', '')
    return _catch_sim_errors(lambda: _run(
        lambda registry: execute_command(
            os_id, command, expected_mode, token, registry, sim=sim),
        os_id, sim))
