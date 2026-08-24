# DYMO Print Sequencing, Stop, and Twin Turbo Roll Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sequence DYMO label jobs one-at-a-time via `printLabel2` job polling (fixes buzz/misregistration), add a Stop button, and add Twin Turbo Left/Right roll selection.

**Architecture:** `printMerge` in `app/src/lib/dymo.js` becomes an async loop that submits one label via `printLabel2Async`, polls the returned `PrintJob` until `Finished`, then submits the next. An `AbortSignal` stops between labels; job faults (PaperOut/Error) end the run with a reason. `DymoPrintDialog.jsx` drives it with progress state, a Stop button, and a per-printer roll toggle.

**Tech Stack:** React 18, Vitest + Testing Library (jsdom), vendored `dymo.connect.framework.js` (do not edit the vendor file).

**Spec:** `docs/superpowers/specs/2026-08-03-dymo-print-sequencing-design.md`

## Global Constraints

- Poll interval **150 ms**; per-label ceiling **15 000 ms** (ceiling continues the run, never hangs it).
- `PrintJobStatus` numeric codes: Unknown 0, Printing 1, **Finished 2**, Error 3, PaperOut 4, InQueue 5, ProcessingError −1, PrinterBusy −2, InvalidJobId −3, NotSpooled −4.
- Fault reasons (exact copy): `Printer error` (3), `Paper out` (4), `Processing error` (−1), `Printer busy` (−2).
- Roll values: `'Left' | 'Right'` only — **no Auto**. Default `'Left'`.
- localStorage: printer stays `five12_dymo_printer`; roll is `` `five12_dymo_roll:${printerName}` ``.
- Outcome copy (exact): `Printed N labels.` / `Printed 1 label.` · `Stopped — P of T printed.` · `<Reason> — stopped after P of T.`
- The DYMO service has **no cancel endpoint**: Stop halts between labels; the in-flight label always completes.
- Vendor file `app/src/vendor/dymo.connect.framework.js` is never modified.
- All commands run from `C:\dev\Five12-TheApp\app` unless noted. Full suite (`npx vitest run`) must stay green after every task.
- **Coordination:** background task task_77ad2717 (preview fix) also edits `dymo.js` / `DymoPrintDialog.jsx`. Whichever lands second rebases. Do not touch `renderPreview` or its comment block.

## Framework facts (verified against the vendored file — trust these, don't re-derive)

- `f.printLabel2Async(printerName, printParamsXml, labelXml, labelSetXml)` → `Promise<PrintJob>`.
- `PrintJob.getStatus(cb)` → `cb({printerName, jobId, status: number, statusMessage: string})`. Synchronous XHR inside, so space polls with `setTimeout`.
- `f.createLabelWriterPrintParamsXml({copies, twinTurboRoll})` → params XML string.
- `f.getPrinters()` entries: `{printerType, name, modelName, isConnected, isLocal, isTwinTurbo}`.

---

### Task 1: Sequenced print engine in `dymo.js`

**Files:**
- Modify: `app/src/lib/dymo.js` (replace `getPrinters` body and the whole `printMerge`; add module-level helpers above `printMerge`)
- Modify: `app/src/lib/dymo.test.js` (replace `fakeFramework` and the printMerge suite)

**Interfaces:**
- Consumes: `mergeLabel(labelXml, values)` from `./labelMerge` (unchanged).
- Produces (Tasks 2–3 rely on these exact shapes):
  - `getPrinters(): Promise<Array<{name: string, isTwinTurbo: boolean}>>`
  - `printMerge(printerName, labelXml, records, opts?): Promise<{printed: number, total: number, stopped: boolean, reason: string|null}>` where `opts = {roll?: 'Left'|'Right', signal?: AbortSignal, onProgress?: ({printed, total}) => void}`. `roll` present ⇒ Twin Turbo params emitted; `roll` absent ⇒ `printParamsXml` is `''` (the dialog only passes `roll` for Twin Turbo printers).

- [ ] **Step 1: Rewrite `app/src/lib/dymo.test.js` with the job-based fake and the full engine suite**

Replace the entire file with:

```js
import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest'
import { printMerge, getPrinters, resetDymo } from './dymo'

// A DesktopLabel shaped like the real "LZMU Dymo Label Big" template: named text
// objects bound to DataTable columns via DataMappingTextSpan, plus an embedded
// DataTable that already carries rows from whenever the label was authored.
const LABEL_XML = `<?xml version="1.0" encoding="utf-8"?>
<DesktopLabel Version="1">
  <DYMOLabel Version="4">
    <DynamicLayoutManager>
      <LabelObjects>
        <TextObject>
          <Name>Fixture Number</Name>
          <FormattedText>
            <LineTextSpan>
              <DataMappingTextSpan>
                <Text>1401</Text>
                <FontInfo>
                  <FontName>Helvetica</FontName>
                  <FontSize>8.8</FontSize>
                  <IsBold>False</IsBold>
                  <IsItalic>False</IsItalic>
                  <IsUnderline>False</IsUnderline>
                </FontInfo>
                <ColumnName>Fixture ID</ColumnName>
              </DataMappingTextSpan>
            </LineTextSpan>
          </FormattedText>
        </TextObject>
      </LabelObjects>
    </DynamicLayoutManager>
    <DataTable>
      <Columns><DataColumn>Fixture ID</DataColumn></Columns>
      <Rows>
        <DataRow><Value>1401</Value></DataRow>
        <DataRow><Value>1402</Value></DataRow>
      </Rows>
    </DataTable>
  </DYMOLabel>
</DesktopLabel>`

// statusScripts: {submitIndex: [statusCode, ...]} — the last code repeats
// forever. Default script is [2] (Finished on first poll). `events` records
// the interleaving of submits and polls so tests can assert sequencing.
function fakeFramework({ statusScripts = {} } = {}) {
  const events = []
  const printLabel2Async = vi.fn(async (printerName, paramsXml, labelXml, labelSetXml) => {
    const idx = printLabel2Async.mock.calls.length - 1
    const script = statusScripts[idx] ?? [2]
    let poll = 0
    events.push(`submit:${idx}`)
    return {
      getStatus: (cb) => {
        const status = script[Math.min(poll, script.length - 1)]
        poll += 1
        events.push(`status:${idx}:${status}`)
        cb({ printerName, jobId: idx, status, statusMessage: '' })
      },
    }
  })
  window.dymo = { label: { framework: {
    init: (cb) => cb(),
    printLabel2Async,
    createLabelWriterPrintParamsXml: (o) =>
      `<LabelWriterPrintParams><Copies>${o.copies}</Copies><TwinTurboRoll>${o.twinTurboRoll}</TwinTurboRoll></LabelWriterPrintParams>`,
    getPrinters: () => [
      { printerType: 'LabelWriterPrinter', name: 'LW450', isTwinTurbo: true },
      { printerType: 'LabelWriterPrinter', name: 'LW330', isTwinTurbo: false },
      { printerType: 'TapePrinter', name: 'LM500', isTwinTurbo: false },
    ],
  } } }
  return { printLabel2Async, events }
}

const rec = (n) => ({ 'Fixture Number': String(n) })

beforeEach(() => { resetDymo() })
afterEach(() => { vi.useRealTimers() })

describe('getPrinters', () => {
  it('returns LabelWriter printers with their twin-turbo flag', async () => {
    fakeFramework()
    expect(await getPrinters()).toEqual([
      { name: 'LW450', isTwinTurbo: true },
      { name: 'LW330', isTwinTurbo: false },
    ])
  })
})

describe('printMerge', () => {
  it('never sends a labelSetXml — the DYMO service 400s on any non-empty one', async () => {
    const { printLabel2Async } = fakeFramework()
    await printMerge('LW450', LABEL_XML, [rec(601)])
    expect(printLabel2Async).toHaveBeenCalled()
    for (const call of printLabel2Async.mock.calls) expect(call[3]).toBe('')
  })

  it('sends one print job per record, each carrying that record’s values', async () => {
    const { printLabel2Async } = fakeFramework()
    const res = await printMerge('LW450', LABEL_XML, [rec(601), rec(602)])
    expect(printLabel2Async).toHaveBeenCalledTimes(2)
    expect(printLabel2Async.mock.calls[0][2]).toContain('601')
    expect(printLabel2Async.mock.calls[0][2]).not.toContain('602')
    expect(printLabel2Async.mock.calls[1][2]).toContain('602')
    expect(res).toEqual({ printed: 2, total: 2, stopped: false, reason: null })
  })

  it('clears the embedded DataRows so the template cannot drive the label count', async () => {
    const { printLabel2Async } = fakeFramework()
    await printMerge('LW450', LABEL_XML, [rec(601)])
    for (const call of printLabel2Async.mock.calls) {
      expect(call[2]).not.toContain('<DataRow>')
      expect(call[2]).toContain('<DataTable>')
    }
  })

  it('emits TwinTurboRoll print params when a roll is given, empty params otherwise', async () => {
    const { printLabel2Async } = fakeFramework()
    await printMerge('LW450', LABEL_XML, [rec(601)], { roll: 'Right' })
    expect(printLabel2Async.mock.calls[0][1]).toContain('<TwinTurboRoll>Right</TwinTurboRoll>')
    expect(printLabel2Async.mock.calls[0][1]).toContain('<Copies>1</Copies>')
    await printMerge('LW330', LABEL_XML, [rec(602)])
    expect(printLabel2Async.mock.calls[1][1]).toBe('')
  })

  it('does not submit label N+1 until job N reports Finished', async () => {
    vi.useFakeTimers()
    // job 0: Printing, Printing, then Finished — three polls before the next submit
    const { events } = fakeFramework({ statusScripts: { 0: [1, 1, 2] } })
    const p = printMerge('LW450', LABEL_XML, [rec(601), rec(602)])
    await vi.advanceTimersByTimeAsync(5000)
    const res = await p
    expect(res).toEqual({ printed: 2, total: 2, stopped: false, reason: null })
    expect(events).toEqual([
      'submit:0', 'status:0:1', 'status:0:1', 'status:0:2',
      'submit:1', 'status:1:2',
    ])
  })

  it('abort between labels stops the run and reports the count', async () => {
    const { printLabel2Async } = fakeFramework()
    const ac = new AbortController()
    const seen = []
    const res = await printMerge('LW450', LABEL_XML, [rec(601), rec(602), rec(603)], {
      signal: ac.signal,
      onProgress: (p) => { seen.push(p); if (p.printed === 1) ac.abort() },
    })
    expect(res).toEqual({ printed: 1, total: 3, stopped: true, reason: null })
    expect(printLabel2Async).toHaveBeenCalledTimes(1)
    expect(seen).toEqual([{ printed: 1, total: 3 }])
  })

  it('a PaperOut mid-run ends the run with the reason and the finished count', async () => {
    const { printLabel2Async } = fakeFramework({ statusScripts: { 1: [4] } })
    const res = await printMerge('LW450', LABEL_XML, [rec(601), rec(602), rec(603)])
    expect(res).toEqual({ printed: 1, total: 3, stopped: true, reason: 'Paper out' })
    expect(printLabel2Async).toHaveBeenCalledTimes(2) // the faulted label is not retried
  })

  it('a job stuck on Unknown hits the 15s ceiling and the run continues instead of hanging', async () => {
    vi.useFakeTimers()
    const { printLabel2Async } = fakeFramework({ statusScripts: { 0: [0] } })
    const p = printMerge('LW450', LABEL_XML, [rec(601), rec(602)])
    await vi.advanceTimersByTimeAsync(40000)
    const res = await p
    expect(res).toEqual({ printed: 2, total: 2, stopped: false, reason: null })
    expect(printLabel2Async).toHaveBeenCalledTimes(2)
  })
})
```

- [ ] **Step 2: Run the suite to verify the new tests fail**

Run: `npx vitest run src/lib/dymo.test.js`
Expected: FAIL — `printLabel2Async` is never called (current code calls `printLabel`), `getPrinters` returns strings not objects, `printMerge` returns `undefined` not a result object.

- [ ] **Step 3: Implement the engine in `app/src/lib/dymo.js`**

Replace the current `getPrinters` (lines ~55–60) with:

```js
export async function getPrinters() {
  const f = await fw();
  return f.getPrinters()
    .filter((p) => p.printerType === 'LabelWriterPrinter')
    .map((p) => ({ name: p.name, isTwinTurbo: !!p.isTwinTurbo }));
}
```

Replace the whole `printMerge` (and its comment block) with:

```js
// One printLabel2 job per record, strictly sequenced: submit a label, poll its
// job until the printer says Finished, only then submit the next. The service
// returns from PrintLabel as soon as it ACCEPTS a job — not when the label
// finishes feeding — so firing jobs back-to-back makes the LabelWriter start a
// new job mid-feed and re-seek the label gap (the "buzz"/misregistration).
// Batching alternatives are ruled out by evidence: the service 400s on any
// non-empty labelSetXml (see labelMerge.js), and physical tests show the
// embedded DataTable never drives the label count.
//
// opts.roll ('Left'|'Right') is passed only for Twin Turbo printers — it pins
// the roll via LabelWriterPrintParams. opts.signal stops the run between
// labels (the service has no cancel endpoint, so the label in flight always
// completes). opts.onProgress fires after each label finishes.
const JOB_POLL_MS = 150;
const JOB_CEILING_MS = 15000;
const STATUS_FINISHED = 2; // dymo.label.framework.PrintJobStatus
const FAULT_REASONS = {
  3: 'Printer error',
  4: 'Paper out',
  [-1]: 'Processing error',
  [-2]: 'Printer busy',
};

const sleep = (ms) => new Promise((res) => setTimeout(res, ms));

// Resolve {fault: string|null} for one PrintJob. Finished → null fault.
// Error/PaperOut/ProcessingError/PrinterBusy → that reason. Printing/InQueue
// keep polling; Unknown/InvalidJobId/NotSpooled also keep polling (they appear
// transiently right after submit) — but the ceiling bounds the wait so a
// printer with unreliable status reporting paces the run instead of hanging
// it. An abort stops the WAIT (not the label) so Stop needn't outlast a slow
// label; the caller counts the label as printed either way.
async function awaitJobDone(job, signal) {
  const deadline = Date.now() + JOB_CEILING_MS;
  for (;;) {
    const info = await new Promise((res) => {
      try { job.getStatus(res); } catch (e) { res({ status: -1, statusMessage: String(e) }); }
    });
    const status = info ? info.status : 0;
    if (status === STATUS_FINISHED) return { fault: null };
    if (FAULT_REASONS[status] !== undefined) return { fault: FAULT_REASONS[status] };
    if (signal?.aborted) return { fault: null };
    if (Date.now() >= deadline) return { fault: null };
    await sleep(JOB_POLL_MS);
  }
}

export async function printMerge(printerName, labelXml, records, opts = {}) {
  const { roll, signal, onProgress } = opts;
  const f = await fw();
  const paramsXml = roll
    ? f.createLabelWriterPrintParamsXml({ copies: 1, twinTurboRoll: roll })
    : '';
  const total = records.length;
  let printed = 0;
  for (const rec of records) {
    if (signal?.aborted) return { printed, total, stopped: true, reason: null };
    const job = await f.printLabel2Async(printerName, paramsXml, mergeLabel(labelXml, rec), '');
    const { fault } = await awaitJobDone(job, signal);
    if (fault) return { printed, total, stopped: true, reason: fault };
    printed += 1;
    if (onProgress) onProgress({ printed, total });
  }
  return { printed, total, stopped: false, reason: null };
}
```

Leave `renderPreview` and everything above it untouched.

- [ ] **Step 4: Run the suite to verify it passes**

Run: `npx vitest run src/lib/dymo.test.js`
Expected: PASS — 9 tests.

Note: the abort test relies on `onProgress` firing synchronously inside the loop; the sequencing test relies on the events array ordering. If the sequencing test flakes on timing, increase the `advanceTimersByTimeAsync` value — never poll faster.

- [ ] **Step 5: Run the full suite and build**

Run: `npx vitest run && npx vite build`
Expected: all files pass (Task 2 fixes the dialog's consumption of `getPrinters` — until then `DymoPrintDialog` has a latent mismatch but no test covers it, so the suite stays green; the build has no type checking and passes).

- [ ] **Step 6: Commit**

```bash
git add src/lib/dymo.js src/lib/dymo.test.js
git commit -m "feat(dymo): sequence print jobs via printLabel2 status polling

One label in flight at a time — submit, poll GetJobStatus to Finished,
then next. Fixes the buzz/misregistration: the service ACKs PrintLabel on
acceptance, not completion, so back-to-back jobs made the printer re-seek
the gap mid-feed. Adds AbortSignal stop-between-labels, fault reporting
(paper out / error), a 15s per-label ceiling so flaky status can't hang a
run, and TwinTurboRoll print params. getPrinters() now returns
{name, isTwinTurbo}.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Roll selector and printer objects in the dialog

**Files:**
- Modify: `app/src/components/DymoPrintDialog.jsx`
- Create: `app/src/components/DymoPrintDialog.test.jsx`

**Interfaces:**
- Consumes: `getPrinters(): Promise<[{name, isTwinTurbo}]>` from Task 1.
- Produces: state `roll` (`'Left' | 'Right'`) and `selectedPrinter` (`{name, isTwinTurbo} | undefined`) that Task 3's `doPrint` reads. localStorage key `` `five12_dymo_roll:${printer}` ``.

- [ ] **Step 1: Write the failing dialog test**

Create `app/src/components/DymoPrintDialog.test.jsx`:

```jsx
import { describe, expect, it, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import DymoPrintDialog from './DymoPrintDialog'
import { printMerge } from '../lib/dymo'

vi.mock('../lib/dymo', () => ({
  dymoReady: vi.fn(async () => true),
  getPrinters: vi.fn(async () => [
    { name: 'LW450', isTwinTurbo: true },
    { name: 'LW330', isTwinTurbo: false },
  ]),
  renderPreview: vi.fn(async () => null),
  printMerge: vi.fn(async () => ({ printed: 0, total: 0, stopped: false, reason: null })),
}))

const TPL = {
  id: 1, name: 'Big Label', variables: ['Universe'], savedMappings: {},
  labelXml: '<DesktopLabel/>', createdAt: '2026-07-23T00:00:00Z',
}

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  global.fetch = vi.fn(async (url) => ({
    ok: true,
    text: async () => {
      const u = String(url)
      if (u === '/api/dymo-templates') return JSON.stringify([TPL])
      if (u.startsWith('/api/dymo-templates/1/mapping')) return JSON.stringify(TPL)
      if (u.startsWith('/api/dymo-templates/1')) return JSON.stringify(TPL)
      if (u.startsWith('/api/dymo-csv-sources')) return JSON.stringify([])
      return '{}'
    },
  }))
})

const ROWS = [{ universe: '1' }, { universe: '2' }]

async function openWithTemplate() {
  render(<DymoPrintDialog patchRows={ROWS} selectedRows={[]} onClose={() => {}} />)
  const tplSelect = await screen.findByLabelText('Template')
  await userEvent.selectOptions(tplSelect, '1')
  await screen.findByText('Universe') // mapping table rendered
}

describe('DymoPrintDialog roll selector', () => {
  it('shows Left/Right for a Twin Turbo printer, defaults Left, persists per printer', async () => {
    await openWithTemplate()
    const left = await screen.findByRole('button', { name: 'Left' })
    const right = screen.getByRole('button', { name: 'Right' })
    expect(left.className).toContain('border-brand')   // selected style
    await userEvent.click(right)
    expect(localStorage.getItem('five12_dymo_roll:LW450')).toBe('Right')
  })

  it('hides the roll selector for a non-Twin-Turbo printer', async () => {
    await openWithTemplate()
    await userEvent.selectOptions(screen.getByLabelText('Printer'), 'LW330')
    expect(screen.queryByRole('button', { name: 'Left' })).toBeNull()
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run src/components/DymoPrintDialog.test.jsx`
Expected: FAIL — no `Left` button exists; additionally the printer select breaks because the dialog still treats printers as strings.

- [ ] **Step 3: Implement in `DymoPrintDialog.jsx`**

3a. Add state after the `printer` state line:

```jsx
const [roll, setRoll] = useState('Left');               // TwinTurbo roll, per printer
```

3b. In `probe()`, printers are now objects — change the reset check:

```jsx
const probe = async () => {
  setReady(null);
  const ok = await dymoReady();
  setReady(ok);
  if (ok) {
    try {
      const ps = await getPrinters();
      setPrinters(ps);
      if (ps.length && !ps.some(p => p.name === printer)) setPrinter(ps[0].name);
    } catch { setPrinters([]); }
  }
};
```

3c. Add below `probe`'s useEffect — selected printer + per-printer roll recall:

```jsx
const selectedPrinter = printers.find(p => p.name === printer);
useEffect(() => {
  if (printer) setRoll(localStorage.getItem(`five12_dymo_roll:${printer}`) || 'Left');
}, [printer]);
const pickRoll = (r) => {
  setRoll(r);
  localStorage.setItem(`five12_dymo_roll:${printer}`, r);
};
```

3d. The printer `<select>` options map over objects now:

```jsx
{printers.length === 0 && <option value="">none found</option>}
{printers.map(p => <option key={p.name} value={p.name}>{p.name}</option>)}
```

3e. Immediately after the Printer `<label>` closes, add the roll toggle (same two-button pattern as All/Custom):

```jsx
{selectedPrinter?.isTwinTurbo && (
  <div className="flex items-center gap-2 text-sm">
    <span className="text-text-muted">Roll</span>
    <button type="button" onClick={() => pickRoll('Left')}
      className={`px-3 py-1.5 rounded border ${roll==='Left' ? 'border-brand text-brand-hi' : 'border-border text-text-muted'}`}>Left</button>
    <button type="button" onClick={() => pickRoll('Right')}
      className={`px-3 py-1.5 rounded border ${roll==='Right' ? 'border-brand text-brand-hi' : 'border-border text-text-muted'}`}>Right</button>
  </div>
)}
```

- [ ] **Step 4: Run the dialog tests to verify they pass**

Run: `npx vitest run src/components/DymoPrintDialog.test.jsx`
Expected: PASS — 2 tests.

- [ ] **Step 5: Full suite**

Run: `npx vitest run`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/components/DymoPrintDialog.jsx src/components/DymoPrintDialog.test.jsx
git commit -m "feat(dymo): Twin Turbo roll selector — Left/Right, per-printer memory

getPrinters() now yields {name, isTwinTurbo}; the dialog shows a Left/Right
toggle only for Twin Turbo printers (no Auto — an explicit roll means the
printer can never switch rolls mid-run, one source of gap re-seek).
Defaults Left, remembered per printer in localStorage.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Progress, Stop button, and outcome messages

**Files:**
- Modify: `app/src/components/DymoPrintDialog.jsx` (state, `doPrint`, footer buttons)
- Modify: `app/src/components/DymoPrintDialog.test.jsx` (add the run-control suite)

**Interfaces:**
- Consumes: `printMerge(printer, labelXml, records, {roll?, signal, onProgress})` → `{printed, total, stopped, reason}` from Task 1; `roll`/`selectedPrinter` from Task 2.
- Produces: nothing further — terminal UI task.

- [ ] **Step 1: Add the failing run-control tests**

Append to `DymoPrintDialog.test.jsx`:

```jsx
describe('DymoPrintDialog run control', () => {
  it('swaps Print for Stop while running, aborts on click, reports a stopped run', async () => {
    let resolvePrint
    printMerge.mockReturnValue(new Promise((res) => { resolvePrint = res }))
    await openWithTemplate()
    await userEvent.click(await screen.findByRole('button', { name: /Print all 2/ }))

    const stop = await screen.findByRole('button', { name: 'Stop' })
    expect(screen.queryByRole('button', { name: /Print all/ })).toBeNull()
    expect(screen.getByText('Printing 1 of 2…')).toBeInTheDocument()

    const opts = printMerge.mock.calls[0][3]
    expect(opts.roll).toBe('Left')            // twin turbo default from Task 2
    expect(opts.signal.aborted).toBe(false)
    await userEvent.click(stop)
    expect(opts.signal.aborted).toBe(true)

    resolvePrint({ printed: 1, total: 2, stopped: true, reason: null })
    await screen.findByText('Stopped — 1 of 2 printed.')
    expect(screen.getByRole('button', { name: /Print all 2/ })).toBeInTheDocument()
  })

  it('reports a fault with reason and count', async () => {
    printMerge.mockResolvedValue({ printed: 1, total: 2, stopped: true, reason: 'Paper out' })
    await openWithTemplate()
    await userEvent.click(await screen.findByRole('button', { name: /Print all 2/ }))
    await screen.findByText('Paper out — stopped after 1 of 2.')
  })

  it('reports a completed run and passes no roll for a non-Twin-Turbo printer', async () => {
    printMerge.mockResolvedValue({ printed: 2, total: 2, stopped: false, reason: null })
    await openWithTemplate()
    await userEvent.selectOptions(screen.getByLabelText('Printer'), 'LW330')
    await userEvent.click(await screen.findByRole('button', { name: /Print all 2/ }))
    await screen.findByText('Printed 2 labels.')
    expect(printMerge.mock.calls[0][3].roll).toBeUndefined()
  })

  it('disables closing while a run is active', async () => {
    let resolvePrint
    printMerge.mockReturnValue(new Promise((res) => { resolvePrint = res }))
    await openWithTemplate()
    await userEvent.click(await screen.findByRole('button', { name: /Print all 2/ }))
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled()
    resolvePrint({ printed: 2, total: 2, stopped: false, reason: null })
    await screen.findByText('Printed 2 labels.')
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeEnabled()
  })
})
```

- [ ] **Step 2: Run to verify they fail**

Run: `npx vitest run src/components/DymoPrintDialog.test.jsx`
Expected: FAIL — no Stop button, no progress line, `doPrint` still awaits the old signature and writes `Printed N label(s).` unconditionally.

- [ ] **Step 3: Implement**

3a. Imports and state — add `useRef` to the React import; add after `roll` state:

```jsx
const [progress, setProgress] = useState(null);   // {printed, total} while running
const abortRef = useRef(null);
```

3b. Replace `doPrint` entirely:

```jsx
const doPrint = async () => {
  if (printList.length > 200 &&
      !window.confirm(`Print ${printList.length} labels?`)) return;
  setBusy(true); setError(null); setPrintedMsg(null);
  setProgress({ printed: 0, total: printList.length });
  const ac = new AbortController();
  abortRef.current = ac;
  try {
    const res = await printMerge(printer, tpl.labelXml, printList, {
      roll: selectedPrinter?.isTwinTurbo ? roll : undefined,
      signal: ac.signal,
      onProgress: setProgress,
    });
    localStorage.setItem(LAST_PRINTER_KEY, printer);
    if (res.printed > 0) {
      // labels came out — worth remembering the mapping even on a stopped run
      try {
        const srcKey = source === 'csv' ? 'csv' : 'patch';
        await fetch(`/api/dymo-templates/${tpl.id}/mapping`, {
          method: 'PUT', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source: srcKey, mapping }) }).then(readJson);
      } catch (e) {
        console.warn('mapping save failed (labels already printed):', e);
      }
    }
    if (res.reason) {
      setError(`${res.reason} — stopped after ${res.printed} of ${res.total}.`);
    } else if (res.stopped) {
      setPrintedMsg(`Stopped — ${res.printed} of ${res.total} printed.`);
    } else {
      setPrintedMsg(`Printed ${res.total} label${res.total === 1 ? '' : 's'}.`);
    }
  } catch (e) { setError(e.message); }
  finally { setBusy(false); setProgress(null); abortRef.current = null; }
};
```

3c. Footer — replace the closing button row (`Cancel` + print button):

```jsx
<div className="flex items-center gap-3">
  {busy && progress && (
    <span className="text-sm text-text-muted">
      Printing {Math.min(progress.printed + 1, progress.total)} of {progress.total}…
    </span>
  )}
  <button onClick={onClose} disabled={busy}
    className="px-4 py-2 bg-surface-2 hover:bg-border rounded text-sm disabled:opacity-40">Cancel</button>
  {busy ? (
    <button onClick={() => abortRef.current?.abort()}
      className="px-4 py-2 bg-brand-dim/40 border border-brand/40 text-brand-hi hover:bg-brand-dim/60 rounded text-sm font-medium">
      Stop
    </button>
  ) : (
    <button onClick={doPrint}
      disabled={!tpl || !printer || printList.length === 0 || ready !== true}
      className="px-4 py-2 bg-online hover:brightness-110 text-bg rounded text-sm font-medium disabled:opacity-40">
      {scopeMode === 'all' ? `Print all ${records.length}` : `Print ${printList.length} labels`}
    </button>
  )}
</div>
```

3d. Disable the header `×` close button while busy:

```jsx
<button onClick={onClose} disabled={busy}
  className="text-text-muted hover:text-text text-lg leading-none disabled:opacity-40">×</button>
```

- [ ] **Step 4: Run the dialog tests to verify they pass**

Run: `npx vitest run src/components/DymoPrintDialog.test.jsx`
Expected: PASS — 6 tests.

- [ ] **Step 5: Full suite + build**

Run: `npx vitest run && npx vite build`
Expected: all green, build succeeds.

- [ ] **Step 6: Commit**

```bash
git add src/components/DymoPrintDialog.jsx src/components/DymoPrintDialog.test.jsx
git commit -m "feat(dymo): Stop button, live progress, honest run outcomes

While a run is active the Print button becomes Stop and a 'Printing N of
M…' line tracks the sequenced jobs. Stop aborts between labels (at most
one more emerges — the service has no cancel endpoint) and reports
'Stopped — P of T printed.'; a printer fault reports its reason the same
way. Closing the dialog is disabled mid-run; the column mapping still
persists whenever any labels came out.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Physical verification on the LabelWriter 450 Twin Turbo

No code. Run the app (`npm run dev` in `app/`, backend already on :5000) and with the real printer:

- [ ] Print a 5-label Custom range → labels 2–5 register cleanly, **no buzz/skip**.
- [ ] Start a longer run, press Stop mid-run → run halts with at most one extra label; message shows the correct count.
- [ ] Print with Roll = Left, then Roll = Right → labels emerge from the chosen roll.
- [ ] Pop the label roll out (or run one side empty) mid-run → "Paper out — stopped after P of T." appears.

If the buzz persists even with sequencing, that is new information — record the observation in the spec before changing approach (the next lever would be pacing between Finished and the next submit, not batching).
