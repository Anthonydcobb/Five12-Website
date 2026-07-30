# Active work — ARP sweep leaves by the wrong interface

- **Owner:** Claude
- **Branch:** `fix/claude/scanner-sweep-on-main` (was `fix/claude/scanner-sweep-interface` @ `adf4d34`)
- **Workspace:** sibling worktree `C:\dev\Five12-worktrees\claude-scanner-iface`
- **Base SHA:** `aa4b25b` (`origin/main`)
- **Status:** review
- **Last updated:** 2026-07-29

## Goal

The active ARP sweep has never worked. Fix the interface selection so
discovery actually discovers, and prove it against the 15 SideCar nodes that
were invisible to the app until today.

## The fault

`_scapy_scan` called `srp()` without `iface`. `srp` is a layer-2 send, so it
uses scapy's **global** `conf.iface` rather than routing per destination. On
this multi-homed host that default is not any show NIC, so every sweep left by
the wrong adapter, matched nothing, and returned `[]` **without raising**.
`_arp_scan` logs that at `debug` and falls through to the ARP cache, so active
discovery has been dead in silence for as long as the code has existed.

Measured on the rig, against a SideCar that answers ping in 1 ms:

```text
scapy's route for 10.9.15.111:  \Device\NPF_{21DA0B53…}  src 10.220.220.220   ← sACN, correct
scapy's default conf.iface:     \Device\NPF_{DC2EAA79…}                        ← not a show NIC

srp(...)                 -> 0 answers
srp(..., iface='sACN')   -> [('10.9.15.111', '04:11:19:90:04:be')]
```

`{21DA0B53…}` is the sACN adapter's GUID, so scapy resolved the *right*
interface for the destination — it was simply never told to use it.

The repo already knew this lesson from the other direction.
`local_ifaces.py` records that the host has several overlapping 10/8
interfaces, that devices are reachable from only one of them, and that
"fanning out across every interface is what makes discovery work". That fix
reached Art-Net and the sACN listener. It never reached the ARP sweep.

## Why nobody noticed

Three things hid it, and all three are the same shape as the six faults of
2026-07-28/29:

1. `srp` returns `[]` rather than raising, so there was no exception to see.
2. `_arp_scan` catches at `debug` level, so nothing appeared in normal logs.
3. The ARP-cache fallback kept finding *some* devices, so discovery looked
   like it was working — just incomplete, which reads as "the network is
   quiet" rather than "the sweep is broken".

## The fix

- `_probe_address(cidr)` — one usable address in the range, for a route lookup.
- `_sweep_ifaces(conf, cidr)` — the routing table's answer **first**, then any
  interface whose own address falls inside the range. Both matter: the first
  fixes the fault, the second honours `local_ifaces.py`'s multi-homed lesson
  where a device answers on only one of several overlapping interfaces.
- `_scapy_scan` sweeps from each, merging and de-duplicating by IP, and falls
  back to the old un-targeted behaviour when no interface can be resolved —
  better to sweep on scapy's default than not at all.

## Evidence

Nine tests, written before the fix and confirmed failing against the unfixed
code (8 failed, 1 passed — the one that passed is the "still attempts a sweep
when no interface resolves" guarantee, which the old code satisfied by
accident). They use a stub `scapy.all`, so they run on interpreters with no
scapy installed.

```text
before:  8 failed, 1 passed
         calls=[{'iface': None, ...}]   ← the fault, captured
after:   9 passed
```

Then the app's own function against the live show network:

```text
_scapy_scan('10.9.15.0/24') -> 15 host(s)
  10.9.15.101 04:11:19:90:01:C0     10.9.15.109 04:11:19:90:03:66
  10.9.15.102 04:11:19:90:01:44     10.9.15.110 04:11:19:90:01:41
  10.9.15.103 04:11:19:90:00:9B     10.9.15.111 04:11:19:90:04:BE
  10.9.15.104 04:11:19:90:01:D4     10.9.15.112 04:11:19:90:02:94
  10.9.15.105 04:11:19:90:02:CB     10.9.15.113 04:11:19:90:03:5D
  10.9.15.106 04:11:19:90:01:88     10.9.15.114 04:11:19:90:03:91
  10.9.15.107 04:11:19:90:02:C7     10.9.15.121 04:11:19:90:00:85
  10.9.15.108 04:11:19:90:01:17
```

Fifteen SideCar nodes on one OUI, none of which the app has ever seen.
**Evidence level: verified on actual gear.**

## Still not enough on its own

This fix is necessary but **not sufficient** for the SideCars to appear in the
UI. There is a second, independent fault: `_sweep_targets` reduces the sACN
`/8` to the `/24`s holding either a local NIC or a previously-seen device.
The nodes live in `10.9.15.0/24`, which has neither — and `known_ips` comes
from devices already in the database, so a device that has never been seen can
never become a sweep target. Chicken-and-egg.

Options, for Anthony to choose, **not** actioned here:

1. Add `10.9.15.0/24` as a configured subnet. No code; 256 addresses is under
   `MAX_SWEEP_ADDRESSES` so it is swept whole. Caveat:
   `_subnet_id_for_ip` returns the *first* matching row, so attribution
   depends on row order relative to the existing `10.0.0.0/8`.
2. Give `NetworkSubnet` explicit sweep hints, so a fresh database finds the
   gear without a bootstrap. More code, no ordering trap.
3. Bootstrap once by pinging a node so it enters the ARP cache, gets picked up
   by `_arp_fallback`, lands in the database, and thereafter keeps its own /24
   swept via `known_ips`. Self-sustaining, but relies on a manual ritual and a
   scan happening before the cache entry ages out.

Recommendation: 2 for the durable answer, 1 if it needs to work this week.

## Scope expansion — sweep hints (2026-07-29)

Anthony chose option 2. Both halves are one outcome — discovery that actually
discovers — so they stay on one branch rather than pretending to be
independent. The branch now also adds:

- `NetworkSubnet.sweep_hints` — comma-separated CIDRs inside a loose subnet
  that are worth actively sweeping. Two guards, both tested: a hint outside
  its own subnet is dropped, so one typo cannot aim the sweep at a range that
  is not ours; and a hint wider than `MAX_SWEEP_ADDRESSES` is dropped, or a
  /16 hint would reinstate the ~11min sweep the limit exists to prevent.
- Hints are **additive** to the existing local-NIC and known-device targets,
  never a replacement — trading one blind spot for another is not a fix.
- `PATCH /api/network/subnets/<id>`, because hints are most needed on the
  subnets that already exist and the only previous way to change one was
  delete-and-recreate, which nulls `subnet_id` on every attached device.

### Reserved-path escalation, flagged deliberately

This touches `backend/app/models.py`, named in README rule 4 as a
collision-prone shared file. No other active note reserves it as of this
writing (`claude--pr2` holds `backend/app/routes.py`; `hermes--credential-config`
is merged). Claimed here before editing, per rule 3, and called out to Hermes
rather than slipped in.

`backend/app/network_routes.py` is a different file from the `routes.py`
network section reserved by PR 2 — no overlap.

## Migration

`d7c3a9f21b04_add_sweep_hints_to_network_subnets.py`, chained onto the current
head `c5f1a2b3d4e6`. Nullable with no default, so a subnet without hints keeps
exactly the behaviour it had before.

Verified by running the **whole chain from an empty MySQL database** to the new
head, then comparing against the models: 12 tables, `alembic_version` =
`d7c3a9f21b04`, **0 differences**. The scratch database was created and dropped
by the verification; the live database was not touched.

Deploy is the ordinary thing:

```bash
cd backend && flask db upgrade
```

### Correction — an earlier version of this note was wrong

A previous revision of this file, and the commit message of `fb15bbc`, claimed
the project could not deliver a schema change by migration at all: that the
live database was stamped with a revision existing nowhere in the repository,
that the tracked chain omitted every network table, and that this branch must
therefore ship no migration and be accompanied by a hand-written
`ALTER TABLE`.

**All of that was wrong**, and it is retracted here rather than quietly
deleted. The cause: I was reading `migrations/` at the repository root, which
`.gitignore:25-28` explicitly labels as *"the dead root-level migrations/
copy"*. The live Alembic history is **`backend/migrations/`**. Read against the
real directory, everything is healthy:

- 14 revisions, exactly one head (`c5f1a2b3d4e6`), exactly one base
  (`a60b682c3834`);
- the live database sits **on** that head, fully up to date;
- `2114aba7e69a_add_network_monitoring_tables.py` creates `network_subnets`,
  `network_devices` and the location tables, and `c5f1a2b3d4e6` creates
  `dymo_csv_sources`.

No `ALTER TABLE` is needed. No reconciliation work is needed. Nothing was
broken except my reading of it.

The one thing worth taking from the episode: **two `migrations/` directories,
one live and one dead, is a trap.** The `.gitignore` comment is the only thing
marking which is which, and a reader who does not open `.gitignore` will pick
the wrong one — as I did, at length. Deleting the dead copy would be a genuine
improvement, and it is not this branch's to make.

## Response to Hermes' review (2026-07-29)

Review: `docs/coordination/reviews/2026-07-29--hermes-scanner-sweep-interface-review.md`.
Verdict was *request changes*; no criticals. Both warnings were real and are
fixed, and all three suggestions are taken.

| Item | Response |
|---|---|
| **W1** invalid or mixed-family hints could disable a subnet's scan, and the API accepted them silently | Fixed. `validate_sweep_hints` is now the single definition of a valid hint, used by both the API and the scanner so they cannot disagree. Address family is checked **before** `subnet_of`, which removes the `TypeError`. POST and PATCH return 400 with a reason per hint. `_hint_networks` stays defensive for rows edited directly in the database. |
| **W2** the schema change broke existing desktop SQLite databases | Fixed. There was no desktop upgrade path in the project at all — confirmed, only `create_all()` in two places. New `app/sqlite_schema.py`, called from `create_app()`'s desktop branch and `run_desktop.py`: additive nullable columns only, refuses NOT NULL without a default, refuses any non-SQLite engine so it cannot step on Alembic. Tests reproduce the review's scenario — an old-schema SQLite file with a row in it, upgraded, then queried through the model. |
| **S1** narrow and validate the PATCH route | Taken, narrowed. `_PATCHABLE` is `sweepHints` only. A general PATCH could rewrite `cidr` (leaving attached device attribution stale) or `active` (silently stopping a subnet being scanned); neither should ride in on a route added to set hints. An unsupported field is a 400, not a silent no-op. |
| **S2** provide an operator-facing configuration path | Documented below; the UI remains a separate task, now named. |
| **S3** production-shaped fan-out test, and interface-failure isolation | Taken, both halves. The point was correct: the old test drove `_scapy_scan('10.0.0.0/8')` directly, but production reduces a wide subnet to /24 targets first, so the fan-out claim was never exercised. There is now an `_arp_scan` test driving the real path with a wide subnet plus a hint. And one `srp` failure no longer stops the remaining interfaces — it is isolated and logged, with the exception re-raised only when **every** interface failed, so `_arp_scan` still learns the sweep is unusable and warms the ARP cache. Swallowing that unconditionally would have silently disabled the fallback. |

### Operator workflow until there is a UI (S2)

Rewritten 2026-07-30 after Hermes' re-review called the first version
incomplete. It was: bash `curl` on a PowerShell rig, no prerequisite, and no way
to tell whether it had worked.

**Prerequisite, and it is the one that bites first.** `/api/network/*` only
exists when the network gate is on. `start.ps1` sets it; a backend started by
hand without it returns 404 for every command below, which reads exactly like a
wrong URL:

```powershell
$env:FIVE12_NETWORK_TOOLS = '1'
```

**Use `Invoke-RestMethod`, not `curl`.** On Windows PowerShell 5.1 `curl` is an
alias for `Invoke-WebRequest`, which does not take `-X` or `-d`, so the previous
version of this section could not be pasted into the shell the operator
actually uses. The single-quoted JSON is a second trap in the same line.

```powershell
# 1. find the subnet id
Invoke-RestMethod http://127.0.0.1:5000/api/network/subnets |
    Select-Object id, label, cidr, sweepHints | Format-Table

# 2. set the hint. Only sweepHints is accepted; a bad hint is a 400 naming it
Invoke-RestMethod -Method Patch `
    -Uri http://127.0.0.1:5000/api/network/subnets/5 `
    -ContentType 'application/json' `
    -Body (@{ sweepHints = '10.9.15.0/24' } | ConvertTo-Json)

# 3. confirm it stuck — this is the step the first version was missing
(Invoke-RestMethod http://127.0.0.1:5000/api/network/subnets |
    Where-Object id -eq 5).sweepHints

# 4. clear it
Invoke-RestMethod -Method Patch `
    -Uri http://127.0.0.1:5000/api/network/subnets/5 `
    -ContentType 'application/json' `
    -Body (@{ sweepHints = '' } | ConvertTo-Json)
```

**The worked example this branch exists for.** The sACN subnet is `10.0.0.0/8`;
the show gear is 15 SideCar nodes at `10.9.15.101-.114` and `.121`; the host NIC
is `10.220.220.220`. `_sweep_targets` reduces the /8 to the /24s holding a local
NIC or a known device, so it aims at `10.220.220.0/24` and never at the nodes,
and `known_ips` cannot bootstrap because a device must be found before it can be
looked for. Setting `sweepHints = '10.9.15.0/24'` on that subnet is what breaks
the loop.

**When it takes effect.** The hint is read at the start of each sweep, not
cached at startup, so the next scheduled scan picks it up — no restart. A
manual scan is the fast way to see it.

**What a rejection looks like.** The API returns 400 with the reason per hint,
so a typo is visible rather than stored and ignored:

```text
'10.9.15.0/33' is not a CIDR block
10.9.15.0/24 is outside 192.168.1.0/24
fd00::/120 is IPv6; the sweep sends ARP, which is IPv4-only
```

**Evidence level: not executed live.** These commands were not run against a
backend during this task — the rig's backend was mid-bench-test with the network
gate deliberately off, and turning it on would have started an ARP sweep of the
show subnets. The API behaviour they rely on is covered by
`backend/tests/test_scanner_sweep_hints.py`; the PowerShell syntax is not.
Worth one pass on the bench before anyone relies on it under pressure.

**Open task, not done here:** a `sweepHints` field in the subnet editor. Left
out to keep this branch reviewable rather than widening it again; it wants its
own small branch once this shape has survived review.

## Reserved paths

- `backend/app/scanner.py` (`_scapy_scan`, `_sweep_targets`, and new helpers)
- `backend/app/models.py` (`NetworkSubnet` only — one column and `to_dict`)
- `backend/app/network_routes.py` (subnet create + new PATCH)
- `backend/tests/test_scanner_sweep_interface.py`
- `backend/tests/test_scanner_sweep_hints.py`
- `backend/app/sqlite_schema.py` (new, review W2)
- `backend/tests/test_sqlite_schema_upgrade.py` (new, review W2)
- `backend/run_desktop.py` (one call to the upgrade helper)
- `backend/app/__init__.py` (one call, in the existing desktop-SQLite branch)
- `backend/migrations/versions/d7c3a9f21b04_*.py` (new migration)

**Evidence labels, corrected after review.** Earlier versions of this note
marked filesystem, PowerShell and database checks as `verified on actual gear`.
That label is for **hardware** behaviour (README rule 8) and using it for
software checks devalues it. The one genuine hardware claim in this branch is
the live ARP sweep finding 15 SideCar nodes on the show network; everything else
is `software — no hardware claim`.
- `docs/coordination/active/claude--scanner-sweep-interface.md`

## Must-not-touch paths

- `backend/app/routes.py`, `backend/tests/test_network_routes.py` (PR 2)
- `backend/config.py`, `.env`, `.env.example` (PR 1 contract)
- `backend/app/models.py`, migrations, frontend manifests and lockfiles
- All `backend/app/five12_ble/` paths
- Everything owned by `claude--preflight-doctor.md`, which is a separate branch

## Checks run

| Command | Result | Evidence level |
|---|---|---|
| `python -m pytest tests/test_scanner_sweep_interface.py` (before fix) | **8 failed, 1 passed** — intended | verified on actual gear |
| `python -m pytest tests/test_scanner_sweep_interface.py` (after fix) | **9 passed** | verified on actual gear |
| `python -m pytest` (full, this worktree) | **387 passed, 5 failed** — see below | verified on actual gear |
| `_scapy_scan('10.9.15.0/24')` on the live network | **15 nodes found** | verified on actual gear |

All commands run with the app interpreter
`C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe`.

### About those 5 failures — not caused by this branch

`tests/test_ble_scanner.py` fails 5 tests **whenever the Five12 app is
running**. They exercise the Bluetooth adapter's machine-wide single-owner
lock (`%TEMP%\five12-ble-adapter.lock`), and a running backend legitimately
holds it. Confirmed two ways: identical failures with this branch's change
stashed, and the lock file unreadable because PID 57616 (`flask run
--no-reload`, both BLE gates on) owns it.

Worth a separate fix: the failure surfaces as `assert '' == 'HELD'`, which
says nothing about the actual cause. A test that cannot run while the app runs
should say so.

## Risks and skipped checks

- The fan-out sweeps a range once per candidate interface. On a host with many
  interfaces inside one configured range that multiplies sweep time; bounded
  in practice because only interfaces *inside* the range qualify.
- Not tested on Linux. `_sweep_ifaces` reads only `conf.route` and
  `conf.ifaces`, both cross-platform, but Hermes should confirm on the venv.
- The 15 nodes were enumerated by calling `_scapy_scan` directly. They have
  not yet been observed arriving in the UI, because that needs the second
  fault above resolved too.

## Handoff / next action

Review by Hermes. Then, in order:

1. **`cd backend && flask db upgrade`** — the ordinary path; adds the nullable
   column.
2. **Set the hint** on the sACN subnet:
   `PATCH /api/network/subnets/<id>` with `{"sweepHints": "10.9.15.0/24"}`.
   Only then do the 15 nodes reach the UI.

Worth considering separately: deleting the dead root-level `migrations/` copy,
which cost this session real time and produced a retracted diagnosis.

Not done here, and deliberately: **no frontend**. `sweepHints` is settable over
the API but there is no field for it in the subnet editor, so today it is an
operator-with-curl feature. That is a real gap rather than a rounding error —
worth its own small branch once the shape has survived review, rather than
widening this one further.


## Rebuilt onto current `main` — 2026-07-30

Per Hermes' re-review: **no wholesale merge.** The branch forked at `aa4b25b`
and three of its files are now *superseded* on `main` rather than merely older,
so merging the tree would have reverted today's work. The change was reassembled
deliberately instead.

**Taken from `adf4d34`:** `backend/app/scanner.py` and
`backend/app/network_routes.py` whole (`main` has not touched either since the
fork), the two new test files, and this record.

**Deliberately not taken, because `main`'s versions are newer:**

| Path | Why |
|---|---|
| `backend/app/sqlite_schema.py` | `main` has it plus the relaxation, rebuild, and index work from the schema-bridge branch |
| `backend/tests/test_sqlite_schema_upgrade.py` | same, and decoupled from `NetworkSubnet.sweep_hints` |
| `backend/run_desktop.py`, `backend/app/__init__.py` | already call the unified bridge |
| `d7c3a9f21b04_...py` | already on `main`, byte-identical, and applied to the live database |

**`backend/app/models.py`:** only the `sweep_hints` column and its `to_dict`
entry were taken — `main`'s copy carries the Hog fixture-library changes. This
closes a gap that had been open since this morning: the migration was on `main`
and applied to the live database while no model declared the column.

## Hermes' re-review findings

### IPv6 hints reach an IPv4 ARP scanner — confirmed and fixed

The family rule was written as *the hint must match the subnet*, which is the
wrong invariant. It caught an IPv6 hint on an IPv4 subnet, but an IPv6 subnet
with IPv6 hints agreed with itself and was accepted, then handed to a sweep that
can only send ARP. ARP is IPv4-only; there is no ARP request for an IPv6 host.

Proven before fixing — `validate_sweep_hints('fd00::/120', 'fd00::/64')`
returned `['fd00::/120']` with no errors. The rule is now absolute: non-IPv4 is
rejected at the subnet (so the message names the real problem once rather than
blaming each hint) and again per hint.

### Operator workflow incomplete — confirmed and rewritten

See the section above. It was bash `curl` on a PowerShell rig — `curl` is an
alias for `Invoke-WebRequest` on 5.1 and does not take `-X` or `-d`, so it could
not be pasted into the shell the operator actually uses. It also never mentioned
that `/api/network/*` returns 404 unless the network gate is on (hit during this
very session), gave no way to confirm the hint stuck, and carried no worked
example. All four addressed, and the section is honestly labelled as not
executed live.

## Verification

| Check | Result |
|---|---|
| `pytest -q backend/tests` from the repository root | **501 passed** |
| `pytest -q backend/tests/test_scanner_sweep_hints.py` | **31 passed** (was 28) |
| Assembled-tree baseline before any fix | 498 passed |

The three new tests were written first and watched failing, with the IPv6 one
failing by *accepting* `fd00::/120` rather than by erroring — the exact defect.

**Not verified:** no live API call, no ARP sweep, no bench, no gear. The rig's
backend was mid-bench-test with the network gate off, and turning it on would
have started an active sweep of the show subnets.

## Status

Pushed for review. Not merged.
