"""RELEASE GATE for the write phase. The command table is the entire write
surface; if a UUID or payload byte can reach a radio without appearing here,
the 'no arbitrary write path' guarantee is gone."""

from app.five12_ble import constants as c
from app.five12_ble.command_service import COMMANDS, WRITABLE_UUIDS


def test_exactly_four_commands():
    assert set(COMMANDS) == {'set_mode_rx', 'set_mode_tx', 'link', 'unlink'}


def test_writable_uuids_are_derived_not_handwritten():
    """Derived from the table, so a new command cannot widen the allowlist
    without also appearing in COMMANDS."""
    assert WRITABLE_UUIDS == frozenset(spec.uuid for spec in COMMANDS.values())


def test_writable_uuids_are_exactly_mode_and_link_action():
    assert WRITABLE_UUIDS == frozenset({c.MODE, c.LINK_ACTION})


def test_every_writable_uuid_is_a_captured_constant():
    """No UUID may be written that was not confirmed by GATT capture."""
    assert WRITABLE_UUIDS <= c.READABLE_UUIDS


def test_exact_wire_payloads():
    assert COMMANDS['set_mode_rx'].payload == bytes([0x00])
    assert COMMANDS['set_mode_tx'].payload == bytes([0x01])
    assert COMMANDS['link'].payload == bytes([0x05])
    assert COMMANDS['unlink'].payload == bytes([0x00])


def test_mode_gates():
    assert COMMANDS['link'].required_mode == ('tx',)
    assert COMMANDS['unlink'].required_mode == ('rx',)
    # Mode changes are allowed from either direction, but only from a KNOWN
    # mode — an undecodable mode is never a reason to guess.
    assert set(COMMANDS['set_mode_rx'].required_mode) == {'rx', 'tx'}
    assert set(COMMANDS['set_mode_tx'].required_mode) == {'rx', 'tx'}


def test_verification_strategies():
    assert COMMANDS['set_mode_rx'].verification == 'reboot-tolerant'
    assert COMMANDS['set_mode_tx'].verification == 'reboot-tolerant'
    assert COMMANDS['link'].verification == 'ack-only'
    assert COMMANDS['unlink'].verification == 'ack-only'


# NOTE: there is deliberately no test asserting the warning prose does not
# claim a completed outcome. Two attempts at that via substring denylists
# both false-positived on legitimate English ('unlinked receiver', 'until it
# is paired again') — the distinction is semantic, not lexical. The rule it
# was reaching for ("never claim RF association") is enforced where it is
# structurally checkable instead: the command result carries no field named
# `linked`. See test_ble_command_service.py.
def test_every_command_warns_the_operator():
    for name, spec in COMMANDS.items():
        assert spec.warning.strip(), f'{name} has no operator warning'


def test_link_warning_names_the_actual_hazard():
    """Link puts a transmitter into pairing mode; any unlinked receiver in
    range pairs to it. The operator must be told that, not just 'are you
    sure'."""
    assert 'range' in COMMANDS['link'].warning.lower()


def test_command_table_is_immutable():
    from dataclasses import FrozenInstanceError
    import pytest
    with pytest.raises(FrozenInstanceError):
        COMMANDS['link'].payload = bytes([0xFF])
