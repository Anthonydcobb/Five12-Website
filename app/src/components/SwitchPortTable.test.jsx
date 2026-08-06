import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import axios from 'axios'
import SwitchPortTable from './SwitchPortTable'

vi.mock('axios')

const PORTS = [
  { port: 5, name: 'Port 5', link: 'up', macs: ['00:19:7C:02:E0:5B'], deviceCount: 1 },
  { port: 6, name: 'Port 6', link: 'up', macs: ['AA:BB:CC:00:00:99'], deviceCount: 1 },
  { port: 7, name: 'Port 7', link: 'down', macs: [], deviceCount: 0 },
  { port: 12, name: 'Port 12', link: 'up',
    macs: Array.from({ length: 79 }, (_, i) => `DD:EE:FF:00:00:${i.toString(16).padStart(2, '0').toUpperCase()}`),
    deviceCount: 79 },
]

const SWITCH = {
  macAddress: 'D0:69:9E:04:78:72',
  vendorData: { switchPorts: PORTS, switchPortsAsOf: '2026-08-06T13:15:16.000000Z' },
}

const DEVICES = [
  { macAddress: '00:19:7C:02:E0:5B', label: 'Bollero Antenna #1', lastIp: '192.168.1.11', deviceType: 'bolero' },
]

beforeEach(() => { vi.resetAllMocks() })

describe('SwitchPortTable', () => {
  it('names a device on a single-MAC port', () => {
    axios.get.mockReturnValue(new Promise(() => {}))
    render(<SwitchPortTable device={SWITCH} devices={DEVICES} />)
    expect(screen.getByText(/Bollero Antenna #1/)).toBeInTheDocument()
  })

  it('shows a raw MAC for a device it does not know, rather than inventing a name', () => {
    axios.get.mockReturnValue(new Promise(() => {}))
    render(<SwitchPortTable device={SWITCH} devices={DEVICES} />)
    expect(screen.getByText(/AA:BB:CC:00:00:99/)).toBeInTheDocument()
  })

  it('does not claim a device is ON a port shared with 78 others', () => {
    axios.get.mockReturnValue(new Promise(() => {}))
    render(<SwitchPortTable device={SWITCH} devices={DEVICES} />)
    const row = screen.getByText('Port 12').closest('tr')
    expect(row.textContent).toMatch(/79 devices/)
  })

  it('shows an empty port as empty', () => {
    axios.get.mockReturnValue(new Promise(() => {}))
    render(<SwitchPortTable device={SWITCH} devices={DEVICES} />)
    const row = screen.getByText('Port 7').closest('tr')
    expect(row.textContent).toMatch(/down/)
  })

  it('labels the map stale when the switch did not answer', async () => {
    axios.get.mockResolvedValue({ data: { live: false, switchPorts: PORTS, asOf: new Date(Date.now() - 240_000).toISOString() } })
    render(<SwitchPortTable device={SWITCH} devices={DEVICES} />)
    expect(await screen.findByText(/switch did not answer/)).toBeInTheDocument()
  })

  it('says our refresh failed rather than blaming the switch, on a bad body', async () => {
    axios.get.mockResolvedValue({ data: '<!doctype html><html>Frontend not built</html>' })
    render(<SwitchPortTable device={SWITCH} devices={DEVICES} />)
    expect(await screen.findByText(/could not refresh/)).toBeInTheDocument()
    expect(screen.queryByText(/switch did not answer/)).not.toBeInTheDocument()
  })

  it('keeps the cached map and says so when the request errors', async () => {
    axios.get.mockRejectedValue(new Error('network'))
    render(<SwitchPortTable device={SWITCH} devices={DEVICES} />)
    expect(await screen.findByText(/could not refresh/)).toBeInTheDocument()
    expect(screen.getByText('Port 5')).toBeInTheDocument()
  })

  it('renders nothing and fires no request for a device with no map', () => {
    const { container } = render(
      <SwitchPortTable device={{ macAddress: 'AA:BB:CC:00:00:01', vendorData: {} }} devices={DEVICES} />
    )
    expect(container).toBeEmptyDOMElement()
    expect(axios.get).not.toHaveBeenCalled()
  })
})
