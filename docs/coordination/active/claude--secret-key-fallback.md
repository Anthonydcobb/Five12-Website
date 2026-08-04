# Active work — remove the hardcoded SECRET_KEY fallbacks

- **Owner:** Claude
- **Branch:** `fix/claude/secret-key-fallback`
- **Workspace:** local Windows worktree, `C:\dev\five12-wt\secret-key`
- **Base SHA:** `e3c4bb7` (`origin/main`)
- **Status:** complete, pushed for review
- **Last updated:** 2026-07-30

## Goal

W4 of `2026-07-30--claude-review-of-hog-fixture-import.md`. Hermes named this as
the safest independent lane and asked for exact paths claimed before editing.

The Hog import added to `DevelopmentConfig`:

```python
SECRET_KEY = os.getenv("SECRET_KEY", "five12-development")
```

A hardcoded fallback, in the file whose entire recent history is
`fix/hermes/credential-config` removing exactly that shape for the database
password. `DesktopConfig` carried a bare literal `'five12-desktop'` from before.

## What the key actually does

One consumer: signing the fixture-import preview token
(`fixture_library_routes.py:44`). **The app uses no Flask sessions at all** —
`git grep` for session use in `backend/app/` returns nothing.

That decides the fix. An unconfigured key can simply be generated per process.
The only consequence is that a preview token does not survive a backend restart,
and that is correct behaviour rather than a cost: the operator should re-preview
rather than import against a catalog snapshot taken before a restart.

```python
SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_urlsafe(32))
```

Both configs. Secure by default, no new setup burden, and an operator who sets
`SECRET_KEY` still gets a stable one.

## The interaction that decided how it is written

`scripts/doctor_probe.py` derives the `.env` key list by **parsing `config.py`
with ast** — that is fault 4's whole point, a hardcoded list goes stale. Its
rule:

```text
os.getenv(K, default)   -> has_default True  -> optional
os.getenv(K)            -> has_default False -> REQUIRED
os.environ[K]           ->                      REQUIRED
```

So the obvious tidier forms are both wrong:

- a `_secret_key()` helper makes `SECRET_KEY` **invisible** to the check
- dropping the default makes the doctor **demand** a key that is optional

The two-argument `os.getenv` shape has to survive, which it does — only the
default changes from a literal to a generated value. Pinned by
`test_the_doctor_still_reads_secret_key_as_OPTIONAL`, which parses the real
`config.py` through the real probe.

This is the sort of second-order effect that would have shipped silently.

## Scope change from what was proposed to Hermes

I told Hermes I would leave `DesktopConfig.SECRET_KEY` alone, on the grounds
that `'five12-desktop'` predates all of this and changing it was "a packaging
decision rather than a cleanup."

**That reasoning was wrong and is retracted.** It rested on not knowing what the
key was for. Having established there is exactly one consumer and no sessions,
the desktop case is not a packaging decision at all — it is the identical
one-line fix, and leaving a known constant in the shipped desktop build while
fixing the dev one would be the worse half of the job. Included, and flagged
here rather than quietly widened.

## Reserved paths

- `backend/config.py` (the two `SECRET_KEY` lines only)
- `backend/tests/test_config.py`
- `docs/coordination/active/claude--secret-key-fallback.md`

## Must-not-touch paths

- `scripts/doctor_probe.py` — read only, to learn the parse rule. No change
  needed: the fix was written to fit the existing contract rather than to
  change it.
- `backend/app/fixture_library*.py`, `app/src/pages/Database.*` — Hermes' W2
- migrations, models, dependency manifests, `.env`

## Checks run

| Command | Result | Evidence level |
|---|---|---|
| `pytest -q backend/tests/test_config.py` | **11 passed** | software verification (Windows rig) |
| `pytest -q backend/tests` from the repository root | **556 passed**, 7 skipped | software verification (Windows rig) |

Six tests written first and watched failing: no shipped constant in either
config, real entropy, two processes not sharing a key, a configured key still
honoured, and the doctor-classification guard.

`SECRET_KEY` added to `test_config.py`'s `_CONFIG_ENV_KEYS` so a generated value
cannot leak into later tests.

**Not verified:** the doctor was not run end to end against a tree that has a
real `backend/.env`. This worktree has none — it is gitignored and lives only in
the main checkout — so `doctor.ps1` FAILs there on `.env completeness` and
`Database` regardless of this change. The classification itself is covered by
the unit test above, which runs the real probe over the real `config.py`.

## Handoff

Pushed for review, not merged. Small and self-contained, but the piece worth a
second opinion is the scope change above — I proposed one thing to Hermes and
did a slightly larger thing, for a reason I believe is right but which Hermes
should get to disagree with.
