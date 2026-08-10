"""Read-only gRPC client for the Starlink dish.

The dish serves an UNAUTHENTICATED gRPC endpoint on 192.168.100.1:9200 whose
Request oneof includes reboot, dish_stow, factory_reset, dish_inhibit_rf and
software_update. Anything that can reach the dish can issue them. On this rig
the dish carries the show's internet, so the client is restricted to an
explicit read allowlist and that restriction is pinned here.

These tests must pass on BOTH interpreters. Plain `python` is 3.14 and has
neither grpcio nor protobuf, so nothing here may import them at module scope.
"""

import importlib.util

import pytest

MODULE = 'app.integrations.starlink_grpc_client'

# Every mutating request name observed in the dish's own Request oneof on
# 2026-08-06. None may appear in the client's source.
MUTATING = (
    'reboot', 'dish_stow', 'factory_reset', 'dish_factory_reset',
    'dish_inhibit_rf', 'dish_inhibit_gps', 'software_update', 'set_sku',
    'wifi_set_config', 'dish_set_config', 'dish_set_emc', 'set_test_mode',
    'dish_clear_obstruction_map', 'set_trusted_keys',
)


def _client():
    import importlib
    return importlib.import_module(MODULE)


def test_the_allowlist_holds_only_reads():
    c = _client()
    assert c.ALLOWED_REQUESTS == frozenset({'get_status', 'get_history'})


def test_no_mutating_request_name_appears_in_the_source():
    """Asserted against the module's own text so that ADDING one fails the
    suite, rather than relying on nobody having called it during a test run.
    A reboot issued at the dish takes the show's internet with it."""
    import inspect
    src = inspect.getsource(_client())
    for name in MUTATING:
        assert name not in src, f'mutating request {name!r} present in client'


def test_a_disallowed_name_is_refused_before_any_channel_opens(monkeypatch):
    """The check must come first. If it happened after connecting, a typo
    would already have reached a device that accepts factory_reset."""
    c = _client()
    opened = []
    monkeypatch.setattr(c, '_channel', lambda host, port: opened.append((host, port)))

    with pytest.raises(ValueError) as exc:
        c.call('reboot')

    assert 'not allowed' in str(exc.value).lower()
    assert opened == [], 'a channel was opened for a disallowed request'


def test_a_disallowed_name_is_refused_even_when_it_looks_like_a_read(monkeypatch):
    c = _client()
    monkeypatch.setattr(c, '_channel', lambda host, port: pytest.fail('channel opened'))
    with pytest.raises(ValueError):
        c.call('get_device_info')      # a real RPC, deliberately not allowlisted


def test_varint_round_trips_without_protobuf_internals():
    """The reflection request is hand-encoded. Earlier drafts reached into
    google.protobuf.internal.encoder/decoder, which are private and move
    between releases; these two helpers are ours and are six lines each."""
    c = _client()
    for n in (0, 1, 127, 128, 300, 5307, 1 << 21):
        buf = c._varint(n)
        value, offset = c._read_varint(buf, 0)
        assert value == n and offset == len(buf)


def test_the_reflection_request_uses_field_four_for_a_symbol():
    """ServerReflectionRequest: file_by_filename is 3, file_containing_symbol
    is 4, list_services is 7. Getting this wrong makes the dish answer
    `INTERNAL: failed to unmarshal the received message`, which reads like a
    transport fault rather than a malformed request — it cost a round trip."""
    c = _client()
    req = c._symbol_request('SpaceX.API.Device.Device')
    assert req[0] == (4 << 3) | 2          # tag: field 4, length-delimited
    assert req.endswith(b'SpaceX.API.Device.Device')
