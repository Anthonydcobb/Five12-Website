import { describe, expect, it, beforeEach, vi } from 'vitest'
import { printMerge, resetDymo } from './dymo'

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

function fakeFramework() {
  const printLabel = vi.fn()
  window.dymo = { label: { framework: { init: (cb) => cb(), printLabel } } }
  return printLabel
}

beforeEach(() => { resetDymo() })

describe('printMerge', () => {
  it('never sends a labelSetXml — the DYMO service 400s on any non-empty one', async () => {
    // DYMO Connect Web Service 1.6.1.7 answers PrintLabel/PrintLabel2 with
    // HTTP 400 "Error printing label. Exception: " for ANY non-empty
    // labelSetXml on a DesktopLabel, whatever its shape. Verified against the
    // live service; the identical request with '' returns 200.
    const printLabel = fakeFramework()
    await printMerge('LW450', LABEL_XML, [{ 'Fixture Number': '601' }])
    expect(printLabel).toHaveBeenCalled()
    for (const call of printLabel.mock.calls) expect(call[3]).toBe('')
  })

  it('sends one print job per record, each carrying that record’s values', async () => {
    const printLabel = fakeFramework()
    await printMerge('LW450', LABEL_XML, [
      { 'Fixture Number': '601' },
      { 'Fixture Number': '602' },
    ])
    expect(printLabel).toHaveBeenCalledTimes(2)
    expect(printLabel.mock.calls[0][2]).toContain('601')
    expect(printLabel.mock.calls[0][2]).not.toContain('602')
    expect(printLabel.mock.calls[1][2]).toContain('602')
  })

  it('clears the embedded DataRows so the template cannot drive the label count', async () => {
    // The stored template ships 98 DataRows. Left in place they are a second,
    // invisible source of "how many labels come out" on top of our records.
    const printLabel = fakeFramework()
    await printMerge('LW450', LABEL_XML, [{ 'Fixture Number': '601' }])
    for (const call of printLabel.mock.calls) {
      expect(call[2]).not.toContain('<DataRow>')
      expect(call[2]).toContain('<DataTable>')  // the table itself must survive
    }
  })
})
