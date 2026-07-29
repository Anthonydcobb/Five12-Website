# Hermes PR 1 independent pre-review

- **Date:** 2026-07-27
- **Reviewer:** isolated Hermes subagent (not Claude Code)
- **Branch reviewed:** `fix/hermes/credential-config`
- **Initial commit reviewed:** `6ad834b`
- **Follow-up commit:** `aaca308`
- **Status:** warnings addressed in code; rotation and Claude review remain open

## Findings

### Critical — credentials remain in Git history

Deleting `.env` and defaults from the candidate tree does not purge earlier commits or blobs. Every previously committed MySQL/mail credential must be treated as compromised and rotated. History rewriting, if later approved, is separate coordinated maintenance and does not replace rotation.

### Warning — pulling can delete the local `.env`

A collaborator whose checkout still tracks `.env` may lose that working-tree file when pulling the deletion. Local modifications may block the update, but that is not a backup strategy. Anthony must back up `.env` outside the repository before merge or pull.

### Warning — configuration tests left module state mutated

The original tests restored environment variables but not class-level values in the reloaded `config` module. Commit `aaca308` adds fixture teardown that restores the original environment and reloads the module after each test.

### Warning — stale legacy Flask package lacked coverage

The root `app/__init__.py` was the sole Python source in the React application directory, imported a nonexistent `app.routes`, and retained a second credential path. Commit `aaca308` removes the dead file instead of preserving an untestable duplicate application factory.

### Suggestion — document migration prominently

Commit `aaca308` adds root `CREDENTIAL-MIGRATION.md` covering pre-pull backup, `DB_PASS` → `DB_PASSWORD`, rotation, local restore, ignore verification, and the separate history-rewrite decision.

## Verification

After the follow-up:

- Full backend suite: **164 passed, 9 pre-existing SQLAlchemy warnings**.
- Changed Python files compiled.
- `git diff --check` passed.
- Root `.env` is absent from the candidate index.
- `.env.example` contains blank password/secret fields.
- The known removed default is absent from the candidate tree.
- The dead root Flask package and secret-bearing compiled cache are absent from the candidate tree.
- Feature branch is clean and synchronized with GitHub.

## Remaining gates

1. Claude Code independently reviews final commit `aaca308` without exposing deleted values.
2. Anthony backs up the current `.env` outside Git.
3. Affected MySQL/mail credentials are rotated before merge.
4. History rewriting is decided separately after rotation and collaborator coordination.
