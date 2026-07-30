# Active work — review of the runtime/desktop hardening plan

- **Owner:** Claude
- **Branch:** `docs/claude/runtime-hardening-plan-review`
- **Workspace:** local Windows worktree, `C:\dev\five12-wt\runtime-hardening-plan-review`
- **Base SHA:** `aa4b25b9d2411ec9565ebcb918b3e302f9883701`
- **Status:** review complete, pushed for Hermes
- **Last updated:** 2026-07-30

## Goal

Perform the read-only plan review requested in section 8.8 of
`docs/superpowers/plans/2026-07-30-five12-runtime-desktop-hardening.md`
(`docs/hermes/runtime-hardening-plan` @ `42c2038`), before any application code
is written against that plan.

## Acceptance criteria

- [x] Plan read in full and reviewed against `origin/main` at `aa4b25b`.
- [x] All active coordination records read, on `main` and on every unmerged branch.
- [x] Findings use Critical / Warning / Suggestion / Looks Good with exact citations.
- [x] Reviewed commit pinned by full SHA, not by branch name.
- [x] Dependency/merge order, reservation collisions, and stale branch assumptions checked.
- [x] Proposed owner/reviewer split included.
- [x] Evidence levels separated; nothing labelled as hardware verification.
- [ ] Hermes reconciles the findings into the plan.

## Reserved paths

- `docs/coordination/reviews/2026-07-30--claude-review-of-runtime-hardening-plan.md`
- `docs/coordination/active/claude--runtime-hardening-plan-review.md`

## Must-not-touch paths

Everything else. This branch changes no application code, no migrations, no
dependency manifests, and no `.env` or credential material.

## Checks run

| Command | Result | Evidence level |
|---|---|---|
| `python -m pytest -q backend\tests` from repo root, app interpreter, on `feat/claude/preflight-doctor` @ `a86b7cd` | 5 failed, 408 passed, 10.40 s | software verification (Windows rig) |
| `git show` / `git diff` / `git ls-tree` across `origin/main` and 7 unmerged branches | see review | repository inspection |

The 5 failures are `test_ble_scanner.py` adapter-lock tests, failing because the
Five12 backend was running (PID 2868, port 5000) and holds the machine-wide
Bluetooth lock. Recorded deliberately — it is finding W2.

## Outcome

Verdict: **request changes**. Four Critical findings make Phase 0 and Phase 1
unexecutable as written; the architecture and sequencing discipline are sound.
Full detail and a replacement integration order are in the review file.

## Handoff / next action

Hermes: fetch `docs/claude/runtime-hardening-plan-review`, verify the findings
independently, and reconcile them into the plan. The two that need a decision
rather than an edit are C2 (the `run_desktop.py` bridge) and W6 (behind-upstream
severity in the doctor).
