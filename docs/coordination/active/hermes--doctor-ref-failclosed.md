# Active work — doctor integration-ref fail-closed fix

- **Owner:** Hermes
- **Branch:** `fix/hermes/doctor-ref-failclosed`
- **Workspace:** `/root/five12-worktrees/hermes-doctor-ref-failclosed`
- **Base SHA:** `4112383` (`origin/main`, including reviewed scanner/interface integration)
- **Status:** review
- **Last updated:** 2026-07-30

## Goal

Fix forward a Critical post-merge review finding in the preflight doctor: a missing, misspelled, or invalid integration ref currently produces empty stdout and exit 128 from Git but is interpreted as zero commits behind, allowing an obsolete feature branch to pass as current.

## Context / handoff

Claude's preflight integration was merged to `main` at `1c86d1d` while Hermes' final asynchronous review was still running. `claude--preflight-doctor.md` records the integration as complete. This narrowly scoped follow-up owns only the unresolved reviewer finding; it does not replace or redesign Claude's feature.

## Acceptance criteria

- [x] A valid integration comparison preserves the existing current/behind behavior.
- [x] A missing or invalid integration ref is never indistinguishable from zero-behind.
- [x] The repo-identity check fails closed with an actionable fetch/ref message when comparison is unavailable.
- [x] Windows PowerShell 5.1 compatibility and UTF-8 BOM are preserved in the candidate files; native 5.1 bench remains the integration gate.
- [x] Pester passes in a clean PowerShell 7 Linux container and canonical backend checks pass on Linux.

## Reserved paths

- `scripts/doctor.ps1` (integration-ref collection only)
- `scripts/Five12Doctor.psm1` (repo-identity availability input only)
- `scripts/tests/Five12Doctor.Tests.ps1` (regression tests only)
- `docs/coordination/active/hermes--doctor-ref-failclosed.md`

## Must-not-touch paths

BLE tests/implementation, network routes/scanners, database/fixtures, frontend, migrations, dependencies, startup behavior outside the repo-identity input.

## Evidence

Exact-head review of merged candidate `4378b98` reproduced `git rev-list --count HEAD..missing-ref` returning exit 128 with empty stdout. Windows PowerShell 5.1 native-command failures do not throw, and the collector initialized `behindIntegration = 0`; therefore the module could report `OK`.

## Checks

- Discriminating Pester case added for an unavailable integration ref; prior module had no availability input and could only see numeric zero.
- Manual PowerShell module scenarios in `mcr.microsoft.com/powershell:lts-ubuntu-22.04`: missing ref **FAIL**, valid current **OK**, valid behind **WARN**.
- Full Pester 4.10.1 suite in the same clean container: **92 passed, 0 failed** (rerun after review correction and rebase).
- Canonical root backend suite on current `main` plus candidate: **505 passed, 19 warnings**.
- UTF-8 BOM (`EF BB BF`) verified on all three changed PowerShell files after editing.
- `git diff --check` — clean.

## Independent review

Exact commit `91cee0a` had no Critical finding. The reviewer confirmed the fail-closed state, immediate `$LASTEXITCODE` capture, `TryParse`, default behavior, `main` behavior, and BOM. One Warning was accepted: remediation hardcoded `git fetch origin main`, which was wrong for an overridden integration ref. The candidate now prints `git fetch origin; git rev-parse --verify <configured-ref>` and the Pester assertion covers the configured `origin/main` value.

## Handoff / next action

Run Pester and the missing-ref doctor scenario under native Windows PowerShell 5.1 on Anthony's rig. If both pass, archive this record and integrate; no additional code review is needed for the narrow reviewed remediation-string correction.
