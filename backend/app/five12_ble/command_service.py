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

import contextlib
import logging
import secrets
import threading
import time
from dataclasses import dataclass

from . import constants as c
from . import decoders as d
from .errors import (
    ConfirmationInvalid,
    DeviceNotFound,
    IdentityMismatch,
    StaleSnapshot,
    UnknownCommand,
    UnknownMode,
    WrongMode,
)

log = logging.getLogger(__name__)


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


# ── Execution ────────────────────────────────────────────────────────────────


@contextlib.asynccontextmanager
async def _connect_for_write(os_id):
    """Indirection so tests can substitute a fake client without importing
    bleak. Imported lazily for the same reason the read path does."""
    from .connection_manager import connect_for_write

    async with connect_for_write(os_id) as client:
        yield client


async def _read_mode(client):
    """Current mode as 'rx' | 'tx' | None. None means the radio reported a
    value this firmware contract does not define — never a reason to guess."""
    raw = await client.read_gatt_char(c.MODE)
    return d.decode_mode(raw)['decoded']


def _spec_or_reject(command_name):
    spec = COMMANDS.get(command_name)
    if spec is None:
        raise UnknownCommand(detail=command_name)
    return spec


def _device_or_reject(registry, os_id):
    device = registry.get(os_id)
    if device is None:
        raise DeviceNotFound(detail=os_id)
    return device


def _hardware_id(device):
    """The hardware id lives in the decoded advertisement, not as an attribute
    of DiscoveredDevice — see its to_dict(). It is the closest thing to stable
    identity we have: os_id is a Bluetooth address and can rotate.
    """
    return device.advert.get('hardwareId')


async def prepare_command(os_id, command_name, registry):
    """Step one of two. Reads the radio's actual mode and mints a confirmation
    bound to it, so the operator confirms against server-side fact rather than
    whatever their browser last happened to render."""
    spec = _spec_or_reject(command_name)
    device = _device_or_reject(registry, os_id)

    async with _connect_for_write(os_id) as client:
        mode = await _read_mode(client)

    if mode is None:
        raise UnknownMode(detail=os_id)

    token = tokens.issue(os_id, _hardware_id(device), command_name, mode)
    return {
        'command': command_name,
        'token': token.value,
        'ttlS': TOKEN_TTL_S,
        'deviceAlias': device.local_name,
        'currentMode': mode,
        'warning': spec.warning,
    }


async def execute_command(os_id, command_name, expected_mode, token_value, registry):
    """Step two. Every check runs here regardless of what the UI did — a
    disabled button is a courtesy, not a security boundary."""
    started = time.monotonic()

    spec = _spec_or_reject(command_name)
    device = _device_or_reject(registry, os_id)
    token = tokens.consume(token_value or '', os_id, command_name)

    if _hardware_id(device) != token.hardware_id:
        raise IdentityMismatch(detail=os_id)

    async with _connect_for_write(os_id) as client:
        mode = await _read_mode(client)
        if mode is None:
            raise UnknownMode(detail=os_id)
        # Freshness: the radio's mode NOW must match both what the client
        # believed and what it was when the operator was warned.
        if mode != expected_mode or mode != token.mode:
            raise StaleSnapshot(detail=f'{token.mode} -> {mode}')
        if mode not in spec.required_mode:
            raise WrongMode(detail=f'{command_name} requires {spec.required_mode}')

        await client.write_gatt_char(spec.uuid, spec.payload)

        # Only ack-only commands (link, unlink) are complete at this point.
        # Mode writes reboot the module and cannot be verified on the
        # connection that made them; the next task adds that state machine,
        # so until then every command reports the acknowledgement alone.
        result_mode = mode
        verification = 'ack-only'

    result = {
        'command': command_name,
        'attAcknowledged': True,
        'verification': verification,
        'mode': {'decoded': result_mode, 'source': 'post-write-readback'},
        'durationMs': int((time.monotonic() - started) * 1000),
    }
    _audit(command_name, device, token.mode, spec, result)
    return result


def _audit(command_name, device, mode, spec, result, error=None):
    """Symbolic names only. Never linking keys, never the opaque blob, never
    the raw OS identifier."""
    log.info(
        'BLE WRITE cmd=%s device=%s mode=%s uuid=%s payload=0x%02X '
        'ack=%s verification=%s durationMs=%s error=%s',
        command_name,
        device.local_name,
        mode,
        _symbolic_uuid(spec.uuid),
        spec.payload[0],
        result.get('attAcknowledged') if result else False,
        result.get('verification') if result else None,
        result.get('durationMs') if result else None,
        error,
    )


def _symbolic_uuid(uuid):
    return {c.MODE: 'MODE', c.LINK_ACTION: 'LINK_ACTION'}.get(uuid, 'UNKNOWN')
