"""Read-only gRPC client for the Starlink dish.

The dish serves an UNAUTHENTICATED gRPC endpoint on 192.168.100.1:9200 whose
Request oneof includes reboot, dish_stow, factory_reset, dish_inhibit_rf and
software_update. Anything that can reach the dish can issue them. On this rig
the dish carries the show's internet, so the client is restricted to an
explicit read allowlist and that restriction is pinned here.

These tests must pass on BOTH interpreters. Plain `python` is 3.14 and has
neither grpcio nor protobuf, so nothing here may import them at module scope.
"""

import sys
import threading
import time
import types

import pytest

MODULE = 'app.integrations.starlink_grpc_client'

# Every mutating request name observed in the dish's own Request oneof on
# 2026-08-10. None may appear in the client's source.
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


# ---------------------------------------------------------------------------
# Fakes.
#
# The client imports grpc and google.protobuf inside functions so the module
# stays importable on the 3.14 interpreter, which has neither. These fakes let
# the parser and call() run end to end on both.
# ---------------------------------------------------------------------------


class _Field:
    """One field of a fake Request message. Records that it was selected."""

    def __init__(self, owner, name):
        self._owner, self._name = owner, name

    def SetInParent(self):
        self._owner.set_fields.append(self._name)


class FakeRequest:
    def __init__(self):
        self.set_fields = []

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return _Field(self, name)

    def SerializeToString(self):
        return b'|'.join(n.encode() for n in self.set_fields)


class FakeResponse:
    """Stands in for the descriptor-built Response class."""

    def __init__(self, payload=None):
        self.payload = payload or {}

    @classmethod
    def FromString(cls, data):
        return cls()


class FakeChannel:
    def __init__(self, response=None):
        self.response = response if response is not None else FakeResponse()
        self.closes = 0
        self.handle_calls = []
        self.handle_method = None

    def unary_unary(self, method, request_serializer, response_deserializer):
        self.handle_method = method

        def handle(message, timeout=None):
            self.handle_calls.append((message, timeout))
            return self.response

        return handle

    def close(self):
        self.closes += 1


def _install_fake_protobuf(monkeypatch):
    """call() does `from google.protobuf import json_format` at call time.

    Plain python has no protobuf at all, so inject one. monkeypatch.setitem
    puts the real modules back when the test ends.
    """
    json_format = types.ModuleType('google.protobuf.json_format')
    json_format.MessageToDict = (
        lambda msg, preserving_proto_field_name=False: dict(msg.payload))
    protobuf = types.ModuleType('google.protobuf')
    protobuf.json_format = json_format
    google = types.ModuleType('google')
    google.protobuf = protobuf
    monkeypatch.setitem(sys.modules, 'google', google)
    monkeypatch.setitem(sys.modules, 'google.protobuf', protobuf)
    monkeypatch.setitem(sys.modules, 'google.protobuf.json_format', json_format)


def _arrange_call(monkeypatch, payload=None):
    """A client whose channel, descriptor fetch and protobuf are all fakes."""
    c = _client()
    _install_fake_protobuf(monkeypatch)
    monkeypatch.setattr(c, '_cached', {})
    channel = FakeChannel(FakeResponse(payload))
    monkeypatch.setattr(c, '_channel', lambda host, port: channel)
    monkeypatch.setattr(c, '_message_classes', lambda ch: (FakeRequest, FakeResponse))
    return c, channel


def _tag(c, field, wire):
    return c._varint((field << 3) | wire)


def _ld(c, field, body):
    """A length-delimited field: tag, length, body."""
    return _tag(c, field, 2) + c._varint(len(body)) + body


# ---------------------------------------------------------------------------
# The hand-rolled reflection parser.
# ---------------------------------------------------------------------------


def test_file_descriptors_pulls_every_proto_out_of_a_reflection_response():
    """A ServerReflectionResponse carries the descriptor set in field 4, whose
    own field 1 repeats the FileDescriptorProto bytes. Nothing else in the
    frame may be mistaken for one.

    This is the parser's only direct coverage. Without it a stub returning []
    passes every other test in this file.
    """
    c = _client()
    payload = (
        _ld(c, 1, b'grpc.reflection.v1alpha.ServerReflection')   # original_request
        + _tag(c, 3, 0) + c._varint(9001)                        # a varint field
        + _ld(c, 4, _ld(c, 1, b'FIRST-PROTO') + _ld(c, 1, b'SECOND-PROTO'))
    )
    assert c._file_descriptors(payload) == [b'FIRST-PROTO', b'SECOND-PROTO']


def test_file_descriptors_skips_a_varint_inside_the_descriptor_set():
    c = _client()
    inner = _tag(c, 2, 0) + c._varint(7) + _ld(c, 1, b'PROTO')
    assert c._file_descriptors(_ld(c, 4, inner)) == [b'PROTO']


def test_file_descriptors_ignores_length_delimited_fields_that_are_not_the_set():
    c = _client()
    payload = _ld(c, 5, b'not-a-descriptor') + _ld(c, 4, _ld(c, 1, b'PROTO'))
    assert c._file_descriptors(payload) == [b'PROTO']


def test_an_unsupported_wire_type_is_named_rather_than_silently_truncating():
    """The parser used to `break` on wire types 1/3/4/5, abandoning the rest of
    the payload. The failure then surfaced downstream as an opaque 'message
    type not found', which points at the wrong thing entirely."""
    c = _client()
    payload = _tag(c, 9, 5) + b'\x00\x00\x00\x00' + _ld(c, 4, _ld(c, 1, b'PROTO'))
    with pytest.raises(c.MalformedReflectionResponse) as exc:
        c._file_descriptors(payload)
    assert 'wire type 5' in str(exc.value)
    assert 'offset 0' in str(exc.value)


def test_an_unsupported_wire_type_inside_the_descriptor_set_is_named_too():
    c = _client()
    with pytest.raises(c.MalformedReflectionResponse) as exc:
        c._file_descriptors(_ld(c, 4, _tag(c, 2, 5) + b'\x00\x00\x00\x00'))
    assert 'wire type 5' in str(exc.value)


def test_a_length_running_past_the_end_of_the_buffer_is_reported():
    c = _client()
    with pytest.raises(c.MalformedReflectionResponse):
        c._file_descriptors(_tag(c, 4, 2) + c._varint(64) + b'short')


def test_a_truncated_varint_is_reported_rather_than_raising_indexerror():
    """A bare IndexError from the middle of a parser tells the caller nothing
    about which device sent the malformed frame."""
    c = _client()
    with pytest.raises(c.MalformedReflectionResponse):
        c._read_varint(b'\x80\x80', 0)


# ---------------------------------------------------------------------------
# call(): channel lifetime, descriptor cache, and the happy path.
# ---------------------------------------------------------------------------


def test_call_selects_the_requested_field_and_maps_the_response(monkeypatch):
    """The happy path end to end against a fake channel. Nothing else here
    proves call() assembles a request or returns what the dish answered."""
    c, channel = _arrange_call(monkeypatch, {'device_info': {'id': 'ut01'}})

    result = c.call('get_status', timeout=3.0)

    assert result == {'device_info': {'id': 'ut01'}}
    message, timeout = channel.handle_calls[0]
    assert message.set_fields == ['get_status'], 'wrong request field selected'
    assert timeout == 3.0
    assert channel.handle_method.endswith('/Handle')


def test_the_channel_is_closed_after_a_successful_call(monkeypatch):
    """Every poll used to open a channel and leave it open. The panel polls
    this against the device carrying the show's internet."""
    c, channel = _arrange_call(monkeypatch, {'uptime': 5})
    c.call('get_status')
    assert channel.closes == 1


def test_the_channel_is_closed_when_the_dish_call_raises(monkeypatch):
    c, channel = _arrange_call(monkeypatch)
    monkeypatch.setattr(c, '_message_classes',
                        lambda ch: (_ for _ in ()).throw(RuntimeError('unreachable')))
    with pytest.raises(RuntimeError):
        c.call('get_status')
    assert channel.closes == 1


def test_a_warm_cache_call_still_closes_its_channel(monkeypatch):
    c, channel = _arrange_call(monkeypatch, {'uptime': 5})
    c.call('get_status')
    c.call('get_history')
    assert channel.closes == 2


def test_two_cold_callers_fetch_the_descriptor_set_once(monkeypatch):
    """_cache_lock guarded only the dict get/set, so the 19-file reflection
    fetch ran outside it and two callers at startup both hit the dish."""
    c, _channel_ = _arrange_call(monkeypatch, {'uptime': 1})
    fetches = []
    start = threading.Event()

    def slow_fetch(ch):
        fetches.append(1)
        time.sleep(0.1)
        return (FakeRequest, FakeResponse)

    monkeypatch.setattr(c, '_message_classes', slow_fetch)

    def poll():
        start.wait(5)
        c.call('get_status')

    threads = [threading.Thread(target=poll) for _ in range(2)]
    for t in threads:
        t.start()
    start.set()
    for t in threads:
        t.join(10)

    assert fetches == [1], 'both callers fetched descriptors from the dish'


def test_a_failed_fetch_does_not_poison_the_cache(monkeypatch):
    """Pinning behaviour that is already correct: a dish that is down at
    startup must not leave an entry behind that suppresses the retry."""
    c, _channel_ = _arrange_call(monkeypatch)
    monkeypatch.setattr(c, '_message_classes',
                        lambda ch: (_ for _ in ()).throw(RuntimeError('down')))
    with pytest.raises(RuntimeError):
        c.call('get_status')
    assert c._cached == {}
