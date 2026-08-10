# Active work — real beltpack→antenna attribution from /rest/audioPorts

- **Owner:** Claude
- **Branch:** `feat/claude/bolero-antenna-attribution`
- **Base SHA:** `7084e91` (`origin/main`)
- **Status:** complete — merged to `main` at `0faa937552b02c5818b7b0affe6a91aa190a10cb`
- **Last updated:** 2026-07-30

## What this does

`GET /rest/audioPorts` returns a complete beltpack→nodeId snapshot. Joined to
`nodeConfig` for names, it gives both the per-pack antenna and the per-antenna
count. One request, alongside the two the adapter already makes.

Supersedes `claude--bolero-antenna-honesty.md`, which blanked the column on the
conclusion that this data did not exist. It does exist.

## Verification

| Check | Result | Evidence level |
|---|---|---|
| `pytest -q backend/tests` from the repository root | **550 passed**, 7 skipped | software verification (Windows rig) |
| `npm test` (Vitest) in `app/` | **74 passed**, 7 files | software verification (Windows rig) |
| Real adapter driven against the live rig | see below | **verified on actual gear** |

```text
available=True  source=rest  packsOnline=9

MBS LM 2   packCount=4  ptp=True  master=True
MBS LM 1   packCount=5  ptp=True  master=False
MBS LM 3   packCount=0  ptp=True  master=False

Anthony  MBS LM 1 | TSB  MBS LM 2 | Local Gaffer  MBS LM 1 | Brooklyn  MBS LM 2
Suck It Bryant  MBS LM 2 | Derek  MBS LM 1 | Princess buttons  MBS LM 2
David  MBS LM 1 | Eric  MBS LM 1

counts sum to 9; packsOnline 9 -> MATCH
```

Seven tests written first and watched failing.

## How the endpoint was missed for an entire investigation

Worth recording, because the failure was in method rather than in the protocol.

The endpoint list was inferred by grepping the minified GUI bundle for quoted
`/rest/...` strings. That found two firmware paths and produced the conclusion
"the GUI does not use REST for live data" — which drove everything after it: a
websocket investigation, a listener, an accumulator, a convergence guard, and
two separate "this is not buildable" conclusions.

**The same grep also failed to find the `ws://` URL, which was known to exist.**
There was direct evidence the search method was unreliable, and it was built on
anyway. That is the whole error.

The REST paths mirror the websocket message kinds — `nodeStatus`, `nodeConfig`,
`bp` and `audioPorts` are all both. Six endpoint names were guessed *before*
`audioPorts` was known to exist, and never re-guessed once it was.

A second wrong claim followed from the first: that the Bolero GUI shows no
per-pack antenna. It does, in the Beltpacks view's `Device` column. That was
generalised from the Network Devices view without checking the others, and then
used to justify a design decision.

`docs/architecture/bolero-websocket-protocol.md` keeps the wrong path below a
resolution header. The protocol facts in it are real; the conclusions are void.

## Design choice kept from the wrong path

If the `audioPorts` call fails, the antenna goes blank and battery/PTP still
render. Attribution is an enhancement, not the panel — and a blank is honest
where the DECT master's name is a confident lie. That is the one thing worth
carrying forward.

## Deleted

`bolero_ws.py`, `test_bolero_ws.py`, and `claude--bolero-antenna-counts.md`.
They existed only to work around data that was available all along.

## Handoff

Merged at Anthony's direction, eighth today without independent review — and the
one that most deserves a second pair of eyes, because my reasoning on this
thread was wrong twice in ways that survived several rounds of my own checking.
The live output above is cheap to check against the Bolero GUI directly.
