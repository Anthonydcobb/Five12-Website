# Active work — network route command safety (PR 2)

- **Owner:** Claude
- **Branch:** `claude/pr2-network-route-safety`
- **Workspace:** ephemeral Claude Code cloud clone (nothing durable outside the pushed branch)
- **Base SHA:** `c8be6db` (`main`)
- **Head SHA:** `82ba5d4` (final; `0cdc7ec` + a comment-only correction)
- **Status:** review — Hermes cross-review returned; requested test added
- **Last updated:** 2026-07-27 (updated after cross-review)

## Goal

Close the PowerShell command-injection defect on `/api/network/apply` and
`/api/network/dhcp` (finding 3 of the initial Hermes review), per the two-PR split
agreed in `2026-07-27--hermes-reply-to-claude.md`.

## Acceptance criteria

- [x] Request data can no longer reach PowerShell as code.
- [x] Adapter names resolved against the live adapter set.
- [x] IP, gateway, and prefix validated.
- [x] Origin/CSRF decision made rather than relying on loopback + CORS.
- [x] Hostile-input regression tests, proven to fail against the unpatched code.
- [x] Full backend suite green.
- [x] Independent cross-review by Hermes — approved, one test addition requested.
- [x] Requested allowlisted-hostile-alias transport test added (`0cdc7ec`).
- [ ] Windows bench test on a spare adapter (Anthony; no agent can perform this).

## Reserved paths

- `backend/app/routes.py` (network section only, lines ~609-760)
- `backend/tests/test_network_routes.py`

## Must-not-touch paths

Untouched by this branch, confirmed by `git diff --stat` (2 files):
`backend/config.py`, `.env`, `.env.example`, `app/package.json`,
`app/package-lock.json`, migrations, all `five12_ble/` paths.

## Interfaces and contracts

Four layered guards, any one of which closes the injection:

1. **`_run_ps(cmd, params)` passes operator input as environment variables**,
   referenced in-script as `$env:FIVE12_ADAPTER`. Values never enter the script
   text, so no quoting or escaping is required and no value can be parsed as code.
   This is the guard that makes injection impossible rather than merely difficult.
2. **Adapter allowlist** — resolved against live `Get-NetAdapter` output; anything
   else is a 400 before any NIC command runs. Fails closed if enumeration fails.
3. **Address validation** — `ipaddress.IPv4Address` for IP and gateway; prefix
   bounded 1-32.
4. **Origin check** — a present, foreign `Origin` gets 403. The desktop UI calls
   from the Electron *renderer* via Axios, so Chromium sends a loopback origin and
   it matches. The absent-`Origin` exception is for native callers (curl, scripts,
   the test client).

**Behavior change:** a browser reaching the app by LAN address now receives 403 on
these two routes. This matches the loopback-only premise; LAN use needs the
authentication work that remains outstanding.

**No frontend change required.** `app/src/pages/IPConfig.jsx` already sends
`adapter.name` sourced from `/api/network/interfaces`, so the allowlist accepts
every value the UI can produce.

## Decisions and trade-offs

Hermes's reply asked that input validation not be the only barrier. Agreed, and
inverted as well: the env-var passing is not the only barrier either. Validation
without env-passing leaves the escaping question open forever; env-passing without
validation would still let an operator point a NIC command at a nonexistent
adapter. Both are cheap, so both are in.

Rejected: escaping the adapter name before interpolation. It keeps the value in
the script text, which means the guarantee depends on getting PowerShell quoting
rules exactly right — a worse position than never interpolating at all.

## Scope addition — a gap neither review caught

`/api/network/interfaces`, `/apply`, and `/dhcp` live on the **always-registered**
routes blueprint (`app/__init__.py:36`), not the `ENABLE_NETWORK_TOOLS`-gated
`network_routes.py`. The comment at `app/__init__.py:50-52` states the
`/api/network/*` routes "simply don't exist" when the switch is off. That was never
true of these three — so `FIVE12_NETWORK_TOOLS=0`, exactly what an operator would
set when hardening a hosted deploy, left the only PowerShell-executing endpoints in
the codebase reachable.

The three routes now check the switch themselves. Flagging as scope addition rather
than burying it: it is a one-line-per-route change squarely inside "make network
writes safe", but it was not in the agreed PR 2 description.

## Checks run

| Command | Result | Evidence level |
|---|---|---|
| `pytest` on `main` (baseline) | 159 passed, 9 warnings | software verification |
| `pytest` on this branch at `0cdc7ec` | **187 passed** (159 + 28) | software verification |
| `pytest tests/test_network_routes.py` at `0cdc7ec` | **28 passed** | software verification |
| The two new transport tests against **unpatched** `routes.py` | **2 failed** — both discriminate | software verification |
| Whole test file against **unpatched** `routes.py` | **21 failed, 7 passed** (was 19/7 at `a86cff1`) | software verification |
| Trial merge with PR 1 final `aaca308` | clean, zero conflicts | software verification |
| Combined suite, both finals merged | **192 passed** (164 + 28) | software verification |
| Real NIC reconfigure on Windows | **not run** | — |

The 159-passed baseline independently reproduces the figure in the initial Hermes
review, which my first response had marked unverified.

The against-unpatched run is the load-bearing one: tests that pass both before and
after a fix prove nothing. The 21 failures are the discriminating cases; the 7
passes are valid-path regression guards that legitimately pass either way.

## Risks and skipped checks

- **No execution on real hardware.** PowerShell does not exist in this runtime, so
  `subprocess.run` is faked. Every assertion is about what is *sent* to the shell,
  which is where the defect lived — but nobody has confirmed a real NIC still
  reconfigures correctly. **This needs a bench check on the Windows rig before it
  is trusted in a show context.** Simulated only; not bench-tested, not verified on
  actual gear.
- **The cross-origin delivery chain is still unreproduced.** The Origin check is
  cheap and correct regardless, so this does not gate the PR.
- **Out of scope, still open:** `routes.py:1145-1146` accepts device credentials as
  query parameters with `admin`/`admin` defaults. Queued as a later PR per the
  agreed order.

## Cross-review outcome

Hermes reviewed `a86cff1` and approved the implementation, finding no defect that
reopens arbitrary PowerShell execution. It requested one test-only addition, with a
correct diagnosis: every existing injection test rejected the hostile adapter name
at the **allowlist**, so none of them ever exercised the **environment transport**
with a hostile value. They pinned layer 2 while the claim being made was about
layer 1. Loosening the allowlist later would have silently removed the coverage.

`0cdc7ec` adds two tests that put the injection-shaped alias *inside* the mocked
live inventory, so the allowlist passes it through and the transport is the only
barrier left. They assert the value and every executable fragment of it are absent
from the PowerShell source, and that it arrives byte-exact in `FIVE12_ADAPTER`.
Both fail against unpatched `routes.py`, so they discriminate rather than merely
pass.

Two corrections from Hermes accepted into the record:

- The IP-config calls originate in the **Electron renderer via Axios**, not the
  main process. Chromium sends the renderer origin, which the allowlist accepts;
  the absent-Origin exception serves curl and other native callers. My code comment
  said "main process" and is inaccurate on that point.
- `_local_origin()` is a **hostname** allowlist, not an exact-origin allowlist: any
  loopback host, port, or scheme is trusted. This does not reopen the public-web
  CSRF path, since a public page keeps its public hostname in `Origin`. It does
  mean a malicious page already served from another loopback port is treated as
  first-party. Non-blocking under the stated desktop threat model, and stated here
  explicitly so the limit is on the record rather than implied.

## Commits

- `a86cff1` — `fix(network): stop request data reaching PowerShell as code`
- `0cdc7ec` — `test(network): pin env transport with an allowlisted hostile alias`
- `82ba5d4` — `docs(network): correct _local_origin comment after cross-review` (head)

`82ba5d4` is comment-only, no behavior change, suites re-run at 28 focused / 187
complete. It moves both accepted corrections out of this note and into the
docstring, so a future reader making a security decision about `_local_origin()`
sees the hostname-allowlist limit at the code rather than only here. Flagged
because it changes the head after cross-review: Hermes approved `a86cff1`, the
requested test landed in `0cdc7ec`, and only the docstring differs at `82ba5d4`.

## Handoff / next action

**Hermes:** cross-review complete and the requested test is in at `0cdc7ec`.
Re-confirm against the final head if the checkbox should name an exact SHA.

**Anthony:** the Windows bench test is the only remaining gate, and no agent can
perform it. Per Hermes's merge gates, use a **spare or test adapter — never the NIC
carrying an active Hog/show-control network or the machine's only management
path**: capture current adapter state, apply a non-conflicting static IP through
the Five12 UI, verify address/prefix/gateway/connectivity, switch back to DHCP,
then verify lease, gateway, and connectivity are restored.

Evidence label for this branch remains **software verified only** — not
bench-tested, not verified on actual gear.

Note on naming: this branch predates my reading the `<type>/<agent>/<slug>`
convention and should have been `fix/claude/network-route-safety`. Left as-is
because it is already pushed and fetched; happy to rename if the convention should
hold strictly.