# Handoff — Claude to Hermes, 2026-07-30

**Channel note.** Honcho was the handoff channel until this afternoon and has
been returning HTTP 520/522; the last three updates never reached it. Anthony
moved handoffs to GitHub. GitHub Issues need an authenticated `gh`/token and
neither is configured on this rig, and the Obsidian vault is not listening on
`127.0.0.1:27123`, so this lands in the repo — which is the channel
`docs/coordination/README.md` designates anyway, and Hermes has confirmed it
reads Five12-Website directly.

`origin/main` went `aa4b25b` → `bbf4abc` today. Suites green: **565 backend,
74 frontend**. Every record referenced here is on `main` under
`docs/coordination/active/`.

---

## Decisions that are yours

**1. Preflight repo-identity severity.** Open since your first review round.
Current: behind-upstream WARN, diverged FAIL, behind-integration WARN. You asked
for stale state to block. I have twice gone narrower than asked and flagged it
both times. One line either way, and I will make it on your word.

**2. W2 — `/api/fixture-library/status` rebuilds and hashes the whole catalog
per call.** Measured at the real 29,936-record scale: ~400 ms and 9.50 MiB per
request, on the `Database.jsx` page-load path. Your lane; noting it is still
open.

**3. W6 — no size guard before the backup row meets `max_allowed_packet`.**
~9.5 MiB against a 16 MiB limit. It fits today, nothing checks it, and exceeding
it surfaces as a raw packet error inside `except Exception` → HTTP 500 with no
hint that the fix is a server variable.

---

## Ten merges, none independently reviewed

All at Anthony's direction, all recorded as such. Ordered by how much a second
opinion would help:

| # | Commit | What | Why it wants review |
|---|---|---|---|
| 1 | `0faa937` | Bolero antenna via `/rest/audioPorts` | **My reasoning was wrong twice; both errors survived several rounds of my own checking.** |
| 2 | `5541546` | one metadata-derived desktop SQLite bridge | Rests on "relaxing `NOT NULL` is always safe". If that is wrong, the design is wrong. |
| 3 | `4378b98` | doctor: `FETCH_HEAD` in worktrees, stale-branch approval | Two of your three findings; the BOM one is `fa0015c`. |
| 4 | `d086120` | scanner IPv6 rule | **Stricter than what you reviewed** — an IPv6 subnet is now rejected outright rather than silently mis-swept. Beyond the minimum your finding required. |
| 5 | `c679243` | SECRET_KEY generated per process | Scope change from what I proposed to you. |
| 6 | `c2920ea` | `ignore_cidrs` honoured by the sweep, and PATCH-able | Widens `_PATCHABLE`, which I had deliberately narrowed. |
| 7 | `2569a48` | single Alembic head | Applied to the live database. |
| 8 | `b8c0caf` | Bolero blank-antenna honesty | Superseded by #1. |
| 9 | `cce4b90` | sweep-hint tests made NIC-independent | Test-only. |
| 10 | `77ae462` | dead root migrations | **The one that followed the protocol** — you approved both content and method. |

---

## Two things I got wrong

**The Bolero investigation.** I grepped the minified GUI bundle for quoted
`/rest/...` strings, found two firmware paths, and concluded "the GUI does not
use REST for live data." That same grep had already failed to find the `ws://`
URL — **which I knew existed, because I had connected to it.** I had direct
evidence the method was unreliable and built on it anyway. It produced a
websocket listener, an accumulator, a convergence model, and two confident
"this is not buildable" conclusions. The answer was `GET /rest/audioPorts`, one
request, available the entire time. The REST paths mirror the websocket message
kinds; I guessed six endpoint names before `audioPorts` was known to exist and
never re-guessed after.

A second wrong claim rode on the first: that the Bolero GUI shows no per-pack
antenna. It does — the `Device` column in the Beltpacks view. Generalised from
one view without checking the others, then used to justify a design decision.

`docs/architecture/bolero-websocket-protocol.md` keeps the wrong path below a
resolution header. The protocol facts in it are real; the conclusions are void.

**SECRET_KEY scope.** I told you I would leave `DesktopConfig.SECRET_KEY` alone,
calling it "a packaging decision." That rested on not knowing what the key was
for. One consumer, no Flask sessions — it is the identical one-line fix.
Included, and flagged rather than widened silently.

---

## The pattern worth more than any single diff

**Three environment-dependent tests found today**: the BLE adapter-lock tests,
Task 0.2's baseline in your plan, and
`test_a_mixed_family_hint_does_not_abort_the_scan`. Two were mine. Same shape
each time — a result quietly depending on machine state nobody stated, so it
reads deterministic while it is not.

**Task 8.2 of your hardening plan is where this would do the most damage.**
Thread counts, socket counts and subprocess counts are all machine state. A
stated-precondition convention belongs in that task rather than being discovered
after it ships.

---

## Machine state, since you were tracking it

Anthony directed the pull and restart before your sequence arrived. I checked
your stated reason first: `f60c52f` is on `main`, so the PowerShell 5.1 gate
looked satisfied.

- checkout on `fix/claude/dymo-print-sequencing` at `cff1a32`, pushed, 17 ahead
  of `main`, clean tree
- `origin/main` merged into that branch; **572 passed** on the combined tree
- backend and frontend restarted; **preflight all green**
- live sACN subnet now carries `ignoreCidrs = 10.100.0.0/22`. NordVPN's tunnel
  sits inside the configured `10.0.0.0/8`, so a local NIC was putting
  `10.100.0.0/24` into the active sweep every cycle for answers that were always
  discarded. Routing itself is fine — longest-prefix match sends show traffic out
  the right interfaces and Nord holds no default route.

---

## The gap I would not want lost

**None of today's work has been exercised against a live show.** The Bolero side
now has genuine hardware evidence and the routing check is real-network
evidence, but the sACN listener, the ARP sweep under load, and the BLE stack
have not been near a running show since any of this landed.

Ten merges went in on my own assessment. Each is individually verified. The
combination is not.
