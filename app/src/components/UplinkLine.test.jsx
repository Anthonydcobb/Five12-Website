import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import axios from 'axios'
import UplinkLine from './UplinkLine'

vi.mock('axios')

const DEVICE = { macAddress: '00:19:7C:02:E0:5B', label: 'Bollero Antenna #1' }

beforeEach(() => { vi.resetAllMocks() })

describe('UplinkLine', () => {
  it('states the port plainly when one device is behind it', async () => {
    axios.get.mockResolvedValue({ data: { found: true, switchLabel: 'Luminex (CARL)',
      switchMac: 'D0:69:9E:04:78:72', port: 5, portName: 'Port 5', deviceCount: 1 } })
    render(<UplinkLine device={DEVICE} />)
    expect(await screen.findByText(/on Luminex \(CARL\) · Port 5/)).toBeInTheDocument()
  })

  it('says BEHIND, with the count, when the port is shared', async () => {
    axios.get.mockResolvedValue({ data: { found: true, switchLabel: 'Luminex',
      switchMac: 'D0:69:9E:04:77:C8', port: 12, portName: 'Port 12', deviceCount: 73 } })
    render(<UplinkLine device={DEVICE} />)
    expect(await screen.findByText(/behind Luminex · Port 12/)).toBeInTheDocument()
    expect(screen.getByText(/72 others/)).toBeInTheDocument()
  })

  it('never says "on" for a shared port', async () => {
    axios.get.mockResolvedValue({ data: { found: true, switchLabel: 'Luminex',
      switchMac: 'D0:69:9E:04:77:C8', port: 12, portName: 'Port 12', deviceCount: 73 } })
    render(<UplinkLine device={DEVICE} />)
    await screen.findByText(/behind/)
    expect(screen.queryByText(/^on /)).not.toBeInTheDocument()
  })

  it('says no switch has seen it rather than staying blank', async () => {
    axios.get.mockResolvedValue({ data: { found: false } })
    render(<UplinkLine device={DEVICE} />)
    expect(await screen.findByText(/no switch has seen this device/i)).toBeInTheDocument()
  })

  it('renders nothing while the request is in flight', () => {
    axios.get.mockReturnValue(new Promise(() => {}))
    const { container } = render(<UplinkLine device={DEVICE} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders nothing when the request fails', async () => {
    axios.get.mockRejectedValue(new Error('network'))
    const { container } = render(<UplinkLine device={DEVICE} />)
    await waitFor(() => expect(axios.get).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
  })
})
