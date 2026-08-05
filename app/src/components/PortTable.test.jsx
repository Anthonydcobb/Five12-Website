import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import axios from 'axios'
import PortTable from './PortTable'

vi.mock('axios')

const CACHED = [
  { port: 1, universe: 21, protocol: 'sACN', direction: 'Output', status: 'OK' },
  { port: 2, universe: 42, protocol: 'sACN', direction: 'Output', status: 'OK' },
]

const DEVICE = {
  macAddress: '28:36:38:C0:39:C0',
  lastSeen: new Date().toISOString(),
  vendorData: { model: 'XND-8', ports: CACHED },
}

beforeEach(() => {
  vi.resetAllMocks()
})

describe('PortTable', () => {
  it('paints the cached patch before the live read resolves', () => {
    axios.get.mockReturnValue(new Promise(() => {}))   // never settles
    render(<PortTable device={DEVICE} />)
    expect(screen.getByText('21')).toBeInTheDocument()
    expect(screen.getByText('42')).toBeInTheDocument()
  })

  it('replaces the cached patch with the live one', async () => {
    axios.get.mockResolvedValue({ data: {
      live: true,
      ports: [{ ...CACHED[0], universe: 77 }, CACHED[1]],
    } })
    render(<PortTable device={DEVICE} />)
    expect(await screen.findByText('77')).toBeInTheDocument()
    expect(screen.queryByText('21')).not.toBeInTheDocument()
  })

  it('marks the patch stale when the node did not answer', async () => {
    axios.get.mockResolvedValue({ data: {
      live: false, ports: CACHED, asOf: new Date(Date.now() - 240_000).toISOString(),
    } })
    render(<PortTable device={DEVICE} />)
    expect(await screen.findByText(/4m ago/)).toBeInTheDocument()
  })

  it('keeps the cached patch when the request errors', async () => {
    axios.get.mockRejectedValue(new Error('network'))
    render(<PortTable device={DEVICE} />)
    await waitFor(() => expect(axios.get).toHaveBeenCalled())
    expect(screen.getByText('21')).toBeInTheDocument()
  })

  it('renders nothing for a device with no ports', () => {
    const { container } = render(
      <PortTable device={{ macAddress: 'AA:BB:CC:00:00:01', vendorData: {} }} />
    )
    expect(container).toBeEmptyDOMElement()
    expect(axios.get).not.toHaveBeenCalled()
  })

  it('shows an undecoded status as its raw code rather than blank', async () => {
    axios.get.mockResolvedValue({ data: {
      live: true,
      ports: [{ port: 1, universe: 5, protocol: 'sACN', direction: 'Output', status: 'code 9' }],
    } })
    render(<PortTable device={DEVICE} />)
    expect(await screen.findByText('code 9')).toBeInTheDocument()
  })
})
