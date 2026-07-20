# Design — sACN Listener & Live Universe View

Date: 2026-07-20 · Branch: `edit_export`
Supersedes the "OPEN SCOPE QUESTION" in `docs/stardust-artnet-handoff.md`.

## 1. The scope decision

The handoff doc asked whether an sACN listener could deliver the number the
devices panel was originally specced to show: *which universes the Stardust
consumes*. **It cannot, and that goal is formally abandoned.**

In E1.31, sources announce themselves — via data packets and via universe
discovery on `239.255.250.214`. **Receivers announce nothing.** The Stardust
is a pure receiver (it consumes sACN/Art-Net and re-transmits over CRMX), so
no amount of listening reveals its patch. This is a property of the protocol,
not a gap in the implementation.

**Decided scope:** build the listener as a *network-wide* view — "what is live
on the wire, and who is sourcing it." This is genuinely useful (it is the
question a lighting tech actually asks on site) and it is certain to work: it
was already proven live on 2026-07-20, receiving universe 1 from
`10.0.0.2` / "Processor, Netnumber 2, Output 1".

**Explicitly out of scope** (recorded so it is not re-litigated):

- *Per-device consumed universes via IGMP.* A receiver must join
  `239.255.0.N` to receive universe N, so group membership does answer the
  original question — readable either by sniffing IGMP reports or by querying
  the GigaCore's snooping table over SNMP (infrastructure that already
  exists). Deferred, not dismissed. Revisit only after this ships.
- *Scraping the Stardust web UI.* Answers the question for exactly one vendor
  and reintroduces the fragile/SSRF pattern this codebase deliberately
  removed (see the module docstring in `integrations/stardust.py`).

## 2. Architecture

New module `backend/app/sacn_listener.py`, sitting beside `scanner.py` — not
in `integrations/`. This is a network-wide service, not a per-device adapter,
and it does not fit behind `DeviceAdapter`.

Three concerns inside that one file, mirroring how `stardust.py` keeps pure
parsers at module level:

| Unit | Responsibility | Depends on |
|------|---------------|------------|
| `parse_data_packet(bytes)` / `parse_discovery_packet(bytes)` | Pure byte→dict decoding. No sockets, no state. | nothing |
| `UniverseRegistry` | Lock-guarded live state; TTL expiry; snapshot for the API. | parsers' output shape |
| `SacnListener` | Owns the socket, join reconciliation, receive-loop thread. | both above |

The split exists so the parsers can be unit-tested against captured bytes with
no network, and so the registry's expiry rules can be reasoned about without
socket code in the way.

### Shared helper extraction

`_local_ipv4s()` currently lives inside `integrations/stardust.py`, but it
encodes host-topology knowledge (the multi-homed `10.0.0.0/8` problem) that
both discovery paths need. Move it to `backend/app/local_ifaces.py` as
`local_ipv4s(pin_env=...)`. `stardust.py` imports it and keeps honouring
`FIVE12_ARTNET_SRC`; the listener passes `FIVE12_SACN_SRC`. Behaviour is
unchanged for Art-Net.

## 3. The socket

This is the part that has already burned two sessions. **One** socket, bound
to INADDR_ANY, with the interface chosen explicitly in each membership
request:

```python
s = socket.socket(AF_INET, SOCK_DGRAM)
s.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
s.bind(('', 5568))                      # NOT (iface_ip, 5568)
for iface in local_ipv4s('FIVE12_SACN_SRC'):
    s.setsockopt(IPPROTO_IP, IP_ADD_MEMBERSHIP,
                 inet_aton(group) + inet_aton(iface))
```

Binding the interface's *unicast* IP — the intuitive thing, and what the
Art-Net unicast path correctly does — silently receives **zero** multicast on
Windows. Verified 2026-07-20. This must be commented at the bind site or it
will be "fixed" back.

Every group is joined on every local interface. A failed join on one
interface is logged at debug and must not abort the others (same tolerance
as `_discover_nodes`).

### Join lifecycle

- At start: join the discovery group `239.255.250.214` only.
- Each ~1s tick: reconcile. Join `239.255.<hi>.<lo>` (hi = `universe >> 8`,
  lo = `universe & 0xFF`) for every universe named in a discovery packet;
  `IP_DROP_MEMBERSHIP` for groups silent longer than `JOIN_DROP_AGE` (60s).
- Hard cap `MAX_JOINED_UNIVERSES = 128`, logged once when exceeded, so a
  misbehaving source cannot exhaust OS join slots.

**Known limitation:** sources predating E1.31-2016 do not send universe
discovery packets and will therefore be invisible. Accepted for v1. If it
bites in the field, the fallback is a configured baseline range (e.g. join
1–16 unconditionally) — a small, additive change.

## 4. Packet parsing

Root layer: preamble `0x0010`, ACN PID `ASC-E1.17`, root vector at 18–21
(`0x04` = data, `0x08` = extended/discovery), CID at 22–37.

**Data packet** (root vector `0x04`, framing vector `0x02`):
source name @44–107 (UTF-8, NUL-terminated), priority @108,
sequence @111, options @112 (bit 6 preview, bit 5 stream-terminated),
universe @113–114 (uint16 BE).

**Discovery packet** (root vector `0x08`, framing vector `0x02`, discovery
layer vector `0x01`): source name @44–107, page @118, last page @119,
universe list from @120 as uint16 BE.

Parsers return `None` on anything malformed, short, or non-E1.31 — never
raise. Same defensive posture as `_parse_poll_reply`.

**[NEEDS VERIFICATION]** These offsets are written from the E1.31 spec, not
yet confirmed against captured bytes from the rig. Confirm during
implementation and change the marker to `[VERIFIED <date>]`, following the
convention already used throughout `stardust.py`.

## 5. Registry and expiry

Per universe, a source map keyed by CID:

```
universe -> {
  announced_at: ts | None,     # last named in a discovery packet
  sources: { cid -> { name, ip, priority, fps, last_seen, seq } }
}
```

Guarded by a single `threading.Lock`. Rules:

- A source is **active** if seen within 2.5s (the E1.31 source-loss timeout).
- The `stream_terminated` option bit drops a source immediately.
- A source is purged from the registry after 15s.
- A universe is purged after 60s with no sources and no discovery mention.
- `fps` from a rolling 1-second packet count per source.

Nothing is written to the database. This is live state; it is meaningless
after a restart, and persisting it would add a migration and write churn for
no benefit.

## 6. API

`GET /api/network/sacn`, added to the existing `network_routes.py` blueprint
(`/api/network` prefix). camelCase keys per the project's API convention.

```json
{
  "listening": true,
  "interfaces": ["10.220.220.220", "10.0.0.1"],
  "universes": [
    { "universe": 1, "active": true, "priority": 100,
      "sources": [
        { "name": "Processor, Netnumber 2, Output 1", "ip": "10.0.0.2",
          "cid": "…", "priority": 100, "fps": 44, "active": true,
          "lastSeen": "2026-07-20T18:04:11Z" }
      ] }
  ]
}
```

Universes sorted ascending. A universe's top-level `priority` is the **highest
priority among its active sources** (the one a compliant receiver would
actually follow); each source also carries its own. A universe is `active` if
any of its sources is.

When the socket could not be opened, the response
is `{"listening": false, "error": "<reason>", "universes": []}` — the UI must
be able to say *why* it sees nothing rather than implying a quiet wire.

## 7. Startup

Started in `create_app` immediately after `start_scanner(app)`, under the same
`ENABLE_NETWORK_TOOLS` guard, so hosted deploys never open the socket.

**Documented caveat:** under gunicorn each worker runs its own listener and
its own registry, so successive polls can hit workers with slightly different
state. Harmless for a live view, and desktop mode — the actual target — is
single-process. Same caveat the scanner already carries.

Port 5568 does not collide with the Art-Net path's 6454.

## 8. Frontend

New component `app/src/components/SacnUniverses.jsx`. It does **not** go into
`NetworkMonitor.jsx`, which is already 622 lines; the page imports and places
it.

- Section header "LIVE sACN UNIVERSES", styled to match the existing panels.
- Table: universe · source name · source IP · priority · fps · live dot.
- Multiple sources on one universe render as stacked rows under that universe,
  since that is exactly the conflict a tech is looking for.
- Polls `/api/network/sacn` on the interval the page already uses.
- Two distinct empty states: *listening, nothing on the wire* vs.
  *listener unavailable: `<error>`*.

**Device card change:** the per-device "UNIVERSES OUTPUTTING" block stays —
it is real and correct for Art-Net transmitters like the Swisson. Only the
Stardust hint text changes, from "needs the sACN listener" to the honest
explanation: a receiver consumes universes rather than announcing them, see
the live universe section.

## 9. Testing

The project has no test suite. The parsers are the one part meaningfully
testable without hardware, and they are also the part most likely to be
silently wrong, so they get the first test file.

- `backend/tests/test_sacn_parse.py` (pytest, run from `backend/.venv`):
  round-trip a captured data packet and a captured discovery packet; assert
  truncated, empty, wrong-PID, and wrong-vector inputs all return `None`.
  Fixtures are real bytes captured from the rig, stored as hex constants.
- Registry expiry tested with an injected clock — no `sleep` in tests.
- Socket, join, and threading behaviour verified by a scratchpad script run
  against the live network, printing the universe table for 30s. This is the
  pattern that proved out the Art-Net work; it is not automatable here.
- `npm run build` must pass for the frontend change.

## 10. Success criteria

1. With the rig live, `GET /api/network/sacn` lists universe 1 with source
   "Processor, Netnumber 2, Output 1" at `10.0.0.2` within ~15s of startup.
2. Universes announced by discovery are joined automatically; killing a
   source marks it inactive within 2.5s and removes it within 15s.
3. The Network Monitor renders the live table and both empty states.
4. Art-Net discovery still finds both nodes after the `local_ipv4s`
   extraction (regression check — 2 nodes, Stardust `via=10.220.220.220`).
5. Parser tests pass.
