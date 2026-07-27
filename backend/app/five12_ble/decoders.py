"""Raw GATT bytes → display values. Pure, no I/O, no bleak.

Two rules hold everywhere in this module:

1. Never raise. An unrecognised value decodes to None. A firmware revision we
   have not captured must degrade gracefully, not crash a snapshot.
2. Never discard the raw bytes. Every result carries its hex so the UI can
   show the evidence behind a decoded label.
"""

from .constants import (
    Mode,
    OutputPower,
    RX_POWER_NOT_APPLICABLE,
    RX_PROTOCOL_NOT_APPLICABLE,
    TxProtocol,
)

# Raw enum, the official module table figure, and Toolbox's product-facing
# label are three different things and are kept separate deliberately.
_POWER_LABELS = {
    OutputPower.MAX: ('max', '20 dBm / ~100 mW', '>100 mW'),
    OutputPower.LEVEL_3: ('level-3', '16 dBm / ~40 mW', None),
    OutputPower.LEVEL_4: ('level-4', '11 dBm / ~13 mW', None),
    OutputPower.MIN: ('min', '5 dBm / ~3 mW', '5 mW'),
}

_PROTOCOL_LABELS = {
    TxProtocol.CRMX: 'crmx',
    TxProtocol.W_DMX_G3: 'w-dmx-g3',
    TxProtocol.W_DMX_G4S: 'w-dmx-g4s',
}


def _hex(raw):
    return (raw or b'').hex().upper()


def _one_byte(raw):
    """The single byte of a one-byte characteristic, or None."""
    return raw[0] if raw and len(raw) == 1 else None


def decode_name(raw):
    """Device name is null-padded UTF-8."""
    decoded = None
    if raw:
        try:
            decoded = raw.split(b'\x00', 1)[0].decode('utf-8') or None
        except UnicodeDecodeError:
            decoded = None
    return {'raw': _hex(raw), 'decoded': decoded}


def decode_battery(raw):
    """Standard Battery Service 0x2A19 — one byte, 0-100 percent."""
    value = _one_byte(raw)
    if value is not None and not 0 <= value <= 100:
        value = None
    return {'raw': _hex(raw), 'decoded': value}


def decode_firmware(raw):
    """Wire bytes are least-significant first. 02 07 00 01 displays as 1.0.7.2,
    confirmed against CRMX Toolbox on the captured unit."""
    decoded = None
    if raw and len(raw) == 4:
        decoded = '.'.join(str(b) for b in reversed(raw))
    return {'raw': _hex(raw), 'decoded': decoded}


def decode_mode(raw):
    value = _one_byte(raw)
    decoded = None
    if value == Mode.RX:
        decoded = 'rx'
    elif value == Mode.TX:
        decoded = 'tx'
    return {'raw': _hex(raw), 'decoded': decoded}


def decode_dmx_hold(raw):
    """DMX Hold keeps DMX output active on loss of connectivity."""
    value = _one_byte(raw)
    decoded = None
    if value == 0x00:
        decoded = False
    elif value == 0x01:
        decoded = True
    return {'raw': _hex(raw), 'decoded': decoded}


def decode_output_power(raw):
    value = _one_byte(raw)
    out = {
        'raw': _hex(raw),
        'decoded': None,
        'rawEnum': value,
        'moduleFigure': None,
        'toolboxLabel': None,
        'notApplicable': value == RX_POWER_NOT_APPLICABLE,
    }
    if value in _POWER_LABELS:
        label, module_figure, toolbox_label = _POWER_LABELS[value]
        out['decoded'] = label
        out['moduleFigure'] = module_figure
        out['toolboxLabel'] = toolbox_label
    return out


def decode_universe_color(raw):
    """Three RGB bytes. 00 FF 00 is Green."""
    decoded, rgb = None, None
    if raw and len(raw) == 3:
        rgb = list(raw)
        decoded = '#{:02X}{:02X}{:02X}'.format(*rgb)
    return {'raw': _hex(raw), 'decoded': decoded, 'rgb': rgb}


def decode_tx_protocol(raw):
    value = _one_byte(raw)
    return {
        'raw': _hex(raw),
        'decoded': _PROTOCOL_LABELS.get(value),
        'notApplicable': value == RX_PROTOCOL_NOT_APPLICABLE,
    }


def decode_link_status(raw):
    """LINK_ACTION ordinary reads: 01 observed in RX, 03 observed in TX.

    These are baseline status values whose full semantics are NOT established.
    This returns the observed value only. It deliberately exposes no boolean
    link state — an ATT-level value is not evidence of RF association.
    """
    value = _one_byte(raw)
    return {
        'raw': _hex(raw),
        'decoded': value,
        'note': 'observed status value; not proof of receiver association',
    }
