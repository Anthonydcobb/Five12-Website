"""Typed BLE failures, each with copy an operator can act on.

Raw bleak/WinRT errors are unreadable at a focus call. Every failure the user
can actually cause gets a named class and a sentence that says what to do.
"""


class BleError(Exception):
    code = 'ble-error'
    operator_message = 'Bluetooth operation failed.'

    def __init__(self, detail=None):
        self.detail = detail
        super().__init__(f'{self.code}: {self.operator_message}')

    def to_dict(self):
        out = {'code': self.code, 'message': self.operator_message}
        if self.detail:
            out['detail'] = self.detail
        return out


class AdapterUnavailable(BleError):
    code = 'adapter-unavailable'
    operator_message = (
        'No usable Bluetooth adapter was found. Check that Bluetooth is turned '
        'on in Windows settings, then reload this page.'
    )


class DeviceNotFound(BleError):
    code = 'device-not-found'
    operator_message = (
        'That device is no longer in range. Move closer to the fixture, or wait '
        'for the next scan pass and try again.'
    )


class DeviceBusy(BleError):
    code = 'device-busy'
    operator_message = (
        'Another operation is already using this device. Wait for it to finish '
        'and try again.'
    )


class ToolboxHoldingConnection(BleError):
    code = 'toolbox-holding-connection'
    operator_message = (
        'CRMX Toolbox appears to be connected to this device. Toolbox holds the '
        'Bluetooth connection exclusively — close it completely, then try again.'
    )


class CharacteristicMissing(BleError):
    code = 'characteristic-missing'
    operator_message = (
        'This device did not expose an expected Bluetooth characteristic. It may '
        'be running firmware Five12 has not been verified against.'
    )


class OperationTimeout(BleError):
    code = 'operation-timeout'
    operator_message = (
        'The device stopped responding before the operation finished. This is '
        'common at the edge of range — move closer and try again.'
    )


class NotOwner(BleError):
    code = 'not-owner'
    operator_message = (
        'Another Five12 process owns the Bluetooth adapter. Only one can scan at '
        'a time; close the other window or wait for it to release the adapter.'
    )


class ScanLoopUnavailable(BleError):
    code = 'scan-loop-unavailable'
    operator_message = (
        'The Bluetooth scan service is not currently running, so this device '
        'cannot be reached. Reload this page; if the problem persists, check '
        'that Bluetooth is turned on and that no other Five12 window owns the '
        'adapter.'
    )


class UnexpectedBleFailure(BleError):
    code = 'unexpected-ble-failure'
    operator_message = (
        'Something went wrong talking to this device. Try again, and if it '
        'keeps happening, check the server log.'
    )


# ── Write-phase rejections ───────────────────────────────────────────────────
# Each of these is a refusal to write, not a failure to talk to the radio.


class UnknownCommand(BleError):
    code = 'unknown-command'
    operator_message = (
        'Five12 does not recognise that command. Reload this page; if it keeps '
        'happening the app and the server are running different versions.'
    )


class UnknownMode(BleError):
    code = 'unknown-mode'
    operator_message = (
        'This radio did not report a mode Five12 understands, so it will not be '
        'changed. It may be running firmware Five12 has not been verified '
        'against.'
    )


class WrongMode(BleError):
    code = 'wrong-mode'
    operator_message = (
        'That action is not available in this radio\'s current mode. Link is a '
        'transmitter action; Unlink is a receiver action.'
    )


class StaleSnapshot(BleError):
    code = 'stale-snapshot'
    operator_message = (
        'This radio changed since you opened this dialog, so nothing was '
        'written. Read its status again and retry.'
    )


class ConfirmationInvalid(BleError):
    code = 'confirmation-invalid'
    operator_message = (
        'That confirmation has expired or was already used. Start the action '
        'again — confirmations are single-use and last 60 seconds.'
    )


class IdentityMismatch(BleError):
    code = 'identity-mismatch'
    operator_message = (
        'The radio at this address is not the one you confirmed against, so '
        'nothing was written. Bluetooth addresses can change; pick the radio '
        'from the list again.'
    )
