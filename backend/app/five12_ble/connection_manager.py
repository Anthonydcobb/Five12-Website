"""Single-owner BLE connections with bounded timeouts.

One connection operation per device at a time. Connections are explicit and
short-lived; nothing here connects on its own.

bleak is imported lazily so the pure modules stay importable without it.
"""

import asyncio
import contextlib
import logging
import threading

from .errors import (
    AdapterUnavailable,
    CharacteristicMissing,
    DeviceBusy,
    DeviceNotFound,
    OperationTimeout,
    ToolboxHoldingConnection,
    UnknownCommand,
)

log = logging.getLogger(__name__)

CONNECT_TIMEOUT = 12.0
READ_TIMEOUT = 6.0
DISCONNECT_TIMEOUT = 6.0
WRITE_TIMEOUT = 6.0


class _DeviceLocks:
    """One lock per device, created on demand."""

    def __init__(self):
        self._locks = {}
        self._guard = threading.Lock()

    def for_device(self, os_id):
        with self._guard:
            if os_id not in self._locks:
                self._locks[os_id] = threading.Lock()
            return self._locks[os_id]


_device_locks = _DeviceLocks()


class BleakClientAdapter:
    """Wraps a bleak client in the tiny interface build_snapshot expects.

    Deliberately exposes only read operations. There is no write method on this
    class, and adding one is out of scope for the read-only phase.
    """

    def __init__(self, client):
        self._client = client
        self._uuids = {
            char.uuid.lower()
            for service in client.services
            for char in service.characteristics
        }

    def has_characteristic(self, uuid):
        return uuid.lower() in self._uuids

    async def read_gatt_char(self, uuid):
        return await asyncio.wait_for(
            self._client.read_gatt_char(uuid), timeout=READ_TIMEOUT
        )


class BleakWriteClientAdapter(BleakClientAdapter):
    """The read adapter plus exactly one write method.

    Deliberately a separate class. test_ble_gatt_client.py asserts that
    BleakClientAdapter exposes no write-shaped method of any name, and the
    read path must keep that guarantee — so writes get their own type that
    only the command service ever constructs.
    """

    async def write_gatt_char(self, uuid, payload):
        # Second, independent check on the allowlist. The command service has
        # already mapped a command name to this UUID; this refuses anything
        # that reached here by another route. Imported lazily so the module
        # graph stays acyclic.
        from .command_service import WRITABLE_UUIDS

        if uuid.lower() not in WRITABLE_UUIDS:
            raise UnknownCommand(detail=uuid)
        if not self.has_characteristic(uuid):
            raise CharacteristicMissing(detail=uuid)
        # response=True demands an ATT acknowledgement. Without it we would
        # have no evidence the radio accepted anything.
        await asyncio.wait_for(
            self._client.write_gatt_char(uuid, payload, response=True),
            timeout=WRITE_TIMEOUT,
        )


@contextlib.asynccontextmanager
async def _connect_with(os_id, adapter_cls):
    """Connect to one device, yielding `adapter_cls` wrapped around the client.

    Always disconnects, including on error. Raises a typed BleError the panel
    can render rather than a raw bleak exception.
    """
    try:
        from bleak import BleakClient
        from bleak.exc import BleakError
    except ImportError:
        raise AdapterUnavailable()

    lock = _device_locks.for_device(os_id)
    if not lock.acquire(blocking=False):
        raise DeviceBusy(detail=os_id)

    client = BleakClient(os_id, timeout=CONNECT_TIMEOUT)
    try:
        try:
            await asyncio.wait_for(client.connect(), timeout=CONNECT_TIMEOUT)
        except asyncio.TimeoutError:
            raise OperationTimeout(detail=os_id)
        except BleakError as exc:
            # Windows reports an in-use peripheral as a generic connect
            # failure. CRMX Toolbox holding the connection is by far the most
            # likely cause in the field, so name it rather than guessing.
            text = str(exc).lower()
            if 'in use' in text or 'access' in text or 'busy' in text:
                raise ToolboxHoldingConnection(detail=os_id)
            raise DeviceNotFound(detail=str(exc))

        yield adapter_cls(client)
    finally:
        # The lock must be released no matter how disconnect exits, including
        # via asyncio.CancelledError (a BaseException, not caught by
        # `except Exception` / contextlib.suppress(Exception)). A held lock
        # never expires on its own, so a cancelled disconnect used to poison
        # the device for the rest of the process. The nested finally runs
        # release() before any exception — cancellation included — keeps
        # propagating past this frame.
        try:
            with contextlib.suppress(Exception):
                # A hung disconnect is real, common BLE behaviour; bound it
                # like every other bleak call here so cleanup can't stall
                # forever. Failing to disconnect cleanly must not mask
                # whatever the caller's body was actually doing, so the
                # timeout (and any other disconnect failure) is swallowed.
                await asyncio.wait_for(client.disconnect(), timeout=DISCONNECT_TIMEOUT)
        finally:
            lock.release()


@contextlib.asynccontextmanager
async def connect(os_id):
    """Read-only connection. Cannot write: the adapter has no write method."""
    async with _connect_with(os_id, BleakClientAdapter) as adapter:
        yield adapter


@contextlib.asynccontextmanager
async def connect_for_write(os_id):
    """Write-capable connection. Only the command service should call this."""
    async with _connect_with(os_id, BleakWriteClientAdapter) as adapter:
        yield adapter
