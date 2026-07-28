"""A confirmation the server did not issue is not a confirmation. Tokens are
server-minted, single-use, short-lived, and bound to one device and one
command, so a stale browser tab cannot replay one."""

import pytest

from app.five12_ble import errors as e
from app.five12_ble.command_service import TOKEN_TTL_S, TokenStore


def _store():
    return TokenStore()


def test_issue_returns_an_unguessable_value():
    t = _store().issue('dev-1', 'F1400000', 'link', 'tx', now=100.0)
    assert len(t.value) >= 32


def test_two_tokens_are_never_equal():
    s = _store()
    a = s.issue('dev-1', 'F1400000', 'link', 'tx', now=100.0)
    b = s.issue('dev-1', 'F1400000', 'link', 'tx', now=100.0)
    assert a.value != b.value


def test_consume_returns_the_binding():
    s = _store()
    t = s.issue('dev-1', 'F1400000', 'link', 'tx', now=100.0)
    got = s.consume(t.value, 'dev-1', 'link', now=101.0)
    assert got.hardware_id == 'F1400000'
    assert got.mode == 'tx'


def test_a_token_is_single_use():
    s = _store()
    t = s.issue('dev-1', 'F1400000', 'link', 'tx', now=100.0)
    s.consume(t.value, 'dev-1', 'link', now=101.0)
    with pytest.raises(e.ConfirmationInvalid):
        s.consume(t.value, 'dev-1', 'link', now=102.0)


def test_a_token_expires():
    s = _store()
    t = s.issue('dev-1', 'F1400000', 'link', 'tx', now=100.0)
    with pytest.raises(e.ConfirmationInvalid):
        s.consume(t.value, 'dev-1', 'link', now=100.0 + TOKEN_TTL_S + 0.1)


def test_a_token_is_bound_to_its_device():
    s = _store()
    t = s.issue('dev-1', 'F1400000', 'link', 'tx', now=100.0)
    with pytest.raises(e.ConfirmationInvalid):
        s.consume(t.value, 'dev-2', 'link', now=101.0)


def test_a_token_is_bound_to_its_command():
    """A confirmation for 'unlink' must never execute 'set_mode_tx'."""
    s = _store()
    t = s.issue('dev-1', 'F1400000', 'unlink', 'rx', now=100.0)
    with pytest.raises(e.ConfirmationInvalid):
        s.consume(t.value, 'dev-1', 'set_mode_tx', now=101.0)


def test_an_unknown_token_is_rejected():
    with pytest.raises(e.ConfirmationInvalid):
        _store().consume('not-a-real-token', 'dev-1', 'link', now=100.0)


def test_a_failed_consume_does_not_burn_the_token():
    """Fumbling the device id must not invalidate a confirmation the operator
    is about to use correctly."""
    s = _store()
    t = s.issue('dev-1', 'F1400000', 'link', 'tx', now=100.0)
    with pytest.raises(e.ConfirmationInvalid):
        s.consume(t.value, 'wrong-device', 'link', now=101.0)
    assert s.consume(t.value, 'dev-1', 'link', now=102.0).mode == 'tx'


def test_expired_tokens_are_swept_on_issue():
    """The store must not grow without bound over a long show."""
    s = TokenStore()
    s.issue('dev-1', 'F1400000', 'link', 'tx', now=100.0)
    s.issue('dev-2', 'F1400000', 'link', 'tx', now=100.0 + TOKEN_TTL_S + 1)
    assert len(s._tokens) == 1
