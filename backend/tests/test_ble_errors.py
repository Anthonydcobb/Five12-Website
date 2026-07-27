"""Every BLE failure an operator can hit needs copy they can act on. A lighting
tech mid-focus does not benefit from "BleakError: WinRT: 0x80070490"."""

import pytest

from app.five12_ble import errors as e


def test_all_errors_carry_code_and_operator_message():
    for cls in (e.AdapterUnavailable, e.DeviceNotFound, e.DeviceBusy,
                e.ToolboxHoldingConnection, e.CharacteristicMissing,
                e.OperationTimeout, e.NotOwner):
        err = cls()
        assert err.code, cls.__name__
        assert err.operator_message, cls.__name__
        assert len(err.operator_message) > 20, cls.__name__


def test_toolbox_conflict_names_toolbox_and_says_what_to_do():
    """This is the most common real-world failure — Toolbox holds the BLE
    connection exclusively. The message must name it and give the fix."""
    msg = e.ToolboxHoldingConnection().operator_message.lower()
    assert 'toolbox' in msg
    assert 'close' in msg


def test_to_dict_shape():
    out = e.DeviceNotFound(detail='os-1').to_dict()
    assert out['code'] == 'device-not-found'
    assert 'message' in out
    assert out['detail'] == 'os-1'


def test_errors_are_raisable():
    with pytest.raises(e.BleError):
        raise e.OperationTimeout()


def test_codes_are_unique():
    codes = [cls().code for cls in (
        e.AdapterUnavailable, e.DeviceNotFound, e.DeviceBusy,
        e.ToolboxHoldingConnection, e.CharacteristicMissing,
        e.OperationTimeout, e.NotOwner)]
    assert len(codes) == len(set(codes))
