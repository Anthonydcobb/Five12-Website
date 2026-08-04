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

// Fake vendored framework: printLabelAsync just records the submission (its
// return value is unused — see the amendment: PrintLabel2's "job id" was
// never usable, and printLabelAsync's isn't either). `events` records
// submissions so tests can assert sequencing against the queue-poll mock.
function fakeFramework() {
  const events = []
  const printLabelAsync = vi.fn(async (printerName, paramsXml, labelXml, labelSetXml) => {
    const idx = printLabelAsync.mock.calls.length - 1
    events.push(`submit:${idx}`)
    return true
  })
  window.dymo = { label: { framework: {
    init: (cb) => cb(),
    printLabelAsync,
    createLabelWriterPrintParamsXml: (o) =>
      `<LabelWriterPrintParams><Copies>${o.copies}</Copies><TwinTurboRoll>${o.twinTurboRoll}</TwinTurboRoll></LabelWriterPrintParams>`,
    getPrinters: () => [
      { printerType: 'LabelWriterPrinter', name: 'LW450', isTwinTurbo: true },
      { printerType: 'LabelWriterPrinter', name: 'LW330', isTwinTurbo: false },
      { printerType: 'TapePrinter', name: 'LM500', isTwinTurbo: false },
    ],
  } } }
  return { printLabelAsync, events }
}

// Scripts the backend's /api/print-queue responses. `scripts`: {submitIndex:
// [queueState, ...]} — states are consumed one per poll (appear and drain
// share the same list) for that submission; the last one repeats. A
// submission with no script gets the default: appears on the first poll,
// drains on the second — fast, no real waiting needed.
const DEFAULT_SCRIPT = [
  { jobCount: 1, printerStatus: '', jobs: [] },
  { jobCount: 0, printerStatus: '', jobs: [] },
]

function fakeQueue(printLabelAsync, events, scripts = {}) {
  const pollCounts = {}
  global.fetch = vi.fn(async (url) => {
    const idx = printLabelAsync.mock.calls.length - 1
    const script = scripts[idx] ?? DEFAULT_SCRIPT
    const poll = pollCounts[idx] ?? 0
    pollCounts[idx] = poll + 1
    const state = script[Math.min(poll, script.length - 1)]
    events.push(`poll:${idx}:${poll}:jobCount=${state.jobCount}` +
      (state.printerStatus ? `:${state.printerStatus}` : ''))
    return { ok: true, status: 200, json: async () => state, url }
  })
  return global.fetch
}

const rec = (n) => ({ 'Fixture Number': String(n) })

beforeEach(() => { resetDymo() })
afterEach(() => { vi.useRealTimers(); delete global.fetch })

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
    const { printLabelAsync, events } = fakeFramework()
    fakeQueue(printLabelAsync, events)
    await printMerge('LW450', LABEL_XML, [rec(601)])
    expect(printLabelAsync).toHaveBeenCalled()
    for (const call of printLabelAsync.mock.calls) expect(call[3]).toBe('')
  })

  it('sends one print job per record, each carrying that record\'s values', async () => {
    const { printLabelAsync, events } = fakeFramework()
    fakeQueue(printLabelAsync, events)
    const res = await printMerge('LW450', LABEL_XML, [rec(601), rec(602)])
    expect(printLabelAsync).toHaveBeenCalledTimes(2)
    expect(printLabelAsync.mock.calls[0][2]).toContain('601')
    expect(printLabelAsync.mock.calls[0][2]).not.toContain('602')
    expect(printLabelAsync.mock.calls[1][2]).toContain('602')
    expect(res).toEqual({ printed: 2, total: 2, stopped: false, reason: null })
  })

  it('clears the embedded DataRows so the template cannot drive the label count', async () => {
    const { printLabelAsync, events } = fakeFramework()
    fakeQueue(printLabelAsync, events)
    await printMerge('LW450', LABEL_XML, [rec(601)])
    for (const call of printLabelAsync.mock.calls) {
      expect(call[2]).not.toContain('<DataRow>')
      expect(call[2]).toContain('<DataTable>')
    }
  })

  it('emits TwinTurboRoll print params when a roll is given, empty params otherwise', async () => {
    const { printLabelAsync, events } = fakeFramework()
    fakeQueue(printLabelAsync, events)
    await printMerge('LW450', LABEL_XML, [rec(601)], { roll: 'Right' })
    expect(printLabelAsync.mock.calls[0][1]).toContain('<TwinTurboRoll>Right</TwinTurboRoll>')
    expect(printLabelAsync.mock.calls[0][1]).toContain('<Copies>1</Copies>')
    await printMerge('LW330', LABEL_XML, [rec(602)])
    expect(printLabelAsync.mock.calls[1][1]).toBe('')
  })

  it('polls the backend queue endpoint for the given printer, URL-encoded', async () => {
    const { printLabelAsync, events } = fakeFramework()
    fakeQueue(printLabelAsync, events)
    await printMerge('DYMO LabelWriter 450 Twin Turbo', LABEL_XML, [rec(601)])
    expect(global.fetch).toHaveBeenCalledWith(
      '/api/print-queue?printer=DYMO%20LabelWriter%20450%20Twin%20Turbo')
  })

  it('does not submit label N+1 until label N\'s queue has drained', async () => {
    vi.useFakeTimers()
    // label 0: appears immediately, then stays queued for two more polls
    // before draining — proves the run waits rather than firing back-to-back.
    const { printLabelAsync, events } = fakeFramework()
    fakeQueue(printLabelAsync, events, {
      0: [
        { jobCount: 1, printerStatus: '', jobs: [] },
        { jobCount: 1, printerStatus: '', jobs: [] },
        { jobCount: 1, printerStatus: '', jobs: [] },
        { jobCount: 0, printerStatus: '', jobs: [] },
      ],
    })
    const p = printMerge('LW450', LABEL_XML, [rec(601), rec(602)])
    await vi.advanceTimersByTimeAsync(5000)
    const res = await p
    expect(res).toEqual({ printed: 2, total: 2, stopped: false, reason: null })
    expect(events).toEqual([
      'submit:0',
      'poll:0:0:jobCount=1', 'poll:0:1:jobCount=1', 'poll:0:2:jobCount=1', 'poll:0:3:jobCount=0',
      'submit:1',
      'poll:1:0:jobCount=1', 'poll:1:1:jobCount=0',
    ])
  })

  it('abort between labels stops the run and reports the count', async () => {
    const { printLabelAsync, events } = fakeFramework()
    fakeQueue(printLabelAsync, events)
    const ac = new AbortController()
    const seen = []
    const res = await printMerge('LW450', LABEL_XML, [rec(601), rec(602), rec(603)], {
      signal: ac.signal,
      onProgress: (p) => { seen.push(p); if (p.printed === 1) ac.abort() },
    })
    expect(res).toEqual({ printed: 1, total: 3, stopped: true, reason: null })
    expect(printLabelAsync).toHaveBeenCalledTimes(1)
    expect(seen).toEqual([{ printed: 1, total: 3 }])
  })

  it("abort during a label's queue wait counts that label and stops before the next", async () => {
    vi.useFakeTimers()
    // job 0's queue never drains — the abort lands mid-wait, not between labels
    const { printLabelAsync, events } = fakeFramework()
    fakeQueue(printLabelAsync, events, {
      0: [{ jobCount: 1, printerStatus: '', jobs: [] }],
    })
    const ac = new AbortController()
    const p = printMerge('LW450', LABEL_XML, [rec(601), rec(602)], { signal: ac.signal })
    await vi.advanceTimersByTimeAsync(900) // several polls, queue still non-empty
    ac.abort()
    await vi.advanceTimersByTimeAsync(500) // the next poll tick observes the abort
    const res = await p
    // the in-flight label completes physically (no cancel endpoint) so it COUNTS;
    // label 2 must never be submitted
    expect(res).toEqual({ printed: 1, total: 2, stopped: true, reason: null })
    expect(printLabelAsync).toHaveBeenCalledTimes(1)
  })

  it('a fault mid-run ends the run with the reason and the finished count', async () => {
    const { printLabelAsync, events } = fakeFramework()
    fakeQueue(printLabelAsync, events, {
      1: [{ jobCount: 1, printerStatus: 'PaperOut', jobs: [] }],
    })
    const res = await printMerge('LW450', LABEL_XML, [rec(601), rec(602), rec(603)])
    expect(res).toEqual({ printed: 1, total: 3, stopped: true, reason: 'Paper out' })
    expect(printLabelAsync).toHaveBeenCalledTimes(2) // the faulted label is not retried
  })

  it('a queue stuck non-empty hits the 15s ceiling and the run continues instead of hanging', async () => {
    vi.useFakeTimers()
    const { printLabelAsync, events } = fakeFramework()
    fakeQueue(printLabelAsync, events, {
      0: [{ jobCount: 1, printerStatus: '', jobs: [] }], // never drains
    })
    const p = printMerge('LW450', LABEL_XML, [rec(601), rec(602)])
    await vi.advanceTimersByTimeAsync(40000)
    const res = await p
    expect(res).toEqual({ printed: 2, total: 2, stopped: false, reason: null })
    expect(printLabelAsync).toHaveBeenCalledTimes(2)
  })

  it('a transient fetch failure keeps polling instead of ending the run', async () => {
    vi.useFakeTimers()
    const { printLabelAsync, events } = fakeFramework()
    let call = 0
    global.fetch = vi.fn(async () => {
      call += 1
      events.push(`poll:${call}`)
      if (call <= 2) throw new Error('network blip')
      return { ok: true, status: 200, json: async () => ({ jobCount: 0, printerStatus: '', jobs: [] }) }
    })
    const p = printMerge('LW450', LABEL_XML, [rec(601)])
    await vi.advanceTimersByTimeAsync(5000)
    const res = await p
    expect(res).toEqual({ printed: 1, total: 1, stopped: false, reason: null })
  })

  it('maps each fault source to its exact reason copy', async () => {
    const cases = [
      // printerStatus containing PaperOut/PaperProblem/PaperJam → 'Paper out'
      [{ jobCount: 1, printerStatus: 'PaperOut', jobs: [] }, 'Paper out'],
      [{ jobCount: 1, printerStatus: 'PaperJam', jobs: [] }, 'Paper out'],
      // printerStatus containing Error/Offline → 'Printer error'
      [{ jobCount: 1, printerStatus: 'Error', jobs: [] }, 'Printer error'],
      [{ jobCount: 1, printerStatus: 'Offline', jobs: [] }, 'Printer error'],
      // any job status containing 'Error' → 'Printer error'
      [{ jobCount: 1, printerStatus: '', jobs: [{ id: 1, status: 'PrintingError' }] }, 'Printer error'],
      // A paper-out can surface on the JOB while Get-Printer still says Normal:
      // Windows PrintJobStatus is a flags enum whose ToString() names PaperOut,
      // Offline, Blocked. Missing these fed the rest of a run into an empty
      // printer and still reported success.
      [{ jobCount: 1, printerStatus: 'Normal', jobs: [{ id: 1, status: 'PaperOut' }] }, 'Paper out'],
      [{ jobCount: 1, printerStatus: 'Normal', jobs: [{ id: 1, status: 'Printing, PaperOut' }] }, 'Paper out'],
      [{ jobCount: 1, printerStatus: 'Normal', jobs: [{ id: 1, status: 'Offline' }] }, 'Printer error'],
      // paper beats error when a job reports both — the operator needs the
      // actionable one
      [{ jobCount: 1, printerStatus: '', jobs: [{ id: 1, status: 'Error, PaperOut' }] }, 'Paper out'],
    ]
    for (const [state, reason] of cases) {
      resetDymo() // drop the cached framework so the new fake is picked up
      const { printLabelAsync, events } = fakeFramework()
      fakeQueue(printLabelAsync, events, { 0: [state] })
      const res = await printMerge('LW450', LABEL_XML, [rec(601)])
      expect(res).toEqual({ printed: 0, total: 1, stopped: true, reason })
    }
  })

  it('a healthy in-flight job status does not fault the run', async () => {
    // guards the job-status regexes against over-matching: 'Printing' must not
    // trip the paper or error branch, or every normal run would abort
    const { printLabelAsync, events } = fakeFramework()
    fakeQueue(printLabelAsync, events, {
      0: [
        { jobCount: 1, printerStatus: 'Normal', jobs: [{ id: 1, status: 'Printing' }] },
        { jobCount: 0, printerStatus: 'Normal', jobs: [] },
      ],
    })
    const res = await printMerge('LW450', LABEL_XML, [rec(601)])
    expect(res).toEqual({ printed: 1, total: 1, stopped: false, reason: null })
  })
})
