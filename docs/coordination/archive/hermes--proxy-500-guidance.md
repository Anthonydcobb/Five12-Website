# Active work — Vite proxy 500 guidance

- **Owner:** Hermes
- **Branch:** `fix/hermes/proxy-500-guidance`
- **Workspace:** `/root/five12-worktrees/hermes-proxy-guidance`
- **Base SHA:** `3814034` (`origin/main`)
- **Status:** complete
- **Last updated:** 2026-07-30

## Goal

Use Anthony's live Windows bench result to make an empty Vite-proxy HTTP 500 explain that Flask may be unavailable, while preserving distinct formatting for backend-generated HTTP errors.

## Acceptance criteria

- [x] Empty 5xx responses identify the failed fixture request and suggest checking Flask.
- [x] Backend 5xx JSON errors keep their actual backend detail and are not mislabeled as transport failures.
- [x] Existing scoped retry, recovery, action-success, and stale-request behavior remains green.
- [x] Full frontend tests and production build pass.

## Reserved paths

- `app/src/pages/Database.jsx`
- `app/src/pages/Database.test.jsx`
- `docs/coordination/active/hermes--proxy-500-guidance.md`

## Must-not-touch paths

Backend, database, migrations, network/BLE/sACN, dependency manifests, Electron.

## Interfaces and contracts

No API changes. This handles the Vite dev proxy's observed empty HTTP 500 when Flask is stopped.

## Evidence

Anthony bench-tested the failure half on Windows at commit `7408086`: with Flask stopped and the Database page hard-refreshed, Vite returned separate empty HTTP 500 responses for fixture status and catalog. The UI correctly scoped both failures and offered retry, but said only `No error details returned.`

## Checks

- New empty-proxy-500 regression test was observed failing against `3814034`, then passing after the narrow wording change.
- `npm run test -- --run src/pages/Database.test.jsx` — **10 passed**.
- `npm run test` — **63 passed**.
- `npm run build` — passed; pre-existing large-chunk warning only.
- `git diff --check` — clean.

## Independent review

Commit `f70185d` received **Looks Good** with no Critical, Warning, or Suggestion findings. The reviewer independently confirmed focused tests 10/10, production build passed, and diff check clean.

## Handoff / next action

Integrated after independent review. Pull `main`, repeat Anthony's stopped-Flask screenshot, restart Flask, and verify retry recovery without a browser refresh.
