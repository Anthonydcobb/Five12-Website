# Active work — stop claiming Bolero antenna attribution we do not have

- **Owner:** Claude
- **Branch:** `fix/claude/bolero-antenna-honesty`
- **Workspace:** local Windows worktree, `C:\dev\five12-wt\bolero`
- **Base SHA:** `4710f51` (`origin/main`)
- **Status:** in progress
- **Last updated:** 2026-07-30

## Goal

Anthony reported that the Devices page shows all eight beltpacks on **MBS LM 2**
while the Bolero's own GUI shows five on **MBS LM 1** and three on **MBS LM 2**.
Stop the panel asserting a per-pack antenna it cannot know.

## Root cause — established against the live rig, read-only

Not a join bug. The REST surface the adapter uses does not carry per-pack
antenna attribution at all.

`/rest/nodeStatus` hangs every connected pack off the node that is the **DECT
master**. Asked of all three antennas in turn, every one of them gives the same
answer:

```text
--- asked 192.168.1.11 ---
    node 132651929 (MBS LM 2)  ip=192.168.1.11  LOCAL   bp=9  [2,4,6,30,32,33,34,35,37]
    node 163060633 (MBS LM 1)  ip=192.168.1.12  remote  bp=0  []
    node 198187945 (MBS LM 3)  ip=192.168.1.13  remote  bp=0  []

--- asked 192.168.1.12 ---
    node 163060633 (MBS LM 1)  ip=192.168.1.12  LOCAL   bp=0  []
    node 132651929 (MBS LM 2)  ip=192.168.1.11  remote  bp=9  [...]

--- asked 192.168.1.13 ---
    node 198187945 (MBS LM 3)  ip=192.168.1.13  LOCAL   bp=0  []
    node 132651929 (MBS LM 2)  ip=192.168.1.11  remote  bp=9  [...]
```

MBS LM 1 asked about **itself** reports zero packs. So this is not a
local-versus-remote artifact, which was my first hypothesis and was wrong.

```text
MBS LM 2   isDectMaster=True    bp=9
MBS LM 1   isDectMaster=False   bp=0
MBS LM 3   isDectMaster=False   bp=0
```

That matches the green **M** badge beside MBS LM 2 in the Bolero GUI.

Nothing else in the payload carries attribution either:

- a `bp[]` entry has `['battery','bpType','detailedStatusFlags','id',
  'packageVersion','riedelSerial','signalLevel','timeslots','usedMicrophone']` —
  no node or antenna reference. `timeslots` is RF slot statistics
  (`free/usable/interfered/warning`), not a radio link.
- `/rest/bp` is the registration roster — 12 registered packs, names, last
  connect time. No antenna field.
- `/rest/antennaStatus`, `/rest/dectStatus`, `/rest/bpStatus`, `/rest/system`,
  `/rest/nodeInfo`, `/rest/beltpacks` all return 400.

So `antenna` was derived from "the node whose `bp[]` contains this pack", which
is always the DECT master. It was never going to read anything but MBS LM 2, and
the per-antenna `packCount` (8/0/0) is wrong for the same reason.

The adapter's docstring asserted the premise that turned out false: *"A pack is
'attached' to exactly the antenna whose bp[] lists it, which is how the operator
sees it in the GUI."* The GUI says five on LM 1; the REST API says zero.

## Decision

Report what the API supports and nothing more. A confidently wrong antenna on a
panel read under show pressure is worse than a blank one.

- per-pack `antenna` becomes `None` — the UI already renders `p.antenna ?? '—'`
- per-antenna `packCount` becomes `None`; `packsOnline` stays, because the
  system-wide total *is* known and correct
- antennas gain `isDectMaster`, so the panel can say the one true thing about
  the topology it can see
- the simulator changes to match. It fabricated `ANT-A`/`ANT-B` attribution,
  which is exactly how a demo ends up looking better than the hardware; if the
  real adapter cannot know this, the sim must not pretend it can

## Reserved paths

- `backend/app/integrations/bolero.py`
- `backend/tests/test_bolero_normalize.py`
- `app/src/pages/Devices.jsx` (Bolero antenna card and beltpack antenna cell only)
- `docs/coordination/active/claude--bolero-antenna-honesty.md`

## Must-not-touch paths

- `scripts/`, `start.ps1`, doctor tests — Hermes owns these until
  `fix/hermes/doctor-ref-failclosed` (`f60c52f`) lands
- `backend/app/fixture_library*.py`, `app/src/pages/Database.*` — Hermes owns
  the W2 `/status` checksum work
- migrations, models, dependency manifests, `.env`

## Not in scope

Recovering real attribution. The Bolero GUI has it, so it exists on an endpoint
I have not found; six guesses returned 400. Finding it needs a HAR capture from
the Bolero web UI, which is a bench task for Anthony. Tracked separately.

## Checks run

To be filled in as the work proceeds.
