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

  it('sends one print job per record, each carrying that record\'s values', async () => {
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

  it("abort during a label's wait counts that label and stops before the next", async () => {
    vi.useFakeTimers()
    // job 0 reports Printing forever — the abort lands mid-wait, not between labels
    const { printLabel2Async } = fakeFramework({ statusScripts: { 0: [1] } })
    const ac = new AbortController()
    const p = printMerge('LW450', LABEL_XML, [rec(601), rec(602)], { signal: ac.signal })
    await vi.advanceTimersByTimeAsync(450)   // several polls, job 0 still Printing
    ac.abort()
    await vi.advanceTimersByTimeAsync(300)   // the next poll tick observes the abort
    const res = await p
    // the in-flight label completes physically (no cancel endpoint) so it COUNTS;
    // label 2 must never be submitted
    expect(res).toEqual({ printed: 1, total: 2, stopped: true, reason: null })
    expect(printLabel2Async).toHaveBeenCalledTimes(1)
  })

  it('maps each fault status to its exact reason copy', async () => {
    for (const [code, reason] of [[3, 'Printer error'], [-1, 'Processing error'], [-2, 'Printer busy']]) {
      resetDymo()  // drop the cached framework so the new fake is picked up
      fakeFramework({ statusScripts: { 0: [code] } })
      const res = await printMerge('LW450', LABEL_XML, [rec(601)])
      expect(res).toEqual({ printed: 0, total: 1, stopped: true, reason })
    }
  })
})
