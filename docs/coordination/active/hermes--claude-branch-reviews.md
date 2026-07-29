# Active work — Hermes reviews of Claude maintenance branches

- **Owner:** Hermes
- **Branch:** `docs/hermes/claude-branch-reviews`
- **Workspace:** `/root/five12-worktrees/hermes-claude-reviews`
- **Base SHA:** `aa4b25b` (`origin/main`)
- **Status:** complete — review artifacts ready
- **Last updated:** 2026-07-29

## Goal

Independently review the three branches Claude marked for Hermes:

- `origin/fix/claude/scanner-sweep-interface` at `72797cc`
- `origin/feat/claude/preflight-doctor` at `a2dbd85`
- `origin/chore/claude/remove-dead-migrations` at `fbdebf5`

## Reserved paths

- `docs/coordination/active/hermes--claude-branch-reviews.md`
- `docs/coordination/reviews/2026-07-29--hermes-scanner-sweep-interface-review.md`
- `docs/coordination/reviews/2026-07-29--hermes-preflight-doctor-review.md`
- `docs/coordination/reviews/2026-07-29--hermes-dead-migrations-review.md`

## Result

- Scanner/sweep hints: **request changes** — two blocking correctness gaps.
- Preflight doctor: **request changes** — the doctor can still produce false assurance in several of the exact fault classes it is intended to catch.
- Dead root migrations cleanup: **approved** — no blocking findings.

## Verification

- Scanner branch: 27 focused tests passed; full backend suite passed from `backend/` at 410 tests.
- Doctor branch: 23 focused Python tests passed; full backend suite passed from `backend/` at 406 tests. PowerShell/Pester could not be independently run on the Linux review host.
- Migration cleanup: 6 focused tests passed; full backend suite passed from `backend/` at 389 tests.
- All three diffs passed `git diff --check`.
- Running the documented backend command from repository root exposed a pre-existing cwd-sensitive BLE subprocess-test defect; the same suites pass from `backend/`.

## Handoff

Claude should address the scanner and doctor findings, push updated exact heads, update each active record to name those heads, and request re-review. The migration cleanup may merge independently before either branch, subject to ordinary integration checks.
