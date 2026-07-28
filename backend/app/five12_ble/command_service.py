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

import secrets
import threading
import time
from dataclasses import dataclass

from . import constants as c
from .errors import ConfirmationInvalid


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


# ── Confirmation tokens ──────────────────────────────────────────────────────

TOKEN_TTL_S = 60.0


@dataclass(frozen=True)
class ConfirmationToken:
    """Binds one confirmation to one device, one command, and the mode the
    radio was in when the operator was shown the warning."""

    value: str
    os_id: str
    hardware_id: str
    command: str
    mode: str
    issued_at: float


class TokenStore:
    """In-process, single-use, expiring confirmations.

    In-process is correct here rather than a limitation: only one worker owns
    the Bluetooth adapter at a time (see scanner.py's lock file), so a token
    issued by a worker that cannot write would be useless anyway.
    """

    def __init__(self):
        self._tokens = {}
        self._guard = threading.Lock()

    def issue(self, os_id, hardware_id, command, mode, now=None):
        now = time.time() if now is None else now
        token = ConfirmationToken(
            value=secrets.token_urlsafe(32),
            os_id=os_id,
            hardware_id=hardware_id,
            command=command,
            mode=mode,
            issued_at=now,
        )
        with self._guard:
            self._sweep(now)
            self._tokens[token.value] = token
        return token

    def consume(self, value, os_id, command, now=None):
        """Return the token, removing it. Raises ConfirmationInvalid unless it
        exists, is unexpired, and matches this device AND this command.

        A mismatch does NOT remove the token: fumbling a device id must not
        invalidate a confirmation the operator is about to use correctly.
        """
        now = time.time() if now is None else now
        with self._guard:
            token = self._tokens.get(value)
            if token is None:
                raise ConfirmationInvalid(detail='unknown token')
            if now - token.issued_at > TOKEN_TTL_S:
                del self._tokens[value]
                raise ConfirmationInvalid(detail='expired')
            if token.os_id != os_id:
                raise ConfirmationInvalid(detail='device mismatch')
            if token.command != command:
                raise ConfirmationInvalid(detail='command mismatch')
            del self._tokens[value]
            return token

    def _sweep(self, now):
        """Caller holds the guard."""
        stale = [v for v, t in self._tokens.items() if now - t.issued_at > TOKEN_TTL_S]
        for v in stale:
            del self._tokens[v]


tokens = TokenStore()
