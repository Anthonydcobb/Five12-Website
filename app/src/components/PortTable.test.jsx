import { describe, expect, it, vi, beforeEach } from 'vitest'
import { Profiler } from 'react'
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

  // Finding 1 regression: `live: false` can arrive with no usable timestamp
  // (NetworkDevice.last_seen is nullable). The stale banner must still
  // render — silently collapsing to the "live" sentinel would present an
  // old patch as current, which the feature spec forbids outright.
  it('shows the stale banner when live is false and asOf is explicitly null', async () => {
    axios.get.mockResolvedValue({ data: {
      live: false, ports: CACHED, asOf: null,
    } })
    render(<PortTable device={DEVICE} />)
    expect(await screen.findByText(/node did not answer/)).toBeInTheDocument()
    // "never" is the wrong word here: the node DID answer once (that's how
    // we have a cached patch); we just don't know when it was last seen.
    expect(screen.queryByText(/never/)).not.toBeInTheDocument()
  })

  it('shows the stale banner when live is false and asOf is missing entirely', async () => {
    axios.get.mockResolvedValue({ data: {
      live: false, ports: CACHED,
    } })
    render(<PortTable device={DEVICE} />)
    expect(await screen.findByText(/node did not answer/)).toBeInTheDocument()
  })

  it('still shows the relative time when live is false and asOf is known', async () => {
    axios.get.mockResolvedValue({ data: {
      live: false, ports: CACHED, asOf: new Date(Date.now() - 240_000).toISOString(),
    } })
    render(<PortTable device={DEVICE} />)
    expect(await screen.findByText(/4m ago/)).toBeInTheDocument()
  })

  // Finding 2 regression: DeviceDetail renders PortTable without a `key`,
  // so it persists across device selections. `ports` state is only reset
  // inside the effect, which commits AFTER the prop-driven render — so a
  // plain rerender+queryByText assertion can't see the bug, because
  // React's act() flushes the corrective effect before control returns to
  // the test. A <Profiler onRender> captures every individual commit in
  // order, including the intermediate one, which is the only way to catch
  // a device change momentarily painting the previous device's rows.
  it('never commits a frame showing the previous device rows after the device prop changes', () => {
    axios.get.mockReturnValue(new Promise(() => {})) // never resolves
    const DEVICE_B = {
      macAddress: 'AA:BB:CC:00:00:02',
      vendorData: { model: 'XND-4', ports: [
        { port: 1, universe: 99, protocol: 'sACN', direction: 'Output', status: 'OK' },
      ] },
    }
    const container = document.createElement('div')
    document.body.appendChild(container)
    const snapshots = []
    const onRender = () => { snapshots.push(container.textContent) }

    const { rerender } = render(
      <Profiler id="probe" onRender={onRender}><PortTable device={DEVICE} /></Profiler>,
      { container }
    )
    snapshots.length = 0
    rerender(
      <Profiler id="probe" onRender={onRender}><PortTable device={DEVICE_B} /></Profiler>
    )

    expect(snapshots.length).toBeGreaterThan(0)
    for (const snapshot of snapshots) {
      expect(snapshot).not.toContain('121sACNOutputOK') // device A's port 1 / universe 21 row
      expect(snapshot).not.toContain('242sACNOutputOK') // device A's port 2 / universe 42 row
    }
    expect(snapshots.some(s => s.includes('199sACNOutputOK'))).toBe(true) // device B's row eventually commits
  })
})
