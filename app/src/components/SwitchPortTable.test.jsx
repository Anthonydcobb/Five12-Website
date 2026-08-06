import { describe, expect, it, vi, beforeEach } from 'vitest'
import { Profiler } from 'react'
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

  // Finding 1 regression: a half-written stored row can have deviceCount: 1
  // with an EMPTY macs array (the cached path serves the raw stored JSON
  // with no revalidation, unlike the live path which guarantees
  // deviceCount === macs.length). nameFor(undefined) used to call
  // .toUpperCase() on undefined and throw, blanking the whole detail pane
  // (there is no ErrorBoundary under app/src). The port and its link state
  // are still real information, so the row must render, just honestly.
  it('does not crash on a port claiming one device with no recorded MAC', () => {
    const CORRUPT_PORTS = [
      { port: 3, name: 'Port 3', link: 'up', macs: [], deviceCount: 1 },
    ]
    axios.get.mockReturnValue(new Promise(() => {}))
    render(<SwitchPortTable
      device={{ macAddress: 'D0:69:9E:04:78:72', vendorData: { switchPorts: CORRUPT_PORTS } }}
      devices={DEVICES}
    />)
    const row = screen.getByText('Port 3').closest('tr')
    expect(row.textContent).toMatch(/not recorded/)
  })

  // Finding 3 coverage: SwitchPortTable persists across device selections
  // (DeviceDetail renders it without a `key`). Both `portsState` and `stale`
  // are tagged with the mac they describe and the render derives `ports`/
  // `staleValue` by falling back to the current device's own cached data
  // when the tag doesn't match yet — same shape as PortTable.jsx's fix. A
  // plain render/rerender/queryByText test can't observe a momentary wrong
  // commit: React's act() flushes the corrective effect before assertions
  // run, so unfixed code self-heals before it can be caught. A
  // <Profiler onRender> records every commit, including the intermediate
  // one, mirroring PortTable.test.jsx's two Profiler regression tests.
  const SWITCH_B = {
    macAddress: '11:22:33:44:55:66',
    vendorData: { switchPorts: [
      { port: 1, name: 'Port 1', link: 'up', macs: ['77:88:99:AA:BB:CC'], deviceCount: 1 },
    ] },
  }

  it('never commits a frame showing the previous switch rows after the device prop changes', () => {
    axios.get.mockReturnValue(new Promise(() => {})) // never resolves for either switch
    const container = document.createElement('div')
    document.body.appendChild(container)
    const snapshots = []
    const onRender = () => { snapshots.push(container.textContent) }

    const { rerender } = render(
      <Profiler id="probe" onRender={onRender}><SwitchPortTable device={SWITCH} devices={DEVICES} /></Profiler>,
      { container }
    )
    snapshots.length = 0
    rerender(
      <Profiler id="probe" onRender={onRender}><SwitchPortTable device={SWITCH_B} devices={DEVICES} /></Profiler>
    )

    expect(snapshots.length).toBeGreaterThan(0)
    for (const snapshot of snapshots) {
      expect(snapshot).not.toContain('Bollero Antenna #1') // SWITCH's port 5 device name
      expect(snapshot).not.toContain('AA:BB:CC:00:00:99') // SWITCH's port 6 raw mac
    }
    expect(snapshots.some(s => s.includes('77:88:99:AA:BB:CC'))).toBe(true) // SWITCH_B's row eventually commits
  })

  it('never commits a frame showing the previous switch\'s stale banner over the new switch\'s fresh rows', async () => {
    axios.get.mockImplementation((url) => {
      if (url.includes(SWITCH.macAddress)) {
        return Promise.resolve({ data: { live: false, switchPorts: PORTS, asOf: null } })
      }
      return new Promise(() => {}) // SWITCH_B's own check never resolves
    })

    const container = document.createElement('div')
    document.body.appendChild(container)
    const snapshots = []
    const onRender = () => { snapshots.push(container.textContent) }

    const { rerender } = render(
      <Profiler id="probe" onRender={onRender}><SwitchPortTable device={SWITCH} devices={DEVICES} /></Profiler>,
      { container }
    )
    // Let SWITCH's live:false response resolve and commit the stale banner.
    await waitFor(() => expect(container.textContent).toMatch(/switch did not answer/))

    snapshots.length = 0
    rerender(
      <Profiler id="probe" onRender={onRender}><SwitchPortTable device={SWITCH_B} devices={DEVICES} /></Profiler>
    )

    expect(snapshots.length).toBeGreaterThan(0)
    for (const snapshot of snapshots) {
      const hasStaleBanner = snapshot.includes('switch did not answer')
      const hasSwitchBRow = snapshot.includes('77:88:99:AA:BB:CC')
      expect(hasStaleBanner && hasSwitchBRow).toBe(false)
    }
  })
})
