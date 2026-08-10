import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import axios from 'axios'
import SnapshotImportPanel from './SnapshotImportPanel'

vi.mock('axios')

const NETGEAR = { macAddress: 'AA', deviceType: 'netgear', vendorData: {} }
const NODE = { macAddress: 'BB', deviceType: 'swisson', vendorData: {} }

beforeEach(() => { vi.resetAllMocks() })

describe('SnapshotImportPanel', () => {
  it('renders nothing for a non-NETGEAR device', () => {
    const { container } = render(<SnapshotImportPanel device={NODE} onImported={() => {}} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('posts pasted html and reports what was imported', async () => {
    axios.post.mockResolvedValue({ data: {
      macAddress: 'AA', systemName: 'FMB Switch 60',
      profileCount: 5, portCount: 12, hostDataAvailable: true,
    } })
    const onImported = vi.fn()
    render(<SnapshotImportPanel device={NETGEAR} onImported={onImported} />)

    fireEvent.click(screen.getByText(/import switch snapshot/i))
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '<html>x</html>' } })
    fireEvent.click(screen.getByText(/^import$/i))

    await waitFor(() => expect(onImported).toHaveBeenCalled())
    expect(axios.post).toHaveBeenCalledWith('/api/network/snapshot',
      { html: '<html>x</html>', macAddress: 'AA' })
    expect(screen.getByText(/FMB Switch 60/)).toBeTruthy()
    expect(screen.getByText(/5 profiles/)).toBeTruthy()
  })

  it('surfaces the server refusal detail rather than a generic failure', async () => {
    axios.post.mockRejectedValue({
      response: { status: 409, data: { error: 'serial_conflict', detail: 'Recorded with serial X.' } },
    })
    render(<SnapshotImportPanel device={NETGEAR} onImported={() => {}} />)
    fireEvent.click(screen.getByText(/import switch snapshot/i))
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '<html>x</html>' } })
    fireEvent.click(screen.getByText(/^import$/i))

    await waitFor(() => expect(screen.getByText(/Recorded with serial X\./)).toBeTruthy())
  })

  it('warns when host data was dropped', async () => {
    axios.post.mockResolvedValue({ data: {
      macAddress: 'AA', systemName: 'S', profileCount: 5, portCount: 12,
      hostDataAvailable: false,
    } })
    render(<SnapshotImportPanel device={NETGEAR} onImported={() => {}} />)
    fireEvent.click(screen.getByText(/import switch snapshot/i))
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '<html>x</html>' } })
    fireEvent.click(screen.getByText(/^import$/i))

    await waitFor(() => expect(screen.getByText(/host details were not readable/i)).toBeTruthy())
  })

  // A Port Configuration page carries no identity of its own, so the MAC of
  // the switch the operator is looking at is the only thing that says which
  // device the capture belongs to.
  const paste = () => {
    fireEvent.click(screen.getByText(/import switch snapshot/i))
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '<html>x</html>' } })
    fireEvent.click(screen.getByText(/^import$/i))
  }

  it('sends the selected device MAC with the paste', async () => {
    axios.post.mockResolvedValue({ data: { portsUpdated: 10 } })
    render(<SnapshotImportPanel device={NETGEAR} onImported={() => {}} />)
    paste()
    await waitFor(() => expect(axios.post).toHaveBeenCalledWith(
      '/api/network/snapshot', { html: '<html>x</html>', macAddress: 'AA' },
    ))
  })

  it('names the ports a partial capture missed', async () => {
    axios.post.mockResolvedValue({ data: {
      portsUpdated: 10, portsInCaptureNotInBase: [11, 12], disagreements: [],
    } })
    render(<SnapshotImportPanel device={NETGEAR} onImported={() => {}} />)
    paste()
    await waitFor(() => expect(screen.getByText(/11, 12/)).toBeTruthy())
  })

  it('surfaces a profile disagreement as a warning', async () => {
    axios.post.mockResolvedValue({ data: {
      portsUpdated: 10, portsInCaptureNotInBase: [],
      disagreements: [{ port: 3, field: 'profile', popover: 'WRONG', portConfig: 'HogNet' }],
    } })
    render(<SnapshotImportPanel device={NETGEAR} onImported={() => {}} />)
    paste()
    await waitFor(() => expect(screen.getByText(/Port 3/i)).toBeTruthy())
  })

  it('does not show the Overview summary for a portconfig result', async () => {
    axios.post.mockResolvedValue({ data: { portsUpdated: 10, portsInCaptureNotInBase: [] } })
    render(<SnapshotImportPanel device={NETGEAR} onImported={() => {}} />)
    paste()
    await waitFor(() => expect(screen.getByText(/10 ports updated/i)).toBeTruthy())
    expect(screen.queryByText(/profiles,/)).toBeNull()
  })
})
