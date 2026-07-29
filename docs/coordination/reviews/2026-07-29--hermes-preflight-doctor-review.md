# Hermes review — Five12 preflight doctor

- **Reviewed branch:** `origin/feat/claude/preflight-doctor`
- **Reviewed head:** `a2dbd856ddff3cdf717a860111320423d65e6589`
- **Base:** `origin/main` at `aa4b25b9d2411ec9565ebcb918b3e302f9883701`
- **Verdict:** **Request changes; do not merge yet**
- **Evidence:** complete diff review, Python tests and targeted reproductions on Linux; Claude's Windows/Pester results remain the Windows evidence

The read-only design, pure PowerShell decision module, focused fault tests, and actionable output are all strong. The problem is false assurance: several paths can still pass or launch despite the exact classes of stale-runtime and conflicting-process failures the doctor is meant to prevent.

## Critical

None.

## Warning 1 — repo identity does not actually detect a stale checkout

`scripts/doctor.ps1:82-89` collects branch, dirty state, and origin URL. `Test-Five12RepoIdentity` in `scripts/Five12Doctor.psm1:174-219` checks path, OneDrive, origin-name pattern, dirtiness, and whether the branch is `main`.

It never fetches or compares `HEAD` to an upstream or expected revision. Therefore a clean canonical checkout on an old commit—the core "stale checkout" failure mode—can receive only the ordinary `main` warning and exit successfully. A stale feature branch outside OneDrive can also pass.

**Required change:** report exact local HEAD and upstream HEAD, detect behind/diverged state after a bounded fetch or against a clearly labeled last-known remote ref, and make stale/diverged state fail or require explicit override. Tests must distinguish a current checkout from a behind checkout.

## Warning 2 — the Python probe does not use Flask's effective environment semantics

At `scripts/doctor_probe.py:467-478`, the report and database probe give `backend/.env` precedence over the inherited process environment. Flask CLI/python-dotenv does the opposite: existing process variables are not overwritten by `.env`.

I reproduced a process `DB_PASSWORD` conflicting with the file. The doctor selected the file value and reported no override, while `os.getenv()`—and therefore Five12 config—selected the process value. The doctor can consequently approve credentials different from those the app will use.

`parse_env_file` also does not fully match python-dotenv parsing; an inline comment after a quoted value remains part of the doctor's value while python-dotenv strips it.

**Required change:** use `python-dotenv` itself to parse, model process-over-file precedence exactly, report key-level override provenance without values, and test conflicts and inline comments. Never emit secret contents.

## Warning 3 — process hygiene allows the launch to create a conflict

`Test-Five12FlaskProcesses` at `scripts/Five12Doctor.psm1:487-524` treats exactly one Flask process and one port owner as healthy. But the doctor runs immediately before `start.ps1` launches another backend. If one backend already exists, the next launch creates a competing process or fails port binding.

It also treats one foreign process owning port 5000 with zero matching Flask processes as healthy. `doctor.ps1:196` then assumes any port owner means "backend up" and probes whatever service is there.

**Required change:** in pre-launch mode, any existing backend or any foreign port owner must block launching a second backend, or `start.ps1` must deliberately reuse/restart the verified existing instance. Match the port-owning PID to the expected interpreter/command line. Add tests for one existing Flask process and one foreign port owner.

## Warning 4 — the launcher does not explicitly fail closed if the doctor crashes

`start.ps1` invokes the script and checks `$LASTEXITCODE`, but does not wrap invocation in `try/catch` or verify that a valid result/exit code was produced. A terminating PowerShell error or unexpected script failure can bypass the intended controlled "FAILED / launch anyway" path depending on host/error semantics.

**Required change:** invoke the doctor through an explicitly checked process or wrap it in `try/catch`; treat exceptions, missing exit status, and nonzero exit as failure. Add an integration test with a doctor stub that throws before returning.

## Warning 5 — the documented root-level backend command is currently broken

The branch strengthens `docs/coordination/README.md` around using the app interpreter but retains the repository-root command:

```text
<python> -m pytest -q backend/tests
```

I ran it on all three review branches. Three BLE lock tests failed because `backend/tests/test_ble_scanner.py:21-29` inserts `backend/app` into child `sys.path` instead of `backend`; running from `backend/` masks the bug through cwd.

**Required change:** fix `BACKEND_DIR`/the subprocess prelude so the documented root command passes, then keep one canonical cwd-independent command.

## Suggestions

- Fix commands containing interface aliases should escape PowerShell single quotes or pass values structurally. A stored alias containing `'` can break copied commands; remediation text should never become an injection footgun.
- Explain or separate the unrelated `requests` 2.32.3 → 2.34.2 bump. It is a valid released version, but dependency churn should have a stated reason.
- Update the branch's active record to name final reviewed head `a2dbd85`; its recorded review target/commit list is stale.
- The global "Unidentified Networks = Private" policy is a real security tradeoff because it affects every unidentified network. The script correctly does not apply it automatically and mentions its breadth; keep that warning prominent.

## Looks good

- The doctor is read-only and does not alter firewall, NIC categories, policy, packages, or credentials.
- Secret values are not intentionally emitted; presence and lengths are reported.
- The PowerShell decision functions are separated for synthetic tests.
- Npcap presence/service and Scapy provider checks address a genuine false-green capability gap.
- `--no-reload` and BLE feature-gate checks are operationally valuable.
- The network-category root-cause explanation is evidence-rich and distinguishes immediate from durable remediation.

## Checks

```text
Python doctor tests: 23 passed
Full backend suite from backend/: 406 passed, 10 warnings
git diff --check: passed
PowerShell/Pester: not independently run; pwsh is unavailable on the Linux reviewer
```
