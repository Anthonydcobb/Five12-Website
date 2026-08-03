# Riedel Bolero — websocket protocol, and where beltpack→antenna attribution lives

**Date:** 2026-07-30
**Investigated against:** the live rig, MBS LM 1/2/3 at 192.168.1.11/.12/.13,
Bolero 3.3.1-16, 10 packs connected, 12 registered.
**Evidence level:** verified on actual gear. Read-only throughout — every probe
was a GET or a listen; nothing was ever sent on the socket and nothing was
written to the comms system.

## Why this document exists

Five12's Devices page showed all packs on MBS LM 2 while the Bolero GUI showed
them spread across LM 1 / LM 2 / LM 3. That was traced to the REST API not
carrying attribution at all (see
`docs/coordination/active/claude--bolero-antenna-honesty.md`), and the panel now
blanks the column rather than asserting the DECT master's name.

This is the follow-up: finding where the GUI gets the number, so the column can
eventually be filled with something true.

## What was established

### 1. The GUI does not use REST for live data

Its whole 3.1 MB bundle (`scripts/app-028c6fe2a3.js`) references exactly two
`/rest` paths, both firmware upload:

```text
/rest/startIODeviceUpdate/
/rest/uploadIODeviceUpdate
```

Everything live arrives on the websocket.

### 2. The socket

```text
ws://<antenna>/wsapp        HTTP Basic auth, same read-only account as REST
```

On connect the server sends `{"connectionToken": <n>}` and then pushes
unprompted. Four message kinds observed in 45 s:

| kind | count | shape |
|---|---|---|
| `nodeStatus` | 17 | full node array, ~7 KB |
| `audioPorts` | 12 | `[{registered, id:{type,id}, nodeId}]` |
| `userEventAdded` | 8 | `{nodeId, nodeName, event:{type,severity,timestamp,note}}` |
| `connectionToken` | 1 | handshake |

### 3. The websocket `nodeStatus` is the SAME as the REST one

Compared key-for-key against `/rest/nodeStatus`:

```text
keys the ws has that REST does not:  []
keys REST has that the ws does not:  []
```

23 keys either way, and the same master-only distribution — MBS LM 2 `bp=9`,
MBS LM 1 `bp=0`, MBS LM 3 `bp=0`. **Switching transport buys nothing on its
own.** This was the obvious hypothesis and it is wrong.

### 4. Attribution lives in `audioPorts`

```json
{"audioPorts": [{"registered": true, "id": {"type": 1, "id": 37},
                 "nodeId": 132651929}]}
```

That is beltpack DECT id 37 attached to node 132651929 (MBS LM 2) — exactly the
mapping REST never exposes. `id.type == 1` appears to distinguish beltpacks from
other audio port types.

Corroborated by `userEventAdded`, which names both ends:

```json
{"nodeId": 163060633, "nodeName": "MBS LM 1",
 "event": {"type": 5, "note": "Suck It Bryant"}}
```

### 5. The GUI computes the count client-side

The antenna table's Beltpacks column sorts on `connectedBpsCount`:

```text
st-sort=connectedBpsCount
```

That field is in neither `nodeStatus` payload, so the GUI maintains it itself
from accumulated `audioPorts` state.

## The unsolved half, and why this stops here

**`audioPorts` is a delta stream, not a snapshot.** Two listens, same rig,
minutes apart:

```text
45 s listen  ->  12 audioPorts messages
30 s listen  ->   0 audioPorts messages, 0 packs attributable
```

A listen-only client therefore starts with an empty map and fills in only as
packs happen to roam. On a cold backend start it would show most packs as
unknown and a few as known — which is a worse lie than the blank column,
because partial data looks like complete data.

The GUI does not have this problem, so it obtains an initial state. Either it
sends a request on the socket, or the server bursts current state on connect
under conditions not reproduced here. Static analysis did not find the send: no
`.send(` call site was recoverable from the minified bundle, most likely because
it goes through an Angular `$websocket`-style wrapper.

**Deliberately not done: sending speculative frames at the socket to find out.**
This is a live comms system. Fuzzing an undocumented protocol on it, to save a
two-minute capture, is not a trade worth making.

## ANSWERED 2026-07-30 by a devtools capture — and it changes the design

Anthony captured the socket with devtools open across a reload. Two findings,
the second much more important than the first.

### 1. There is no request. The GUI sends only pings.

Every outgoing frame, across the whole capture, is:

```json
{"event":"ping","data":"ping"}
```

answered by `{"pong":"pong"}`. No subscribe, no state request, no snapshot call.
The protocol is **pure server-push**. So the earlier open question — "what does
the GUI send after connectionToken" — has the answer *nothing*, and a client
cannot ask for a snapshot because no such request exists.

That means accumulating the `audioPorts` delta stream is not a workaround. It is
the only mechanism there is, and it is what the GUI itself does.

### 2. Antenna assignment is not stable. It changes several times a second.

From the capture, with node ids resolved:

```text
12:46:21.552  audioPorts  bp 30 -> 198187945  MBS LM 3
12:46:21.903  audioPorts  bp 30 -> 163060633  MBS LM 1
12:46:22.002  audioPorts  bp 30 -> 198187945  MBS LM 3

12:46:45.132  audioPorts  bp 35 -> 132651929  MBS LM 2
12:46:45.482  audioPorts  bp 35 -> 163060633  MBS LM 1
12:46:45.633  audioPorts  bp 35 -> 132651929  MBS LM 2
12:46:46.546  audioPorts  bp 35 -> 163060633  MBS LM 1
```

Pack 30 changed antenna three times in 450 ms; pack 35 four times in 1.5 s. This
is DECT handover working normally — beltpacks roam between antennas continuously,
and a pack near a coverage boundary flaps.

**This invalidates the feature as originally requested.** A per-pack "which
antenna" column would be a value that changes faster than anyone can read it,
and any single reading of it is stale before it renders. Two packs looked at a
second apart would disagree with themselves.

~~Note also that the Bolero's own GUI does **not** show a per-pack antenna.~~

**WRONG — corrected 2026-07-30.** The Bolero GUI *does* show a per-pack antenna:
the **Device** column in the Beltpacks view (`/bps_view`), populated for every
connected pack — TSB on MBS LM 2, Suck It Bryant on MBS LM 1, Eric on MBS LM 2,
and so on. The claim above was generalised from the Network Devices view alone,
where the per-antenna count is all that appears. It was load-bearing for the
design argument below and it was not checked.

### Revised recommendation

- do **not** add a per-pack antenna column; the underlying value is not stable
  enough to be meaningful, and showing it would recreate the confidently-wrong
  panel this whole thread began by removing
- if the counts are wanted, mirror the GUI: a long-lived socket listener
  maintaining `{bp id -> nodeId}` from `audioPorts`, surfaced as a per-antenna
  count, with an explicit "converging" state until every connected pack has been
  seen at least once
- that listener is a lifecycle the polling adapter should not own. It belongs
  with the runtime manager in the hardening plan's Phases 3 and 5, alongside the
  sACN listener, with the same start/stop/status contract

### Still unknown

Whether a pack can be registered on more than one antenna at once. `audioPorts`
carries no explicit deregistration in this capture — only `registered: true` —
so the flapping may be a genuine handover sequence, or it may be simultaneous
bearers on several antennas being announced in turn. That distinction decides
whether `{bp -> nodeId}` is even single-valued, and it should be settled before
any counter is built on it.

## The cheap way to finish this (superseded by the section above)

A HAR capture, or just the devtools Network → WS frame list, from the Bolero GUI
at `192.168.1.11`:

1. open devtools, Network tab, filter WS
2. load the GUI and click into the antenna list
3. select the `/wsapp` connection and read the **outgoing** frames

Whatever the GUI sends after `connectionToken` is the missing piece. With that,
the adapter change is small and well-understood:

- open `ws://<host>/wsapp`, authenticate, send the state request
- build `{bp id -> nodeId}` from the `audioPorts` reply
- join to `nodeConfig` for names, exactly as `_normalize` already does
- keep REST polling for battery and node health, which it already serves well

## Constraints that should carry into the implementation

- read-only: the socket is used to *read* state, never to configure the system
- the adapter is currently pure request/response; a long-lived socket is a new
  lifecycle to own, and belongs with the runtime manager in the hardening plan's
  Phases 3 and 5 rather than bolted into a polling adapter
- until attribution can be shown for **every** connected pack, it should not be
  shown for any — partial attribution is the failure this whole thread began with


## Correction and current state — 2026-07-30, later

**The claim that the GUI shows no per-pack antenna was wrong.** The Beltpacks
view has a `Device` column giving each connected pack's antenna, complete, with
only the disconnected pack ("Local Gaffer", grey status dot) left blank.

So per-pack attribution is displayable, the vendor does display it, and the
argument that DECT churn makes it meaningless is weakened — the GUI evidently
finds a way to present it.

### What is still unknown, and it is now the only question

Where the `Device` column gets its value. Two possibilities remain:

1. **It is the same `audioPorts` accumulation**, and the GUI simply had been open
   long enough — the observed session started ~13:21 and the screenshot is
   ~13:24, three minutes, against my listener reaching 5 of 9 in two. If so, a
   cold GUI load would also show blanks, and the limitation is real for everyone.
2. **There is a source not yet found.** Neither `/rest/bp` (6 top-level keys, no
   node) nor the ws `bp` message (not captured in full) obviously carries it.

### The observation that settles it, and it is easier than the count

On a **fresh** load of `/bps_view`, watch the `Device` column itself:

- if some connected packs start blank and fill in over a minute or two →
  possibility 1, the GUI accumulates like everything else, and the honest
  incomplete state is unavoidable
- if every connected pack has a Device from the first paint → possibility 2, and
  the source is still out there

### Message kinds now observed

`nodeStatus`, `audioPorts`, `userEventAdded`, `connectionToken`, `bp`,
`ioDeviceStatus`. The last two appear only when something changes — a 100 s
listen saw `ioDeviceStatus` and no `bp`, while a concurrent GUI session saw `bp`
three times and no `ioDeviceStatus`. That is churn, not a different subscription:
the GUI still sends nothing but pings.
