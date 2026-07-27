"""Read-only connected status snapshot.

Reads only characteristics in the verified allowlist that the device actually
advertises. A per-field failure yields one null field with an error string; it
never fails the whole device.

This module contains no write path.
"""

import time

from . import constants as c
from . import decoders as d
from .sim import sim_gatt_values

# field name → (uuid, decoder, source). Order is the read order.
_FIELDS = (
    ('name', c.DEVICE_NAME, d.decode_name, 'gatt-read'),
    ('battery', c.BATTERY_LEVEL, d.decode_battery, 'gatt-read'),
    ('firmware', c.FIRMWARE_VERSION, d.decode_firmware, 'gatt-read'),
    ('mode', c.MODE, d.decode_mode, 'gatt-read'),
    ('dmxHold', c.DMX_HOLD, d.decode_dmx_hold, 'gatt-read'),
    ('outputPower', c.OUTPUT_POWER, d.decode_output_power, 'gatt-read'),
    ('universeColor', c.UNIVERSE_COLOR, d.decode_universe_color, 'gatt-read'),
    ('txProtocol', c.TX_PROTOCOL, d.decode_tx_protocol, 'gatt-read'),
    ('modeMirror', c.MODE_MIRROR, d.decode_mode, 'mirror'),
    ('colorMirror', c.COLOR_MIRROR, d.decode_universe_color, 'mirror'),
    ('linkStatus', c.LINK_ACTION, d.decode_link_status, 'mirror'),
)


def _finish(decoded, source, now, error=None):
    out = dict(decoded)
    out['source'] = source
    out['readAt'] = now
    if error:
        out['error'] = error
        out['decoded'] = None
    return out


async def build_snapshot(client, os_id, now=None):
    """Read every allowlisted characteristic the device exposes.

    `client` needs only `has_characteristic(uuid)` and
    `async read_gatt_char(uuid) -> bytes`, which keeps this testable with a
    fake and keeps bleak out of this module entirely.
    """
    now = time.time() if now is None else now
    fields, warnings = {}, []

    for name, uuid, decoder, source in _FIELDS:
        if not client.has_characteristic(uuid):
            warnings.append(f'{name}: characteristic not present on this device')
            continue
        try:
            raw = await client.read_gatt_char(uuid)
            fields[name] = _finish(decoder(raw), source, now)
        except Exception as exc:
            fields[name] = _finish(decoder(b''), source, now, error=str(exc))

    return {
        'osId': os_id,
        'readAt': now,
        'fields': fields,
        'warnings': warnings,
    }


def build_sim_snapshot(os_id, now=None):
    """Same shape as build_snapshot, without a radio or an event loop."""
    values = sim_gatt_values(os_id)
    if not values:
        return None
    now = time.time() if now is None else now
    fields = {
        name: _finish(decoder(values[uuid]), source, now)
        for name, uuid, decoder, source in _FIELDS
        if uuid in values
    }
    return {'osId': os_id, 'readAt': now, 'fields': fields, 'warnings': []}
