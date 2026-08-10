# Active work — make the sweep-hint tests independent of the host's NICs

- **Owner:** Claude
- **Branch:** `fix/claude/scanner-test-env-independence`
- **Workspace:** local Windows worktree, `C:\dev\five12-wt\scanner-test`
- **Base SHA:** `756a37b` (`origin/main`)
- **Status:** complete — merged to `main` at `cce4b9065c75ceca9506676282b65dc8b4596b78`
- **Last updated:** 2026-07-30

## Goal

`test_scanner_sweep_hints.py::test_a_mixed_family_hint_does_not_abort_the_scan`
is red on `main` right now. Make it — and its neighbours — assert the function's
behaviour rather than the adapters of whichever machine runs the suite.

## Why it is red, and why it was green this morning

```text
assert scanner._sweep_targets('10.0.0.0/8', known_ips=[], sweep_hints='fd00::/120') == []
AssertionError: assert ['10.100.0.0/24', '10.220.220.0/24'] == []
```

The IPv6 hint IS correctly rejected. The test then asserts no targets remain at
all, which only holds when the host has no `10.x` interface. `_sweep_targets`
falls back to the /24s holding a local NIC, via `local_ipv4s()`.

Anthony's show NICs were unplugged this morning when this suite last ran green.
They are up now — `10.220.220.220` (sACN) and `10.100.0.2` (NordVPN's tunnel,
which also sits inside the sACN `/8`) — so the fallback correctly returns two
targets and the assertion fails.

Nothing is wrong with the production code. The test was measuring the laptop.

## The part worth recording

The file already knew about this hazard. `test_hints_alone_are_enough_on_a_fresh_database`
pins `local_ipv4s` and says why in its own docstring:

> `local_ipv4s` is stubbed out so this asserts the function's behaviour and not
> the adapters of whichever machine runs the suite.

The guard was written once and not applied to the rest of the file. The sibling
`test_scanner_discovery.py` is disciplined about it — every test there goes
through a shared `_no_local_ifaces` helper. This file grew its own tests without
that convention, and the ones using `in` / `not in` survived only because those
assertions tolerate extra targets.

Third environment-dependent test found today, after the BLE adapter-lock tests
and the plan's baseline task. Same shape each time: a result that silently
depends on machine state nobody stated.

## Approach

Adopt the sibling file's convention rather than inventing a second one. Add the
same `_no_local_ifaces` helper and apply it to every test that asserts on
`_sweep_targets` output, except the one that is specifically *about* local NICs.

The failing assertion itself is left intact — `== []` is the correct expectation
once the environment is pinned, and it is what still catches the original
TypeError-out-of-`_sweep_targets` regression. This fix controls the input; it
does not weaken the check.

## Reserved paths

- `backend/tests/test_scanner_sweep_hints.py`
- `docs/coordination/active/claude--scanner-test-env-independence.md`

## Must-not-touch paths

- `backend/app/scanner.py` — no production change is needed or made
- `scripts/`, `start.ps1`, doctor tests — Hermes owns until `f60c52f` lands
- `backend/app/fixture_library*.py`, `app/src/pages/Database.*` — Hermes' W2 work

## Checks run

| Command | Result | Evidence level |
|---|---|---|
| `pytest -q backend/tests/test_scanner_sweep_hints.py` | **31 passed** | software verification (Windows rig) |
| `pytest -q backend/tests` from the repository root | **543 passed, 7 skipped, 0 failed** | software verification (Windows rig) |
| `git status backend/app/` | empty — no production change | software verification (Windows rig) |

Run with the show NICs **connected** (`10.220.220.220` sACN, `10.100.0.2`
NordVPN, `172.31.0.220` HOG, `192.168.1.220` COMS), which is the exact condition
that made the test red.

### The check that actually matters: does the test still bite?

Pinning the environment makes a test pass. That is not the same as the test
still being worth having, so it was mutation-tested — the IPv4 guard was removed
from `validate_sweep_hints` and the test re-run:

```text
E   TypeError: fd00::/120 and 10.0.0.0/8 are not of the same version
FAILED test_a_mixed_family_hint_does_not_abort_the_scan
```

That is precisely the regression the test was written for, so the assertion
retains its full power. `backend/app/scanner.py` was restored immediately and
verified byte-clean.

The 7 skips are the BLE adapter-lock tests standing down because something on
the machine holds the adapter — the guard added earlier today doing its job.

## Handoff / next action

Merged to `main` at Anthony's direction. Clean fast-forward; `main` had not
moved, so the merged tree is exactly the one the checks ran against. Test-only,
no production change, which makes this the lowest-risk of today's merges — but
it is still the seventh without independent review and is recorded as such.

Worth Hermes' attention less for the diff than for the pattern: this is the
third environment-dependent test found today, after the BLE adapter-lock tests
and Task 0.2's baseline. All three shared a shape — a result that quietly
depended on machine state nobody had stated. The plan's Task 8.2 (runtime
leak/regression tests) is where that habit would do the most damage if it
carries forward, and a convention like `_no_local_ifaces` is cheap insurance.
