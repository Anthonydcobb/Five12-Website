"""Bluetooth device routes — read-only CRMX/TimoTwo discovery.

Registered ONLY when ENABLE_BLE_TOOLS is set, so with the gate off these
routes do not exist rather than returning 403.

This module contains no write path. Configuration writes, TX Link, and RX
Unlink are a later, separately gated piece of work.
"""

import sys

from flask import Blueprint, jsonify

ble = Blueprint('ble', __name__, url_prefix='/api/ble')


def _platform_supported():
    """bleak supports Windows 10+ / macOS / Linux with BlueZ. Five12's target
    is Windows 11, so anything else is 'works, unverified' rather than a hard
    no — report the platform honestly and let the UI phrase it."""
    return sys.platform in ('win32', 'darwin', 'linux')


def _adapter_available():
    """True when a usable Bluetooth adapter is present. Task 6 replaces this
    with a real bleak probe; until the scanner exists there is nothing to ask."""
    return False


@ble.get('/capabilities')
def capabilities():
    return jsonify({
        'bleToolsEnabled': True,   # this route only exists when the gate is on
        'adapterAvailable': _adapter_available(),
        'platformSupported': _platform_supported(),
    })
