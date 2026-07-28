# Hermes cross-review — PR 2 network route safety

- **Date:** 2026-07-27
- **Reviewer:** Hermes Agent
- **Branch reviewed:** `claude/pr2-network-route-safety`
- **Commit reviewed:** `a86cff1`
- **Base:** `main` at `c8be6db`
- **Verdict:** **Approve the implementation, with one requested regression-test addition and a mandatory Windows bench gate**
- **Evidence level:** software verified; not bench-tested; not verified on actual hardware

## Bottom line

The implementation closes the direct PowerShell-injection path. Request values are transported in the child-process environment and referenced as PowerShell variables; they do not enter the `-Command` source text. IP/gateway/prefix validation, live adapter allowlisting, the Origin check, and the network-tools kill switch provide useful independent layers.

I found no implementation defect that reopens arbitrary PowerShell execution. I do request one test-only addition before merge: prove the environment-variable barrier still holds when the live adapter allowlist itself contains an injection-shaped but legitimate alias. The current tests reject that alias before reaching the environment transport, so they do not independently pin the strongest claimed guard.

## Claim 1 attacked — `$env:` transport

### Static path audit

All `_run_ps()` calls in `backend/app/routes.py` were enumerated:

- Adapter enumeration: no request parameters.
- Interface listing: no request parameters.
- Static-IP write: constant environment keys for adapter/IP/gateway.
- DHCP write: constant environment key for adapter.

The only remaining Python interpolation in the static-IP script is:

- `prefix`, after integer conversion and the inclusive `1..32` bound.
- `gw_line`, selected from two constant strings.

No adapter, IP, or gateway value is interpolated into PowerShell source.

### PowerShell semantics

Microsoft's PowerShell documentation states that environment variables are inherited by child processes, are stored as strings, and are read using `$Env:<variable-name>`. The parsing documentation states that variable references in argument mode are evaluated to their values. An environment variable's string value is not reparsed as additional PowerShell source.

The invocation uses one consistent path:

```text
powershell -NoProfile -NonInteractive -Command <constant/validated script>
```

Python supplies a per-process `env` mapping to `subprocess.run()`. This is the correct boundary: source is parsed from the command argument; operator data is retrieved afterward as variable values.

### Independent adversarial spike

I ran a separate check where the mocked live adapter list deliberately included this injection-shaped alias:

```text
Ethernet 2'; Start-Process calc.exe; #
```

The route accepted it as a known adapter, returned success under the mocked shell, kept the complete value out of the script text, and passed it only as `FIVE12_ADAPTER`. IP and gateway likewise remained out of script text. Result:

```text
env_transport_with_allowlisted_hostile_alias=PASS
```

This attacks the environment barrier independently of validation/allowlisting.

### Requested test

Add the above scenario to `backend/tests/test_network_routes.py`: temporarily make the fake adapter inventory contain an injection-shaped alias, submit it as an otherwise valid request, and assert that it is absent from script text but exact in the child environment.

This is a test request, not an implementation redesign.

### Remaining limitation

Neither `powershell.exe` nor `pwsh` exists in the Linux review environment, so I did not execute the script through a real PowerShell parser or Windows NetTCPIP cmdlets. The final proof remains Anthony's Windows bench test.

## Claim 2 attacked — Origin policy

### Real application origins

The actual runtime paths are:

- Electron loads `http://127.0.0.1:5050`.
- Vite defaults to `http://localhost:5173`; the same server can be reached as `127.0.0.1:5173` depending on resolver/browser behavior.
- Direct Flask development uses port 5000.
- IPv6 loopback parses as hostname `::1`.

Independent route checks confirmed acceptance of:

```text
http://127.0.0.1:5050
http://localhost:5173
http://127.0.0.1:5173
http://localhost:5000
http://[::1]:5173
```

They confirmed rejection of:

```text
https://evil.example
Origin: null
file://
```

Therefore the current allowlist covers the actual Electron, Vite, and direct-Flask browser origins.

### Policy breadth

`_local_origin()` is a **hostname allowlist**, not an exact-origin allowlist. It also accepts origins such as unrelated `localhost` ports or HTTPS loopback ports. I confirmed this behavior independently.

This does not reopen the original public-web CSRF path: a public page keeps its public hostname in `Origin`, even if it targets loopback. It does mean a malicious webpage already served from another loopback port is treated as first-party. Because raw local clients are intentionally allowed without an Origin header, this endpoint is not attempting to authenticate local processes.

Verdict: non-blocking for the stated loopback desktop threat model, but the wording should remain explicit that all loopback-host origins are trusted. Exact scheme/port matching or real authentication is the stronger future design.

One comment correction is worthwhile: the current IP configuration calls originate in the Electron renderer through Axios, not Electron's main process. Chromium should send the renderer origin; that path is allowed. The absent-Origin exception serves curl or other native callers.

## Other review results

### Kill switch

Confirmed the three routes live on the always-registered blueprint. Adding per-route `ENABLE_NETWORK_TOOLS` checks closes the documented gap. The new tests prove disabled routes do not invoke PowerShell.

### Red/green discrimination

I independently placed Claude's new test file against unpatched `main`:

```text
19 failed, 7 passed
```

The failures directly expose interpolation, missing validation, missing Origin rejection, and the ineffective kill switch. On PR 2:

```text
185 passed, 9 pre-existing warnings
```

### Final PR 1 + PR 2 integration

I trial-merged PR 2 into final PR 1 commit `aaca308` with no conflicts and ran the complete backend suite:

```text
190 passed, 9 pre-existing warnings
```

This independently extends Claude's earlier combined test, which used PR 1 commit `6ad834b`, to the actual final PR 1 head.

## PR 1 review bookkeeping

Claude's written PR 1 review names commit `6ad834b`, while the current PR 1 head is `aaca308`. The follow-up removes the dead root Flask package, restores config-module state after each test, and adds migration documentation. I independently verified and integrated `aaca308`, but Claude's review document should be amended to name the final SHA before the cross-review checkbox is treated as exact.

## Merge gates

Before PR 2 is trusted for production/show use:

1. Add the allowlisted-hostile-alias environment-transport regression test.
2. Run the full backend suite again.
3. On Anthony's Windows rig, with a safe spare/test adapter rather than the active control link:
   - capture current adapter state;
   - apply a non-conflicting static IP through the Five12 UI;
   - verify address, prefix, gateway, and connectivity;
   - switch back to DHCP;
   - verify lease, gateway, and connectivity are restored.
4. Label evidence accurately: current evidence is **software verified only**.

Do not perform the bench test on the NIC carrying an active Hog/show-control network or the machine's only management path.

## Final-head re-verification

Claude addressed the requested changes in:

- `0cdc7ec` — adds two allowlisted-hostile-alias transport tests.
- `82ba5d4` — corrects the renderer/Origin and hostname-allowlist comments without changing behavior.

I inspected both commits and independently reproduced the final evidence:

```text
PR 2 focused tests at 82ba5d4:       28 passed
PR 2 complete backend at 82ba5d4:   187 passed, 9 warnings
Final tests against unpatched main:  21 failed, 7 passed
PR 1 aaca308 + PR 2 82ba5d4:         clean merge; 192 passed, 9 warnings
```

The two newly requested tests fail against the vulnerable implementation and pass at the final head. The comments now accurately describe the Electron renderer and the breadth of the hostname-only loopback policy.

**Final software verdict:** approved at `82ba5d4`. The only PR 2 gate remaining is the Windows spare-adapter bench test. Evidence remains software verified only—not bench-tested and not verified on actual gear.

## Sensitive-history correction

Claude's original PR 1 review included a removed credential literal inside a verification command. The current review text is redacted, but the literal remains in the history of Claude's superseded documentation commit and Hermes's cherry-pick of that commit. The current coordination tree has been replaced with Claude's redacted review, but this does not erase earlier objects.

Therefore the eventual sensitive-history cleanup must include the credential-bearing application commits **and** the affected documentation commits/branches. Until a coordinated rewrite is approved, the coordination branch should be squash-merged or rebuilt from a clean tree rather than merged with its full history. Rotation remains the first and more important gate.
