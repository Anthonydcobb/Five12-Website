"""Read-only gRPC client for the Starlink dish, via server reflection.

[VERIFIED 2026-08-10 on the rig] The dish at 192.168.100.1:9200 enables gRPC
server reflection. One `file_containing_symbol` lookup for
`SpaceX.API.Device.Device` returns the full transitive descriptor set — 19
files — so the schema is built at runtime and no generated stubs are shipped
or go stale against dish firmware.

This exists instead of `starlink-grpc-tools`, which the adapter used to import
and tell operators to `pip install`. That package is not on PyPI (pip: "from
versions: none"); it is a GitHub repository of scripts.

SAFETY. The endpoint is UNAUTHENTICATED and its Request oneof carries
destructive commands alongside the reads. Only names in ALLOWED_REQUESTS are
ever sent, and the check happens before a channel is opened. On this rig the
dish is the show's internet.
"""

import logging
import threading

DISH_HOST = '192.168.100.1'
DISH_PORT = 9200

#: The only requests this application will ever send. Both verified to return
#: real data on 2026-08-10. Widening this set is a safety decision, not a
#: convenience one — see the module docstring.
ALLOWED_REQUESTS = frozenset({'get_status', 'get_history'})

_SERVICE_SYMBOL = 'SpaceX.API.Device.Device'
_REFLECTION_METHOD = '/grpc.reflection.v1alpha.ServerReflection/ServerReflectionInfo'
_HANDLE_METHOD = '/SpaceX.API.Device.Device/Handle'

log = logging.getLogger(__name__)


class MalformedReflectionResponse(Exception):
    """The dish answered reflection with bytes this parser cannot read.

    Raised in preference to returning a partial descriptor set. A truncated
    set fails later as an opaque 'message type not found', which points at the
    schema instead of at the frame that was actually wrong.
    """

# Descriptors are cached per process: the dish's schema does not change between
# polls, and re-fetching 19 files every cycle would load a device that is also
# carrying the show's internet.
_cache_lock = threading.Lock()
_cached = {}          # (host, port) -> (RequestClass, ResponseClass)


def _varint(n):
    """Minimal protobuf varint encoder.

    Ours on purpose. Earlier drafts used google.protobuf.internal.encoder,
    which is private API and has moved between releases; this is six lines and
    cannot break under a protobuf upgrade.
    """
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _read_varint(buf, i):
    """Returns (value, next_offset)."""
    result = shift = 0
    while True:
        if i >= len(buf):
            raise MalformedReflectionResponse(
                f'a varint at offset {i} runs past the end of a '
                f'{len(buf)}-byte payload')
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, i
        shift += 7


def _slice(buf, i, length, start):
    """buf[i:i + length], refusing to pass off a short read as a whole field."""
    if i + length > len(buf):
        raise MalformedReflectionResponse(
            f'the field at offset {start} declares {length} bytes but only '
            f'{len(buf) - i} remain')
    return buf[i:i + length]


def _symbol_request(symbol):
    """ServerReflectionRequest{ file_containing_symbol: symbol }.

    Field numbers: file_by_filename = 3, file_containing_symbol = 4,
    list_services = 7. A wrong number produces `INTERNAL: failed to unmarshal
    the received message` from the dish, which reads like a transport problem.
    """
    body = symbol.encode()
    return bytes(bytearray(_varint((4 << 3) | 2)) + _varint(len(body)) + body)


def _file_descriptors(payload):
    """Pull FileDescriptorProto bytes out of a ServerReflectionResponse.

    field 4 = FileDescriptorResponse, whose field 1 repeats the protos.
    """
    out, i = [], 0
    while i < len(payload):
        start = i
        tag, i = _read_varint(payload, i)
        field, wire = tag >> 3, tag & 7
        if wire == 2:
            length, i = _read_varint(payload, i)
            chunk, i = _slice(payload, i, length, start), i + length
            if field == 4:
                j = 0
                while j < len(chunk):
                    inner_start = j
                    inner, j = _read_varint(chunk, j)
                    inner_wire = inner & 7
                    if inner_wire == 2:
                        ln, j = _read_varint(chunk, j)
                        out.append(_slice(chunk, j, ln, inner_start))
                        j += ln
                    elif inner_wire == 0:
                        _, j = _read_varint(chunk, j)
                    else:
                        raise MalformedReflectionResponse(
                            f'unsupported wire type {inner_wire} for field '
                            f'{inner >> 3} at offset {inner_start} of the '
                            f'descriptor set')
        elif wire == 0:
            _, i = _read_varint(payload, i)
        else:
            raise MalformedReflectionResponse(
                f'unsupported wire type {wire} for field {field} at offset '
                f'{start}')
    return out


def _channel(host, port):
    import grpc
    return grpc.insecure_channel(f'{host}:{port}')


def _message_classes(channel):
    """Fetch the dish's descriptors and return (RequestClass, ResponseClass)."""
    from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

    raw = lambda b: b          # noqa: E731 — reflection frames are opaque here
    reflect = channel.stream_stream(
        _REFLECTION_METHOD, request_serializer=raw, response_deserializer=raw)

    # One request in, one response out: the dish returns the whole transitive
    # descriptor set in a single frame, so the stream is not drained further.
    # If a firmware ever splits it, the pool below fails to find Request and
    # the break is where to look.
    blobs = []
    for response in reflect(iter([_symbol_request(_SERVICE_SYMBOL)]), timeout=15):
        blobs = _file_descriptors(response)
        break

    protos = {}
    for blob in blobs:
        fdp = descriptor_pb2.FileDescriptorProto()
        fdp.ParseFromString(blob)
        protos[fdp.name] = fdp

    # Dependency order matters: DescriptorPool.Add raises on a missing import.
    pool, added = descriptor_pool.DescriptorPool(), set()

    def add(name):
        if name in added or name not in protos:
            return
        for dep in protos[name].dependency:
            add(dep)
        pool.Add(protos[name])
        added.add(name)

    for name in list(protos):
        add(name)

    return (
        message_factory.GetMessageClass(
            pool.FindMessageTypeByName('SpaceX.API.Device.Request')),
        message_factory.GetMessageClass(
            pool.FindMessageTypeByName('SpaceX.API.Device.Response')),
    )


def _classes_for(channel, key):
    """The cached (RequestClass, ResponseClass) for one dish, fetching once.

    The lock is held across the fetch rather than around the dict access
    alone: two callers arriving cold would otherwise both run the 19-file
    reflection exchange against the dish. The second waits here and finds the
    first one's result. A fetch that raises leaves the key absent, so the next
    poll retries instead of inheriting a dead entry.
    """
    with _cache_lock:
        classes = _cached.get(key)
        if classes is None:
            classes = _cached[key] = _message_classes(channel)
        return classes


def call(request_name, host=DISH_HOST, port=DISH_PORT, timeout=10.0):
    """Send one allowlisted read to the dish and return the response as a dict.

    Raises ValueError for a name outside ALLOWED_REQUESTS, before any network
    activity. Any other failure propagates to the caller, which is expected to
    convert it into an unavailable status rather than let it escape.
    """
    if request_name not in ALLOWED_REQUESTS:
        raise ValueError(
            f'{request_name!r} is not allowed; this client sends only '
            f'{sorted(ALLOWED_REQUESTS)}')

    from google.protobuf import json_format

    # The channel serves both the descriptor fetch and the call, so it is
    # opened once and closed on every path out, including the failing ones.
    # One leaked per poll accumulates against the device carrying the show's
    # internet.
    channel = _channel(host, port)
    try:
        request_cls, response_cls = _classes_for(channel, (host, port))

        handle = channel.unary_unary(
            _HANDLE_METHOD,
            request_serializer=lambda m: m.SerializeToString(),
            response_deserializer=response_cls.FromString)

        message = request_cls()
        getattr(message, request_name).SetInParent()
        return json_format.MessageToDict(
            handle(message, timeout=timeout), preserving_proto_field_name=True)
    finally:
        channel.close()
