# Five12 Agent Coordination

This folder is the shared coordination layer for Anthony, Claude Code, and Hermes Agent.
It complements detailed implementation plans in `docs/superpowers/`; it does not replace them.

## Non-negotiable operating rules

1. **`main` is integration-only.** Agents work on branches and do not commit directly to `main`.
2. **Isolate concurrent work in the way the runtime supports.** Hermes and other persistent local agents use separate worktrees. Claude Code cloud sessions use their assigned fresh clone/branch and must commit and push before the ephemeral session ends.
3. **Claim scope before editing.** Create one file in `docs/coordination/active/` and list the exact reserved paths, shared contracts, and files that must not be touched. Reservations are advisory coordination records, not distributed locks; fetch immediately before starting and re-check before integration.
4. **One owner per collision-prone path.** Do not concurrently edit migrations, lockfiles, agent instructions, API contracts, `backend/app/models.py`, `backend/app/routes.py`, or other shared central files.
5. **Separate implementation from review.** When both agents contribute to one feature, one implements and the other independently reviews and verifies. Do not silently replace the other agent's work.
6. **Integrate serially.** Merge the foundational or lower-risk branch first; rebase the second branch onto the new `main`, resolve conflicts in its worktree, and rerun all checks.
7. **Record decisions, not private reasoning.** Summarize evidence, trade-offs, rejected options, and the chosen path. Do not dump hidden chain-of-thought.
8. **Evidence labels are required.** Hardware behavior must be labeled `simulated`, `bench-tested`, or `verified on actual gear`.
9. **No invented lighting data.** Fixture modes, DMX footprints, protocol fields, console operations, and vendor commands require an official source or Anthony's confirmation.
10. **No unverified live writes.** New device/network integrations start read-only. Writes require an explicit allowlist, confirmation, validation, acknowledgement, and readback where meaningful.
11. **Keep the local safety boundary.** The unauthenticated backend must remain bound to loopback. Any LAN/hosted exposure requires an authentication and authorization design first.
12. **Never commit secrets.** Use `.env.example` with placeholders. Credentials, tokens, linking keys, and private keys stay out of Git and logs.
13. **Protect show data.** Destructive and bulk actions need confirmation, clear error reporting, transaction safety, and a backup/rollback path where practical.
14. **Verify before handoff.** Report the real commands run and their results. Never report an unrun check as passing.

## Branch and workspace convention

Branches use `<type>/<agent>/<slug>`:

```text
feat/claude/patch-history
fix/hermes/import-validation
docs/hermes/agent-coordination
```

Persistent local agents should use sibling worktrees:

```text
Five12-TheApp/                  # stable integration checkout
Five12-worktrees/hermes-<slug>/
```

Claude Code cloud sessions instead use the fresh clone and assigned branch provided to that session. Those paths are ephemeral and do not belong in durable coordination state. Uncommitted cloud-session work may be lost when the session ends.

Do not merge one feature branch into another. If a feature depends on another branch, merge the prerequisite to `main` first.

## Starting work

1. Fetch and start from current `origin/main` in the runtime's isolated workspace.
2. Create or use the dedicated assigned branch. Persistent local agents also create a dedicated worktree; ephemeral Claude cloud sessions do not need one.
3. Copy `templates/active-work.md` into `active/<agent>--<slug>.md`.
4. Record owner, base SHA, scope, advisory reserved paths, contracts, acceptance criteria, and required checks.
5. If another active file reserves a needed path, stop and coordinate before editing. Fetch and re-check reservations before integration because active files are not distributed locks.

## During work

- Commit small logical changes using conventional subjects such as `feat:`, `fix:`, `test:`, `docs:`, and `chore:`.
- Update the active note when scope, interfaces, migrations, dependencies, or risks change.
- Keep detailed feature plans in `docs/superpowers/plans/` and link them from the active note.
- Put durable architecture choices in `decisions/` only when they affect future features.
- Do not put temporary logs, raw credentials, live tokens, packet captures, or generated build output in this folder.

## Handoff and review

Before review, the owner records:

- Commits and changed paths
- API/schema/migration/dependency changes
- Commands run and exact outcomes
- Hardware evidence level
- Known risks and skipped checks
- Clear next action

The reviewer checks the diff independently, reruns canonical checks, and writes findings under `reviews/` using Critical / Warning / Suggestion / Looks Good.

## Current canonical checks

Until CI provides a single command, use the applicable checks:

**Run the backend suite with the interpreter the app itself runs on.** Not
"a" Python — *that* Python. Until 2026-07-29 the Windows rig ran its tests on
whatever `python` was on `PATH` (3.14) while the app ran on 3.12, and the two
had different package sets: the test interpreter was missing six of the app's
requirements, including `bleak`. A green suite therefore said nothing about
whether the app's runtime was intact, which is precisely how a missing
`websocket-client` cost most of a day on 2026-07-28 — that import sits inside
a blanket `except Exception`, so a broken install is indistinguishable from
unreachable hardware. Test-only dependencies live in
`backend/requirements-dev.txt` and belong in the same interpreter.

```bash
# Backend, from repository root — Linux worktrees
.venv/bin/python -m pytest -q backend/tests

# Backend — Windows rig, using the interpreter start.ps1 launches the app with
& 'C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe' -m pytest -q backend/tests

# Frontend
cd app
npm ci
npm run test   # when the branch provides the test script
npm run build

# Repository hygiene
git status --short
git diff --check
git ls-files | grep -E '(^|/)(\.env|__pycache__|.*\.pyc)$'  # should return nothing after cleanup
```

Hardware-dependent acceptance tests remain separate and must identify the actual device/firmware without storing credentials or linking keys.

## Folder layout

```text
docs/coordination/
├── README.md
├── active/       # one conflict-resistant file per agent/task
├── plans/        # lightweight cross-agent plans; link detailed superpowers plans
├── decisions/    # durable architecture and workflow decisions
├── reviews/      # independent reviews and responses
├── templates/    # active-work and handoff templates
└── archive/      # completed active notes and handoffs
```

When work merges, move its active note to `archive/`, retain useful verification evidence, remove the worktree, and prune the branch.
