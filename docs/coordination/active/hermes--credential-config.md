# Active work — credential configuration cleanup

- **Owner:** Hermes
- **Branch:** `fix/hermes/credential-config`
- **Workspace:** persistent worktree at `/root/five12-pr1-credentials`
- **Base SHA:** `c8be6db`
- **Status:** active
- **Last updated:** 2026-07-27

## Goal

Remove committed environment credentials from the tracked tree, eliminate the hard-coded database-password fallback, and establish `DB_PASSWORD` as the single configuration contract.

## Acceptance criteria

- [ ] Root `.env` is no longer tracked.
- [ ] Placeholder-only `.env.example` documents required keys.
- [ ] No database password default remains in application code.
- [ ] `DB_PASS` is no longer an accepted or documented variable.
- [ ] Missing `DB_PASSWORD` fails with a clear startup error in development mode.
- [ ] Desktop SQLite mode still starts without a database password.
- [ ] Backend tests pass.
- [ ] Anthony is warned to back up the current local `.env` and rotate the affected MySQL/mail credentials before merge.

## Advisory reserved paths

- `.env`
- `.env.example`
- `.gitignore`
- `backend/config.py`
- `backend/app/__init__.py`
- `app/__init__.py` (sanitize the stale legacy Flask configuration without structural cleanup)
- `__pycache__/app.cpython-310.pyc` (remove the secret-bearing compiled artifact)
- Credential-configuration regression tests added by this task

## Must-not-touch paths

- `backend/app/routes.py` and network-route behavior (reserved for PR 2)
- Frontend manifests and lockfiles
- Cintenna BLE branch files
- Database migrations

## Interfaces and contracts

Development MySQL configuration uses `DB_HOST`, `DB_USER`, `DB_PASSWORD`, and `DB_NAME`. Desktop mode remains SQLite-only and does not require those values.

## Checks planned

- Focused configuration tests
- Full `backend/tests` suite
- Tracked-file check proving `.env` is absent
- Search proving `DB_PASS` is absent from active backend code
- Missing-password and desktop-startup checks

## Risks and skipped checks

Removing a previously tracked `.env` causes Git to delete that tracked working-tree file when existing clones pull the merge. Anthony must back up the local file outside the repository before merge. This PR does not rotate credentials or rewrite Git history.

## Handoff / next action

Hermes implements and verifies the bounded repository change, then Claude Code independently reviews it before merge.
