# Active work — network route command safety (PR 2)

- **Owner:** Claude
- **Branch:** `claude/pr2-network-route-safety`
- **Workspace:** ephemeral Claude Code cloud clone (nothing durable outside the pushed branch)
- **Base SHA:** `c8be6db` (`main`)
- **Status:** review — ready for Hermes cross-review
- **Last updated:** 2026-07-27

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
- [ ] Independent cross-review by Hermes.

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
4. **Origin check** — a present, foreign `Origin` gets 403. Absent `Origin`
   (Electron main process, curl, test client) passes.

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
| `pytest` on this branch | **185 passed** (159 + 26 new) | software verification |
| `pytest tests/test_network_routes.py` against **unpatched** `routes.py` | **19 failed, 7 passed** | software verification |
| Trial merge with `fix/hermes/credential-config` | clean, zero conflicts | software verification |
| Combined suite, both PRs merged | **190 passed** | software verification |
| Real NIC reconfigure on Windows | **not run** | — |

The 159-passed baseline independently reproduces the figure in the initial Hermes
review, which my first response had marked unverified.

The against-unpatched run is the load-bearing one: tests that pass both before and
after a fix prove nothing. The 19 failures are the discriminating cases; the 7
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

## Commits

- `claude/pr2-network-route-safety` — `fix(network): stop request data reaching PowerShell as code`

## Handoff / next action

**Hermes:** independent cross-review. The two claims most worth attacking are the
env-var passing (does `$env:` referencing hold under every PowerShell invocation
path we use?) and the origin allowlist (is `_LOCAL_ORIGIN_HOSTS` complete for the
Electron and Vite dev origins in practice?).

**Anthony:** the bench check on the Windows rig — apply a static IP and switch back
to DHCP through the UI — is the acceptance step no agent can perform.

Note on naming: this branch predates my reading the `<type>/<agent>/<slug>`
convention and should have been `fix/claude/network-route-safety`. Left as-is
because it is already pushed and fetched; happy to rename if the convention should
hold strictly.
