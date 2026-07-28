"""Mode-gated, allowlisted, confirmed writes — the ENTIRE write surface.

The read-only phase had no write path because this module did not exist. That
was structural, not a promise. Now that it does exist, the same structure
confines every write to this one file.

The client posts a command NAME. This module maps it to a UUID and a payload
byte. The client can name neither, which is what makes "no arbitrary UUID
write path" impossible by construction rather than policed by review.

Pure enough to import without bleak: nothing here opens a radio. The one
function that connects imports connection_manager lazily.
"""

from dataclasses import dataclass

from . import constants as c


@dataclass(frozen=True)
class CommandSpec:
    """One row of the write policy.

    required_mode lists the modes the device may be in for this command to be
    legal. A device whose MODE does not decode is in none of them, so an
    unknown mode blocks every command.
    """

    name: str
    uuid: str
    payload: bytes
    required_mode: tuple
    verification: str   # 'reboot-tolerant' | 'ack-only'
    warning: str


COMMANDS = {
    'set_mode_rx': CommandSpec(
        name='set_mode_rx',
        uuid=c.MODE,
        payload=bytes([c.Mode.RX]),
        required_mode=('rx', 'tx'),
        verification='reboot-tolerant',
        warning=(
            'This radio will restart and disappear for several seconds. '
            'If it is currently transmitting, everything it feeds goes dark.'
        ),
    ),
    'set_mode_tx': CommandSpec(
        name='set_mode_tx',
        uuid=c.MODE,
        payload=bytes([c.Mode.TX]),
        required_mode=('rx', 'tx'),
        verification='reboot-tolerant',
        warning=(
            'This radio will restart and disappear for several seconds. '
            'If it is currently receiving, its fixture goes dark.'
        ),
    ),
    'link': CommandSpec(
        name='link',
        uuid=c.LINK_ACTION,
        payload=bytes([0x05]),
        required_mode=('tx',),
        verification='ack-only',
        warning=(
            'This puts the transmitter into pairing mode. Any unlinked '
            'receiver in range will pair to it — not only the one you mean.'
        ),
    ),
    'unlink': CommandSpec(
        name='unlink',
        uuid=c.LINK_ACTION,
        payload=bytes([0x00]),
        required_mode=('rx',),
        verification='ack-only',
        warning=(
            'This receiver will lose its transmitter. Anything it is '
            'currently feeding goes dark until it is paired again.'
        ),
    ),
}

# DERIVED, never hand-written: a new command cannot widen the allowlist
# without also appearing in COMMANDS above.
WRITABLE_UUIDS = frozenset(spec.uuid for spec in COMMANDS.values())
