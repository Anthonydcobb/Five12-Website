# DYMO print sequencing, Stop, and Twin Turbo roll selection — design

**Date:** 2026-08-03
**Files:** `app/src/lib/dymo.js`, `app/src/components/DymoPrintDialog.jsx`, `app/src/lib/dymo.test.js`

## Problem

Three issues, one mechanism:

1. **Buzzing / misregistration on multi-label runs.** `printMerge()` fires one
   `printLabel()` per record through the framework's *synchronous* XHR in a
   tight loop. The DYMO web service returns as soon as it **accepts** a job,
   not when the label finishes feeding, so jobs pile into the spooler and the
   LabelWriter starts a new job while still feeding the previous one — the
   gap re-seek is the buzz. (Batching alternatives are ruled out by evidence:
   the service 400s on any non-empty `labelSetXml`, and physical tests show
   the embedded `DataTable` never drives label count — always one label per
   PrintLabel call.)
2. **No way to stop a run.** The sync-XHR loop freezes the tab for the whole
   run; no button could even be clicked.
3. **No Twin Turbo roll selection.** Every job goes out with empty print
   params, so the printer decides which roll to use.

## Constraints (verified against DYMO Connect Web Service 1.6.1.7)

- The service has **no cancel/abort endpoint**. Full command set:
  StatusConnected, GetPrinters, OpenLabelFile, PrintLabel, PrintLabel2,
  RenderLabel (broken in this build — see the note in `dymo.js`),
  LoadImageAsPngBase64, GetJobStatus, Is550Printer,
  GetConsumableInfoIn550Printer.
- `printLabel2Async()` returns a `PrintJob` with `getJobId()` and
  `getStatus(cb)`; statuses: Unknown 0, Printing 1, Finished 2, Error 3,
  PaperOut 4, InQueue 5, ProcessingError −1, PrinterBusy −2, InvalidJobId −3,
  NotSpooled −4. There is no `getJobStatusAsync` — each status check is a
  brief synchronous request, acceptable when polls are spaced by `setTimeout`.
- `createLabelWriterPrintParamsXml({copies, twinTurboRoll})` builds the
  params; `TwinTurboRoll` = `Auto` | `Left` | `Right`.
- `getPrinters()` exposes `isTwinTurbo` per printer; our wrapper currently
  throws it away.

## Decisions (user-confirmed)

- **Stop = halt + report count.** No resume state, no spooler purge. The
  label in flight completes; message reads "Stopped — N of M printed."
- **Roll selector: Left / Right only, default Left.** No Auto — an explicit
  roll means the printer can never switch rolls mid-run (a re-seek source).
  Persisted per printer. Shown only for Twin Turbo printers.
- **Mid-run fault (PaperOut/Error): stop and report why.** Same shape as the
  Stop button — one consistent way a run ends early.

## Design

### Print engine (`app/src/lib/dymo.js`)

```js
export async function printMerge(printerName, labelXml, records, opts = {})
// opts: { roll: 'Left'|'Right', signal: AbortSignal,
//         onProgress: ({printed, total}) => void }
// returns { printed, total, stopped: boolean, reason: string|null }
```

Loop per record:

1. If `signal.aborted` → return `{stopped: true, reason: null, …}`.
2. `mergeLabel(labelXml, rec)` (unchanged — includes DataRow clearing).
3. `printLabel2Async(printerName, paramsXml, mergedXml, '')` → `PrintJob`.
4. Await job completion via polling (below).
5. `onProgress({printed, total})`; next record.

`paramsXml` is built once per run: for a Twin Turbo printer,
`createLabelWriterPrintParamsXml({copies: 1, twinTurboRoll: roll})`; for any
other printer `''` exactly as today. `roll` defaults to `'Left'`.

**Polling helper** (`awaitJobDone(job, signal)`), poll interval ~150 ms via
`setTimeout`:

| Status | Action |
|---|---|
| Finished | resolve — next label |
| Error / PaperOut / ProcessingError / PrinterBusy | resolve `{fault: reason}` — run ends, reason reported |
| Printing / InQueue | keep polling |
| Unknown / InvalidJobId / NotSpooled | keep polling (transient right after submit), subject to ceiling |
| `getStatus` throws | treat as ProcessingError |

**Hard ceiling: 15 s per label.** If a job never reaches a terminal status,
resolve and continue the run rather than hanging it. A run that can deadlock
on flaky status reporting is worse than one that paces slightly wrong.
`signal.aborted` is also checked at each poll tick so Stop during a slow
label doesn't wait out the ceiling; the in-flight label still completes
physically (no cancel endpoint exists).

`fault` ends the run: returns `{stopped: true, reason: 'Paper out', …}` with
the count of labels that finished.

### Printers API (`app/src/lib/dymo.js`)

`getPrinters()` returns `[{name, isTwinTurbo}]` instead of `[name]`.
Only consumer is the dialog.

### Dialog (`app/src/components/DymoPrintDialog.jsx`)

- **State added:** `progress` (`{printed, total} | null`), `abortRef`
  (`useRef<AbortController>`), `roll` (`'Left' | 'Right'`).
- **Roll selector:** rendered next to the Printer select only when the
  selected printer has `isTwinTurbo`. Two-button toggle (Left / Right)
  matching the existing All/Custom pattern. Default `'Left'`; persisted as
  `localStorage['five12_dymo_roll:<printerName>']`; loaded on printer change.
- **Printer state:** `printers` becomes the object array; `printer` stays a
  name string. `ps.includes(printer)` → `ps.some(p => p.name === printer)`.
- **doPrint:** creates an `AbortController`, passes `signal`, `roll`,
  `onProgress` → `setProgress`. On completion, one message by outcome:
  - completed: `Printed 138 labels.` (existing green banner)
  - stopped: `Stopped — 47 of 138 printed.` (green banner — not an error)
  - fault: `Paper out — stopped after 47 of 138.` (existing red banner)
- **Stop button:** while `busy`, the green Print button is replaced by a red
  **Stop** button that calls `abortRef.current.abort()`. Under it, a live
  line: `Printing 47 of 138…`. The Cancel (close) button stays as-is and is
  disabled while busy — closing mid-run would orphan the run.
- Mapping save after print (existing behavior) runs on completed **and**
  stopped runs — labels were printed either way.

### Out of scope

- Resume-from-N (user chose plain halt).
- Spooler purge via backend.
- The broken RenderLabel preview — separate task already in flight
  (task_77ad2717). **Coordination note:** that task also edits `dymo.js` and
  `DymoPrintDialog.jsx`; whichever lands second rebases.

## Testing (`app/src/lib/dymo.test.js` + dialog test)

Fake framework grows `printLabel2Async` returning a `PrintJob` stub whose
`getStatus(cb)` plays a scripted status sequence per job. Cases:

1. Twin Turbo + roll → `printLabel2Async` params XML contains
   `<TwinTurboRoll>Left</TwinTurboRoll>` (and Right when selected);
   non-TwinTurbo printer → params `''`.
2. **Sequencing:** label N+1 is not submitted until job N reports Finished
   (script: job 1 stays Printing for 3 polls; assert single submission until
   Finished).
3. **Abort between labels:** abort after label 1 finishes → result
   `{printed: 1, stopped: true}`, no further submissions.
4. **PaperOut mid-run** → run ends, `reason` set, count correct.
5. **Status stuck on Unknown** → ceiling fires (fake timers), run continues
   instead of hanging.
6. Existing three tests (no labelSetXml; per-record values; DataRows cleared)
   keep passing with `printLabel2Async`.
7. Dialog: Stop button appears only while busy; stopped outcome renders
   "Stopped — N of M printed."

Existing suite (66 tests) must stay green.

## Verification

Unit suite + `vite build`, then a live 5-label range print on the physical
LabelWriter 450 Twin Turbo: confirm no buzz/skip on labels 2–5, Stop halts
with at most one extra label, and the labels emerge from the selected roll.
