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

  // A failed refresh must keep the rows AND say they are unconfirmed. Leaving
  // the banner unset rendered an up-to-5-minutes-old cached patch identically
  // to a confirmed-live one, permanently — the spec's forbidden "silently
  // presented as current". The triggers are ordinary: backend restarting
  // mid-show, a proxy hiccup, a 500.
  it('keeps the cached patch when the request errors, and labels it', async () => {
    axios.get.mockRejectedValue(new Error('network'))
    render(<PortTable device={DEVICE} />)
    await waitFor(() => expect(axios.get).toHaveBeenCalled())
    expect(screen.getByText('21')).toBeInTheDocument()
    expect(await screen.findByText(/could not refresh/)).toBeInTheDocument()
    // Different wording from the node-did-not-answer case on purpose: the
    // node may be perfectly fine here, it is our refresh that failed. Saying
    // the node is down would be a second false statement.
    expect(screen.queryByText(/node did not answer/)).not.toBeInTheDocument()
  })

  it('times a failed refresh from the stored patch, not from the ping clock', async () => {
    axios.get.mockRejectedValue(new Error('network'))
    render(<PortTable device={{
      ...DEVICE,
      // last_seen is refreshed every 20s by the ICMP keep-alive and says
      // nothing about when the patch was last read. portsAsOf does.
      lastSeen: new Date().toISOString(),
      vendorData: { ...DEVICE.vendorData, portsAsOf: new Date(Date.now() - 240_000).toISOString() },
    }} />)
    expect(await screen.findByText(/could not refresh · as of 4m ago/)).toBeInTheDocument()
  })

  it('says the time is unknown when a failed refresh has no stored portsAsOf', async () => {
    axios.get.mockRejectedValue(new Error('network'))
    render(<PortTable device={DEVICE} />)
    expect(await screen.findByText(/could not refresh · time unknown/)).toBeInTheDocument()
    // "never" is the wrong word: the node did answer once — that is how we
    // have a cached patch — we just do not know when.
    expect(screen.queryByText(/never/)).not.toBeInTheDocument()
  })

  // The SPA-fallback case (stale backend, the route 404s into index.html)
  // does NOT land in the catch: axios resolves with an HTML string rather
  // than rejecting, since it's a successful HTTP response. `res.data.live`
  // is undefined, and the not-well-formed-body check now treats that as a
  // refresh failure rather than a node failure — the node is fine, our
  // backend is stale, and "node did not answer" would blame the wrong side.
  it('shows the could-not-refresh banner when the route falls through to index.html', async () => {
    axios.get.mockResolvedValue({ data: '<!doctype html><div id="root"></div>' })
    render(<PortTable device={DEVICE} />)
    expect(await screen.findByText(/could not refresh/)).toBeInTheDocument()
    expect(screen.queryByText(/node did not answer/)).not.toBeInTheDocument()
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

  // Finding 2 round 2 regression: `stale` is not tagged with the mac it
  // belongs to, only `portsState` is. So when device A's check resolved
  // live:false (banner showing) and the user then selects device B, the
  // render that applies device B's props (before the effect commits) keeps
  // device A's `stale` value while `portsState` has already fallen back to
  // device B's own cached rows. That paints device B's fresh, never-queried
  // rows underneath device A's "node did not answer" banner — the reviewer's
  // Profiler probe captured this exact commit. A plain render/rerender test
  // can't see it: act() flushes the corrective effect before assertions run,
  // so the bug self-heals before it can be observed. Profiler captures every
  // commit, including the intermediate one.
  it('never commits a frame showing the previous device\'s stale banner over the new device\'s fresh rows', async () => {
    const DEVICE_B = {
      macAddress: 'AA:BB:CC:00:00:02',
      vendorData: { model: 'XND-4', ports: [
        { port: 1, universe: 99, protocol: 'sACN', direction: 'Output', status: 'OK' },
      ] },
    }
    axios.get.mockImplementation((url) => {
      if (url.includes(DEVICE.macAddress)) {
        return Promise.resolve({ data: { live: false, ports: CACHED, asOf: null } })
      }
      return new Promise(() => {}) // device B's own check never resolves
    })

    const container = document.createElement('div')
    document.body.appendChild(container)
    const snapshots = []
    const onRender = () => { snapshots.push(container.textContent) }

    const { rerender } = render(
      <Profiler id="probe" onRender={onRender}><PortTable device={DEVICE} /></Profiler>,
      { container }
    )
    // Let device A's live:false response resolve and commit the stale banner.
    await waitFor(() => expect(container.textContent).toMatch(/node did not answer/))

    snapshots.length = 0
    rerender(
      <Profiler id="probe" onRender={onRender}><PortTable device={DEVICE_B} /></Profiler>
    )

    expect(snapshots.length).toBeGreaterThan(0)
    for (const snapshot of snapshots) {
      const hasStaleBanner = snapshot.includes('node did not answer')
      const hasDeviceBRow = snapshot.includes('199sACNOutputOK')
      expect(hasStaleBanner && hasDeviceBRow).toBe(false)
    }
  })
})
