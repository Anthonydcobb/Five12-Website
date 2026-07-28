# Hermes completion notice — PR 1 credential/config cleanup

- **Date:** 2026-07-28
- **Author:** Hermes
- **Audience:** Claude Code
- **Status:** complete and merged
- **Merged head:** `aaca308cbbc8513da0bfa014937bd5b5eb5bef6f`

## Completion summary

Anthony completed the external credential-migration gate without placing any credential values in Git, chat documentation, or this handoff:

- The previously exposed MySQL administrator credential was rotated.
- Five12 now uses a dedicated `five12_app@localhost` account limited to the `five12_website` schema, with no administrative role or grant option.
- The actual PR 1 backend loaded the untracked local `.env` and returned `1` from a read-only `SELECT 1` through the replacement account.
- Mail settings were cleared. The relevant Google account reported no active app passwords, so no active mail app credential remained to revoke.
- The temporary pre-migration `.env` backup was deleted and its absence verified.
- The replacement `.env` remains ignored by Git.

## Merge and verification evidence

Immediately before merge, Hermes reran the backend suite at exact head `aaca308`:

```text
164 passed, 9 warnings in 44.49s
```

Hermes then fast-forwarded remote `main` from `c8be6db` to `aaca308`, fetched the remote state back, and verified:

```text
origin/main = aaca308cbbc8513da0bfa014937bd5b5eb5bef6f
origin/main...origin/fix/hermes/credential-config = 0 / 0
tracked environment files on main = .env.example only
```

## Message to Claude

PR 1's software and operator gates are closed. Fetch `origin` and use `origin/main` at `aaca308` as the base for subsequent work. Do not continue treating credential rotation as a merge blocker.

The following remain separate cleanup items and were not silently folded into PR 1:

- Coordinated Git-history rewrite to purge old secret-bearing objects
- Removal of remaining tracked `.pyc` files
- Dead `Procfile`/deployment-entry cleanup
- Production environment-loading clarification for non-Flask-CLI launch paths
