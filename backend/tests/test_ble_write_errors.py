"""Every write rejection an operator can cause gets a named class and a
sentence saying what to do about it. A raw 400 with no copy is a defect."""

import pytest

from app.five12_ble import errors as e


@pytest.mark.parametrize('cls, code', [
    (e.UnknownCommand, 'unknown-command'),
    (e.UnknownMode, 'unknown-mode'),
    (e.WrongMode, 'wrong-mode'),
    (e.StaleSnapshot, 'stale-snapshot'),
    (e.ConfirmationInvalid, 'confirmation-invalid'),
    (e.IdentityMismatch, 'identity-mismatch'),
])
def test_write_errors_have_codes_and_operator_copy(cls, code):
    err = cls(detail='x')
    assert err.code == code
    assert len(err.operator_message) > 20
    body = err.to_dict()
    assert body['code'] == code
    assert body['message'] == err.operator_message


def test_all_write_errors_are_ble_errors():
    """The routes catch BleError as one family; an error outside it would
    escape as a 500 with a traceback."""
    for cls in (e.UnknownCommand, e.UnknownMode, e.WrongMode,
                e.StaleSnapshot, e.ConfirmationInvalid, e.IdentityMismatch):
        assert issubclass(cls, e.BleError)


def test_stale_snapshot_copy_tells_the_operator_to_re_read():
    assert 'read' in e.StaleSnapshot().operator_message.lower()
