# Handoff — DYMO print sequencing, Stop/progress, Twin Turbo roll, honest preview failures

- **Owner:** Claude
- **Reviewer:** Hermes
- **Branch:** `fix/claude/dymo-print-sequencing` (pushed to `origin`)
- **Base / head SHA:** base `8291f77` (`origin/main`) / head — see PR
- **Status:** review — awaiting Hermes
- **Hardware evidence:** verified on actual gear (DYMO LabelWriter 450 Twin Turbo) — see scope limits under *Known risks*
- **Last updated:** 2026-08-05

> **Rebased 2026-08-05.** This branch sat unreviewed while 37 commits landed on
> `main` (the Astera tablet mirror and the home-screen boot sequence). It has
> been rebased from base `8ba2457` onto `8291f77`; the old head was `bb7cdb6`.
> The merge commit `cff1a32` was flattened, so this is now 17 linear commits,
> matching `main`'s no-merge-commit history.
>
> **The rebase was clean — zero conflicts.** The two sides touch disjoint files
> (11 here, 34 on `main`, no overlap). Re-verified on the rebased tree, not
> assumed: backend `661 passed, 7 skipped`; frontend `11 files, 133 passed`;
> `npm run build` clean. Nothing in the review below changed.

## What changed

17 commits ahead of `origin/main`. Frontend print dialog and DYMO wrapper, plus one new backend endpoint.

**Printing is sequenced, one record at a time.** The service returns from `PrintLabel` as soon as it *accepts* a job, not when the label finishes feeding. Firing jobs back-to-back made the LabelWriter start a new job mid-feed and re-seek the label gap (the "buzz"/misregistration). Each label now waits for the printer queue to fully drain before the next is submitted.

**Job status comes from the Windows spooler, not DYMO.** New `GET /api/print-queue` reads the spooler; DYMO jobs land there under the same printer name and drain in ~1.8 s.

**No LabelSet batching.** The service answers any non-empty `labelSetXml` on a DesktopLabel with HTTP 400 whatever its shape, so one merged label per job is the only accepted form.

**Stop button, live progress, honest run outcomes.** Stop halts between labels; the service has no cancel endpoint, so the label in flight always completes and is counted.

**Twin Turbo roll selector.** Left/Right via `LabelWriterPrintParams`, remembered per printer, sent only for Twin Turbo printers.

**Paper-out is detected on the job, not just the printer.** Windows `PrintJobStatus` is a flags enum, so a job can carry a paper-out while `Get-Printer` still reports Normal. Checking only the printer let a run keep feeding an empty printer and finish reporting success.

**Preview failures are surfaced instead of blamed on the mapping.** A failed render was swallowed by a bare `.catch(() => setPreview(null))`, leaving the pane showing "preview appears when mapped" — which reads as *you haven't finished mapping* when the fault is in the render service. Three distinct states now: image on success, actionable failure message, placeholder only when nothing is mapped.

## Why this approach

**Spooler over DYMO job status, because the DYMO path does not exist.** On DYMO Connect 1.6.1.7 the vendored `DlsWebService` has no `getJobStatus` method (`framework.job.getStatus()` always answers Unknown/"not implemented"), `PrintLabel2` returns `true` rather than a job id, and the service's `GetJobStatus` HTTP endpoint 404s identically to a nonexistent route. Polling DYMO was implemented first (`7580a02`) and then replaced (`70821ec`) once that was established.

**A diagnosis recorded on this branch was wrong and has been corrected in place.** Commit `63041dc` and the note in `lib/dymo.js` previously stated that `RenderLabel` is permanently broken in 1.6.1.7 — HTTP 500 with an empty body for every input, traced to a `FileNotFoundException` on `System.Xml.XmlSerializer` in the Windows Application log, attributed to the assembly being absent from DYMO's single-file bundle.

That conclusion came from a confounded experiment: it added the assembly **and** restarted the host process in one step. The missing control was run on 2026-08-04 — a fresh host, exe only, nothing added — and it renders the same template to a byte-identical PNG (16330 B). The assembly ships in the bundle. That host *process* had degraded and could no longer resolve it; the exception was a symptom, not a packaging defect.

Operational consequence: the fault is recoverable by restarting DYMO Connect, and the preview message now says exactly that. Anyone re-investigating should read the note above `renderPreview` in `app/src/lib/dymo.js` before re-running these probes.

## Files and contracts affected

```text
app/src/components/DymoPrintDialog.jsx        135 +/-
app/src/components/DymoPrintDialog.test.jsx   219 +
app/src/lib/dymo.js                           145 +/-
app/src/lib/dymo.test.js                      295 +
app/src/lib/labelMerge.js                      64 +/-
backend/app/__init__.py                         3 +
backend/app/print_queue_routes.py              96 +
backend/tests/test_print_queue.py              94 +
docs/superpowers/plans/2026-08-03-dymo-print-sequencing.md
docs/superpowers/.../2026-08-03-dymo-print-sequencing-design.md
```

**New contract:** `GET /api/print-queue?printer=<name>` → `{ printerStatus, jobCount, jobs: [{ status, ... }] }`. Loopback-only, read-only, no new auth surface.

`backend/app/__init__.py` is touched (3 lines, blueprint registration) — a shared central file under rule 4. No other agent held a reservation for it at the time of writing; re-check before integration.

## Database, migration, and dependency impact

None. No models, no migrations, no new Python or npm dependencies.

## Verification actually run

```text
# Backend — the interpreter start.ps1 launches the app with (not PATH python)
& 'C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe' -m pytest -q backend/tests
572 passed, 7 skipped, 130 warnings in 14.83s

# Frontend
npx vitest run
Test Files  9 passed (9)
     Tests  103 passed (103)

npx vite build
✓ built in 3.25s   (chunk-size warning only, pre-existing)

# Hygiene
git status --short        -> clean
git diff --check          -> clean
git ls-files | grep -E '(\.env|__pycache__|.*\.pyc)$'
  -> 3 tracked .pyc files, ALL pre-existing on origin/main, none touched by
     this branch (git diff --name-only origin/main...HEAD has no .pyc)
```

**Live-service probes, 2026-08-04, DYMO Connect Web Service 1.6.1.7 on 127.0.0.1:41951:**

```text
RenderLabel, fresh host, exe only, no files added:
  stock DLS 8.0 DieCutLabel     -> 200, PNG (6782 B)
  stored template 3             -> 200, PNG (16330 B)
  not-xml-at-all                -> 400 "Data at the root level is invalid."
  empty labelXml                -> 400 "Invalid params collection."
Same matrix against the degraded host earlier that day: 500 + empty body for
every input including no parameters at all.
```

**In-app preview, verified in the running app** — template *LZMU Dymo Label Big*, `LZMU_Elton_Patch_App_Import(2).csv` (139 rows), Device Type / Fixture Number / Universe / Address mapped: preview image present and valid, placeholder gone, no console errors, jogging ‹ › re-renders a visibly different label per record.

**Printer:** Anthony confirms printers and preview are working on the actual LabelWriter 450 Twin Turbo.

## Operator acceptance test

1. Labels → DYMO → choose *LZMU Dymo Label Big*, load a patch CSV, map the variables. Preview should show the label and change as you jog ‹ ›.
2. Print a short custom range (e.g. `2-4`). Labels should feed cleanly with no mid-feed re-seek between them.
3. Press Stop mid-run. The run should end after the label in flight, and the count reported should match what physically came out.
4. On a Twin Turbo, switch the roll selector and confirm the next label feeds from the other side.
5. Pull the roll mid-run. The run should stop and report *Paper out*, not finish claiming success.
6. To exercise the preview-failure path: kill `DYMO.WebApi.Win.Host.exe`, reopen the dialog. The pane should say preview unavailable and tell you to relaunch DYMO Connect — not "preview appears when mapped".

## Known risks / skipped checks

- **Steps 3–5 of the acceptance test are not confirmed on gear by this session.** Stop, the roll selector, and job-level paper-out are covered by unit tests only. Anthony's "printers and preview are working" covers detection, output, and preview; it was not scoped to those three paths. Treat them as `bench-tested` until someone runs steps 3–5.
- `backend/app/__init__.py` is a shared central file; re-fetch and re-check reservations before integrating.
- The spooler drain has a `JOB_CEILING_MS` of 15 s per label. A genuinely slow or stalled job falls through the ceiling and the run continues rather than hanging — deliberate, but it means a pathological printer could under-report trouble.
- A stray `System.Xml.XmlSerializer.dll` was copied into `C:\Program Files (x86)\DYMO\DYMO Connect\` during the confounded experiment and is **still there** on Anthony's rig. It is inert and unrelated to the fix, but should be deleted from an admin shell so it does not mislead a future investigation. Not a repo change.
- No PR opened: `gh` is not authenticated on this rig and both GitHub MCP servers return `401 Bad credentials`. Branch is pushed; PR body is drafted and ready.

## Reviewer findings

### Critical

### Warnings

### Suggestions

### Looks good

## Next action

Hermes to review the diff independently against `origin/main` (`8ba2457...cff1a32`), rerun the canonical checks, and record findings above. If the review is clean, open the PR — the drafted title and body are ready and Anthony has them; `gh auth login` on this rig is the only blocker.
