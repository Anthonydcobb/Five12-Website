# Active work — credential configuration cleanup

- **Owner:** Hermes
- **Branch:** `fix/hermes/credential-config`
- **Workspace:** persistent worktree at `/root/five12-pr1-credentials`
- **Base SHA:** `c8be6db`
- **Status:** review
- **Last updated:** 2026-07-27

## Goal

Remove committed environment credentials from the tracked tree, eliminate the hard-coded database-password fallback, and establish `DB_PASSWORD` as the single configuration contract.

## Acceptance criteria

- [x] Root `.env` is no longer tracked on the feature branch.
- [x] Placeholder-only `.env.example` documents required keys.
- [x] No known database password default remains in the candidate tree.
- [x] `DB_PASS` is rejected by regression test and absent from active backend code.
- [x] Missing `DB_PASSWORD` fails with a clear startup error in development mode.
- [x] Desktop SQLite mode still starts without a database password.
- [x] Focused tests pass: 5.
- [x] Full backend tests pass: 164, with 9 pre-existing SQLAlchemy warnings.
- [ ] Claude Code independently reviews final commit `aaca308`.
- [ ] Anthony backs up the current local `.env` and rotates the affected MySQL/mail credentials before merge.

## Advisory reserved paths

- `.env`
- `.env.example`
- `.gitignore`
- `backend/config.py`
- `backend/app/__init__.py`
- `app/__init__.py` (remove the dead duplicate Flask package and its credential path)
- `__pycache__/app.cpython-310.pyc` (remove the secret-bearing compiled artifact)
- `CREDENTIAL-MIGRATION.md`
- Credential-configuration regression tests added by this task

## Must-not-touch paths

- `backend/app/routes.py` and network-route behavior (reserved for PR 2)
- Frontend manifests and lockfiles
- Cintenna BLE branch files
- Database migrations

## Interfaces and contracts

Development MySQL configuration uses `DB_HOST`, `DB_USER`, `DB_PASSWORD`, and `DB_NAME`. Desktop mode remains SQLite-only and does not require those values.

## Checks run

- `/root/five12-website/.venv/bin/python -m pytest -q backend/tests/test_config.py` → **5 passed**.
- `/root/five12-website/.venv/bin/python -m pytest -q backend/tests` → **164 passed, 9 pre-existing SQLAlchemy warnings**.
- `git diff --cached --check` → clean before commit.
- Candidate-tree checks → root `.env` untracked; `.env.example` tracked with empty password/secret fields; legacy `DB_PASS` absent from active backend source; known removed default absent from the candidate tree; local worktree `.env` retained and not displayed.
- Python syntax compilation passed for the changed Python files.
- An isolated Hermes subagent reviewed commit `6ad834b`; its test-isolation, stale-app, and migration-documentation warnings were addressed in follow-up commit `aaca308`.

## Risks and skipped checks

Removing a previously tracked `.env` causes Git to delete that tracked working-tree file when existing clones pull the merge. Anthony must back up the local file outside the repository before merge. This PR does not rotate credentials or rewrite Git history.

## Handoff / next action

Claude Code independently reviews branch `fix/hermes/credential-config` at final commit `aaca308`, without reading or reproducing any credential value. Anthony then backs up the current `.env` outside the repository and confirms credential rotation before this branch is eligible to merge.
