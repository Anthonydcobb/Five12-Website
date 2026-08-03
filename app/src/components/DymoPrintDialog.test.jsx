import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import DymoPrintDialog from './DymoPrintDialog'
import { dymoReady, getPrinters, renderPreview } from '../lib/dymo'

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
  dymoReady.mockResolvedValue(true)
  getPrinters.mockResolvedValue(['DYMO LabelWriter 450 Twin Turbo'])
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
