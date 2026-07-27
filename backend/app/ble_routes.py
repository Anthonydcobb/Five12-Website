"""Bluetooth device routes — read-only CRMX/TimoTwo discovery.

Registered ONLY when ENABLE_BLE_TOOLS is set, so with the gate off these
routes do not exist rather than returning 403.

Every route here is a GET. This module contains no write path: configuration
writes, TX Link, and RX Unlink are a later, separately gated piece of work.
"""

import asyncio
import sys

from flask import Blueprint, jsonify, request

from .five12_ble.errors import BleError, DeviceNotFound
from .five12_ble.gatt_client import build_sim_snapshot, build_snapshot
from .five12_ble.scanner import get_scan_service
from .integrations import sim_enabled

ble = Blueprint('ble', __name__, url_prefix='/api/ble')


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
    """Connect, read the allowlisted characteristics, disconnect."""
    service = _service()

    if service.sim:
        snap = build_sim_snapshot(os_id)
        if snap is None:
            return jsonify(DeviceNotFound(detail=os_id).to_dict()), 404
        return jsonify(snap)

    if service.registry.get(os_id) is None:
        return jsonify(DeviceNotFound(detail=os_id).to_dict()), 404

    try:
        return jsonify(asyncio.run(_read_snapshot(os_id)))
    except BleError as exc:
        return jsonify(exc.to_dict()), 409


async def _read_snapshot(os_id):
    from .five12_ble.connection_manager import connect
    async with connect(os_id) as client:
        return await build_snapshot(client, os_id)
