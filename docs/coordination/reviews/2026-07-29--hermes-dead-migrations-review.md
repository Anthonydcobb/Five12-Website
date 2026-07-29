# Hermes review — remove dead root-level migrations

- **Reviewed branch:** `origin/chore/claude/remove-dead-migrations`
- **Reviewed head:** `fbdebf57fe69a7ac97434e0f08540994d590a507`
- **Base:** `origin/main` at `aa4b25b9d2411ec9565ebcb918b3e302f9883701`
- **Verdict:** **Approved; no blocking findings**
- **Evidence:** complete history/diff review, reference tracing, filesystem tests, and Claude's empty-MySQL-chain verification

## Critical

None.

## Warning

None.

## Suggestion — make the documentation guard discriminating

`backend/tests/test_migrations_layout.py:54-58` checks only that `AGENTS.md` and `CLAUDE.md` contain `backend/migrations`. Both files already contained that phrase in their repository-layout section on `main`, even while the database paragraph still incorrectly said `migrations/`.

The test therefore passes if the misleading instruction regresses.

Improve the assertion so the schema-management instruction and command cwd explicitly name `backend/migrations/` / `backend/`, or prohibit the ambiguous unqualified sentence.

## Looks good

- The deleted root migration tree is a separate obsolete chain, not a copy of the live revisions.
- The live chain remains untouched at `backend/migrations/`.
- Repository docs and `.gitignore` correctly point future work at the backend chain and prevent accidental root-chain recreation.
- No startup, deployment, Flask-Migrate, CI, or active documentation reference was found that requires the root chain.
- Running `flask db` from the repository root will now fail loudly instead of silently choosing the wrong chain. That behavior change is desirable and documented.
- Deleted revisions remain recoverable from Git history; no live migration history is erased.
- The branch also removes committed `__pycache__`/`.pyc` artifacts from the dead tree.
- Claude's disposable MySQL verification applied the live chain to one head and found zero model differences.

## Checks

```text
Migration-layout tests: 6 passed
Full backend suite from backend/: 389 passed, 10 warnings
git diff --check: passed
```

The full suite's repository-root form exposed the pre-existing cwd-sensitive BLE subprocess-test defect documented in the other reviews; from `backend/`, this branch is green.

## Merge recommendation

This cleanup may merge independently before the scanner and doctor branches. After merge, run migrations only from `backend/` and archive the active record through the normal coordination workflow.
