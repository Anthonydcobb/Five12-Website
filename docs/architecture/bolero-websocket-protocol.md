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

## The cheap way to finish this

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
