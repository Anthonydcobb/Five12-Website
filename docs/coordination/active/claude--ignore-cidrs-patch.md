# Active work — make ignore_cidrs settable, and make the sweep honour it

- **Owner:** Claude
- **Branch:** `fix/claude/ignore-cidrs-patch`
- **Workspace:** local Windows worktree, `C:\dev\five12-wt\ignore-cidrs`
- **Base SHA:** `900f613` (`origin/main`)
- **Status:** complete, pushed for review
- **Last updated:** 2026-07-30

## Why

NordVPN's tunnel adapter sits at `10.100.0.2/22`, inside the configured sACN
`10.0.0.0/8`. `_sweep_targets` therefore adds `10.100.0.0/24` to the active
sweep, because a local NIC is in it. The VPN tunnel gets ARP-swept every cycle
and its addresses can surface as devices.

## Two things were assumed and are not true

Both were stated to Anthony before being checked, and both are corrected here.

**1. `ignore_cidrs` does not stop the sweep.** It filters at *persist* time —
`scanner.py:559-563` runs `_arp_scan` over the full range and then drops results
via `_is_ignored_ip` before saving. So it prevents phantom devices and nothing
else. The probes still go out.

**2. `ignoreCidrs` cannot be set on an existing subnet.** `_PATCHABLE` is
`{'sweepHints': 'sweep_hints'}` — deliberately narrowed, because a general PATCH
could rewrite `cidr` (leaving device attribution stale) or `active` (silently
stopping a scan). `ignoreCidrs` is only readable at create time, and recreating a
subnet nulls `subnet_id` on every attached device, which is the precise harm
PATCH was added to avoid.

So "add it to ignore_cidrs" is not a config change. It needs both halves below.

## Scope

**A. `ignoreCidrs` joins the PATCH allowlist**, with the same validation shape as
`sweepHints`. It belongs there: the reason PATCH was narrowed was to protect
`cidr` and `active`, and `ignore_cidrs` is neither — it is exactly the
operator-tunable filter PATCH exists for.

**B. `_sweep_targets` skips targets that are entirely inside an ignored range.**
If the operator has declared a range not-ours, probing it is pointless: every
result is thrown away already. Same outcome, less work, and no ARP traffic on a
VPN tunnel.

**Entirely inside, not merely overlapping.** A target is dropped only when it is
a subnet of an ignored network. Ignoring `10.9.15.0/25` must not stop the sweep
of `10.9.15.0/24` and blind half a range that is ours.

## Reserved paths

- `backend/app/network_routes.py` (the PATCH allowlist and its validation)
- `backend/app/scanner.py` (`_sweep_targets` and `_arp_scan` signatures only)
- `backend/tests/test_scanner_sweep_hints.py`
- `backend/tests/test_scanner_discovery.py`
- `docs/coordination/active/claude--ignore-cidrs-patch.md`

## Must-not-touch paths

- `scripts/`, `start.ps1`, doctor tests — Hermes'
- `backend/app/fixture_library*.py`, `app/src/pages/Database.*` — Hermes' W2
- migrations, models, dependency manifests, `.env`
- **the live database.** Setting the actual value on Anthony's sACN subnet is a
  separate, explicit step and is not done as part of this change.

## Checks run

| Command | Result | Evidence level |
|---|---|---|
| `pytest -q backend/tests/test_scanner_sweep_hints.py` | **40 passed** (was 31) | software verification (Windows rig) |
| `pytest -q backend/tests` from the repository root | **565 passed**, 7 skipped | software verification (Windows rig) |

Nine tests written first and watched failing: five on the sweep side, four on
the API.

One existing test was updated deliberately rather than deleted.
`test_patch_refuses_fields_it_does_not_support` asserted
`supported == ['sweepHints']`; the allowlist grew by one field, so it now
asserts `['ignoreCidrs', 'sweepHints']`. Its point is unchanged and still
enforced — `cidr` and `active` stay refused, because rewriting `cidr` leaves
device attribution stale and flipping `active` silently stops a scan. The reason
is recorded in place so a later reader does not mistake it for a loosened test.

**Not verified:** no live scan was run, and nothing was written to Anthony's
database. The behaviour is covered by tests only; the effect on the real sACN
subnet is the separate step below.

## The step this deliberately does NOT take

Setting `ignoreCidrs = '10.100.0.0/22'` on Anthony's live sACN subnet. That is a
write to production configuration and wants to be an explicit, separate act with
its own before/after — not a side effect of merging a code change.

Once this is on `main` and the backend is running it:

```powershell
# find the sACN subnet id
Invoke-RestMethod http://127.0.0.1:5000/api/network/subnets |
    Select-Object id, label, cidr, ignoreCidrs | Format-Table

# set it
Invoke-RestMethod -Method Patch `
    -Uri http://127.0.0.1:5000/api/network/subnets/<id> `
    -ContentType 'application/json' `
    -Body (@{ ignoreCidrs = '10.100.0.0/22' } | ConvertTo-Json)
```

A bad value is a 400 naming each bad entry rather than a stored setting the
scanner quietly ignores.

**Note the range.** NordVPN's adapter is `10.100.0.2/22`, so the tunnel network
is `10.100.0.0/22` — wider than the `/24` the sweep would target. Ignoring the
`/22` covers the target; ignoring only `10.100.0.0/24` would work today but not
if the tunnel address moved within its own /22.
