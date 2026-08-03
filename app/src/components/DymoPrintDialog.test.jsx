import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import DymoPrintDialog from './DymoPrintDialog'
import { dymoReady, getPrinters, renderPreview, printMerge } from '../lib/dymo'

vi.mock('../lib/dymo', () => ({
  dymoReady: vi.fn(),
  getPrinters: vi.fn(),
  renderPreview: vi.fn(),
  printMerge: vi.fn(),
}))

// Variables that guessMapping resolves against the patch-sheet columns, so the
// dialog reaches a fully-mapped state and actually attempts a render.
const TEMPLATE = { id: 3, name: 'LZMU Dymo Label Big', labelXml: '<DesktopLabel/>',
  variables: ['Universe', 'Address'], savedMappings: {} }
const PATCH_ROWS = [{ universe: '1', address: '25' }, { universe: '1', address: '37' }]

beforeEach(() => {
  localStorage.clear()
  dymoReady.mockResolvedValue(true)
  getPrinters.mockResolvedValue([{ name: 'DYMO LabelWriter 450 Twin Turbo', isTwinTurbo: true }])
})

function textResponse(data) {
  return { ok: true, status: 200, text: vi.fn().mockResolvedValue(JSON.stringify(data)) }
}

function mockApi() {
  global.fetch = vi.fn((url) => {
    if (url === '/api/dymo-templates') return Promise.resolve(textResponse([{ id: 3, name: TEMPLATE.name }]))
    if (url === '/api/dymo-templates/3') return Promise.resolve(textResponse(TEMPLATE))
    if (url === '/api/dymo-csv-sources') return Promise.resolve(textResponse([]))
    return Promise.resolve(textResponse({}))
  })
}

// Drive the dialog to the state where every variable is mapped and a render is attempted.
async function renderMapped() {
  mockApi()
  const user = userEvent.setup()
  render(<DymoPrintDialog patchRows={PATCH_ROWS} selectedRows={[]} onClose={vi.fn()} />)
  const select = (await screen.findAllByRole('combobox'))[0]
  await user.selectOptions(select, '3')
  await screen.findByText('Universe')          // mapping table rendered => template loaded
  return user
}

afterEach(() => vi.restoreAllMocks())

describe('DymoPrintDialog preview pane', () => {
  it('shows the render failure instead of the "not mapped yet" placeholder', async () => {
    // DYMO Connect Web Service 1.6.1.7's RenderLabel endpoint throws before it
    // ever reads the request (missing System.Xml.XmlSerializer assembly), so it
    // answers HTTP 500 for every label. Swallowing that left the pane showing
    // "preview appears when mapped", which blames the user for a service fault.
    renderPreview.mockRejectedValue(new Error('renderLabel failed: 500'))
    await renderMapped()

    expect(await screen.findByText(/preview unavailable/i)).toBeInTheDocument()
    expect(screen.queryByText(/preview appears when mapped/i)).not.toBeInTheDocument()
  })

  it('says printing still works, because the failure is preview-only', async () => {
    renderPreview.mockRejectedValue(new Error('renderLabel failed: 500'))
    await renderMapped()

    expect(await screen.findByText(/printing (is unaffected|still works)/i)).toBeInTheDocument()
  })

  it('logs the underlying render error rather than discarding it', async () => {
    const err = new Error('renderLabel failed: 500')
    renderPreview.mockRejectedValue(err)
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    await renderMapped()

    await waitFor(() => expect(spy).toHaveBeenCalledWith(expect.stringMatching(/preview/i), err))
  })

  it('still shows the placeholder when nothing has been mapped yet', async () => {
    // No template chosen => no render attempted => the placeholder is honest.
    renderPreview.mockResolvedValue('iVBORw0KGgo=')
    mockApi()
    render(<DymoPrintDialog patchRows={PATCH_ROWS} selectedRows={[]} onClose={vi.fn()} />)

    await screen.findByText('Print DYMO Labels')
    expect(screen.queryByText(/preview unavailable/i)).not.toBeInTheDocument()
    expect(renderPreview).not.toHaveBeenCalled()
  })

  it('shows the label image once a render succeeds', async () => {
    renderPreview.mockResolvedValue('iVBORw0KGgo=')
    await renderMapped()

    const img = await screen.findByAltText('label preview')
    expect(img).toHaveAttribute('src', 'data:image/png;base64,iVBORw0KGgo=')
    expect(screen.queryByText(/preview unavailable/i)).not.toBeInTheDocument()
  })

  it('clears a stale failure message when a later render succeeds', async () => {
    renderPreview.mockRejectedValueOnce(new Error('renderLabel failed: 500'))
      .mockResolvedValue('iVBORw0KGgo=')
    const user = await renderMapped()
    await screen.findByText(/preview unavailable/i)

    await user.click(screen.getByRole('button', { name: /next label/i }))   // re-renders
    await waitFor(() => expect(screen.queryByText(/preview unavailable/i)).not.toBeInTheDocument())
  })
})

describe('DymoPrintDialog roll selector', () => {
  beforeEach(() => { renderPreview.mockResolvedValue(null) })   // preview isn't under test here

  it('shows Left/Right for a Twin Turbo printer, defaults Left, persists per printer', async () => {
    const user = await renderMapped()
    const left = await screen.findByRole('button', { name: 'Left' })
    const right = screen.getByRole('button', { name: 'Right' })
    expect(left.className).toContain('border-brand')   // selected style
    await user.click(right)
    expect(localStorage.getItem('five12_dymo_roll:DYMO LabelWriter 450 Twin Turbo')).toBe('Right')
  })

  it('hides the roll selector for a non-Twin-Turbo printer', async () => {
    getPrinters.mockResolvedValue([
      { name: 'DYMO LabelWriter 450 Twin Turbo', isTwinTurbo: true },
      { name: 'DYMO LabelWriter 450', isTwinTurbo: false },
    ])
    const user = await renderMapped()
    await screen.findByRole('button', { name: 'Left' })   // Twin Turbo printer selected by default
    await user.selectOptions(screen.getByLabelText('Printer'), 'DYMO LabelWriter 450')
    expect(screen.queryByRole('button', { name: 'Left' })).toBeNull()
  })
})

describe('DymoPrintDialog run control', () => {
  beforeEach(() => { renderPreview.mockResolvedValue(null) })   // preview isn't under test here

  it('swaps Print for Stop while running, aborts on click, reports a stopped run', async () => {
    let resolvePrint
    printMerge.mockReturnValue(new Promise((res) => { resolvePrint = res }))
    await renderMapped()
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
    await renderMapped()
    await userEvent.click(await screen.findByRole('button', { name: /Print all 2/ }))
    await screen.findByText('Paper out — stopped after 1 of 2.')
  })

  it('reports a completed run and passes no roll for a non-Twin-Turbo printer', async () => {
    getPrinters.mockResolvedValue([
      { name: 'DYMO LabelWriter 450 Twin Turbo', isTwinTurbo: true },
      { name: 'DYMO LabelWriter 450', isTwinTurbo: false },
    ])
    printMerge.mockResolvedValue({ printed: 2, total: 2, stopped: false, reason: null })
    await renderMapped()
    await userEvent.selectOptions(screen.getByLabelText('Printer'), 'DYMO LabelWriter 450')
    await userEvent.click(await screen.findByRole('button', { name: /Print all 2/ }))
    await screen.findByText('Printed 2 labels.')
    expect(printMerge.mock.calls[0][3].roll).toBeUndefined()
  })

  it('disables closing while a run is active', async () => {
    let resolvePrint
    printMerge.mockReturnValue(new Promise((res) => { resolvePrint = res }))
    await renderMapped()
    await userEvent.click(await screen.findByRole('button', { name: /Print all 2/ }))
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled()
    resolvePrint({ printed: 2, total: 2, stopped: false, reason: null })
    await screen.findByText('Printed 2 labels.')
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeEnabled()
  })

  it('saves the mapping when a stopped run still printed labels', async () => {
    printMerge.mockResolvedValue({ printed: 1, total: 2, stopped: true, reason: 'Paper out' })
    const user = await renderMapped()
    await user.click(await screen.findByRole('button', { name: /Print all 2/ }))
    await screen.findByText('Paper out — stopped after 1 of 2.')
    // labels came out, so the column mapping must still be remembered
    expect(global.fetch.mock.calls.some(([url, init]) =>
      String(url) === '/api/dymo-templates/3/mapping' && init?.method === 'PUT')).toBe(true)
  })

  it('does not save the mapping when zero labels printed', async () => {
    printMerge.mockResolvedValue({ printed: 0, total: 2, stopped: true, reason: null })
    const user = await renderMapped()
    await user.click(await screen.findByRole('button', { name: /Print all 2/ }))
    await screen.findByText('Stopped — 0 of 2 printed.')
    expect(global.fetch.mock.calls.some(([url]) => String(url).includes('/mapping'))).toBe(false)
  })

  it('clamps the progress line on the final label', async () => {
    printMerge.mockImplementation((printer, xml, recs, opts) => {
      opts.onProgress({ printed: 2, total: 2 })   // last label finished, run not yet resolved
      return new Promise(() => {})                // stay busy so the line stays visible
    })
    const user = await renderMapped()
    await user.click(await screen.findByRole('button', { name: /Print all 2/ }))
    await screen.findByText('Printing 2 of 2…')   // min(printed+1, total) clamps — NOT '3 of 2'
    expect(screen.queryByText('Printing 3 of 2…')).toBeNull()
  })
})
