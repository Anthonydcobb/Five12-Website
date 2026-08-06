import { describe, expect, it, vi, beforeEach } from 'vitest'
import { Profiler } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import axios from 'axios'
import UplinkLine from './UplinkLine'

vi.mock('axios')

const DEVICE = { macAddress: '00:19:7C:02:E0:5B', label: 'Bollero Antenna #1' }

beforeEach(() => { vi.resetAllMocks() })

describe('UplinkLine', () => {
  // NOTE: the plain "states the port when one device is behind it" case now
  // lives in 'states the port plainly, with its age, for a FRESH one-device
  // result' below. deviceCount === 1 is necessary but no longer sufficient,
  // so a fixture without an asOf can no longer stand for the confident case.

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

  it('never states a negative count when deviceCount is 0', async () => {
    axios.get.mockResolvedValue({ data: { found: true, switchLabel: 'Luminex',
      switchMac: 'D0:69:9E:04:77:C8', port: 12, portName: 'Port 12', deviceCount: 0 } })
    render(<UplinkLine device={DEVICE} />)
    expect(await screen.findByText(/behind Luminex · Port 12/)).toBeInTheDocument()
    expect(screen.getByText(/shared with others/)).toBeInTheDocument()
    expect(screen.queryByText(/-1 others/)).not.toBeInTheDocument()
  })

  it('never states NaN others when deviceCount is missing', async () => {
    axios.get.mockResolvedValue({ data: { found: true, switchLabel: 'Luminex',
      switchMac: 'D0:69:9E:04:77:C8', port: 12, portName: 'Port 12' } })
    render(<UplinkLine device={DEVICE} />)
    expect(await screen.findByText(/behind Luminex · Port 12/)).toBeInTheDocument()
    expect(screen.getByText(/shared with others/)).toBeInTheDocument()
    expect(screen.queryByText(/NaN others/)).not.toBeInTheDocument()
  })

  // Finding 1 regression: UplinkLine is rendered without a `key` in
  // DeviceDetail, so it persists across device selections. The render-time
  // guard `hit.mac === device.macAddress ? hit.value : null` at
  // UplinkLine.jsx:110 exists to stop a stale `hit` (still describing the
  // PREVIOUS device) from painting that device's switch/port under the
  // NEWLY selected device's identity. A plain render/rerender/queryByText
  // test can't see this: the corrective effect (which resets `hit` to the
  // new mac) commits before React's act() returns control to the test, so
  // the bug self-heals before any query runs. A <Profiler onRender> records
  // every commit, including the intermediate one where the guard (or its
  // absence) actually matters — same technique as
  // SwitchPortTable.test.jsx's and PortTable.test.jsx's "never commits a
  // frame showing the previous device" tests.
  // Critical 1 regression: the stored switch port map has NO expiry.
  // `read_switch_ports` returns {} on failure by design and the scanner merges
  // shallowly ({**prior, **fresh}), so a switch that goes dark keeps its map
  // frozen in the database indefinitely, across restarts. SwitchPortTable
  // already says so ("switch did not answer · as of 3h ago"); this line read
  // the same map and stated present-tense attachment with no age at all. A
  // spec line governs it: "The table also ages. FDB entries expire when a
  // device goes quiet, so absence is not proof of unplugging. The UI must not
  // imply otherwise." So `deviceCount === 1` is necessary but no longer
  // sufficient — the map must also be fresher than two 300s discovery sweeps.
  const FRESH = () => new Date(Date.now() - 30_000).toISOString()
  const STALE = () => new Date(Date.now() - 3 * 3600_000).toISOString()

  it('states the port plainly, with its age, for a FRESH one-device result', async () => {
    axios.get.mockResolvedValue({ data: { found: true, switchLabel: 'Luminex (CARL)',
      switchMac: 'D0:69:9E:04:78:72', port: 5, portName: 'Port 5', deviceCount: 1, asOf: FRESH() } })
    render(<UplinkLine device={DEVICE} />)
    expect(await screen.findByText(/on Luminex \(CARL\) · Port 5/)).toBeInTheDocument()
    expect(screen.getByText(/as of \d+s ago/)).toBeInTheDocument()
  })

  it('never says "on" for a one-device result from a STALE map', async () => {
    axios.get.mockResolvedValue({ data: { found: true, switchLabel: 'Luminex (CARL)',
      switchMac: 'D0:69:9E:04:78:72', port: 5, portName: 'Port 5', deviceCount: 1, asOf: STALE() } })
    render(<UplinkLine device={DEVICE} />)
    expect(await screen.findByText(/behind Luminex \(CARL\) · Port 5/)).toBeInTheDocument()
    expect(screen.queryByText(/^on /)).not.toBeInTheDocument()
  })

  it('says the map is stale IN WORDS, not only by switching to "behind"', async () => {
    axios.get.mockResolvedValue({ data: { found: true, switchLabel: 'Luminex (CARL)',
      switchMac: 'D0:69:9E:04:78:72', port: 5, portName: 'Port 5', deviceCount: 1, asOf: STALE() } })
    render(<UplinkLine device={DEVICE} />)
    await screen.findByText(/behind/)
    expect(screen.getByText(/3h ago/)).toBeInTheDocument()
    expect(screen.getByText(/may already have changed/)).toBeInTheDocument()
  })

  it('never says "on" when asOf is missing entirely', async () => {
    // Every row swept before this change carries no timestamp at all. No
    // evidence of age is not evidence of youth — a missing asOf must fall to
    // the hedged branch, never the confident one.
    axios.get.mockResolvedValue({ data: { found: true, switchLabel: 'Luminex (CARL)',
      switchMac: 'D0:69:9E:04:78:72', port: 5, portName: 'Port 5', deviceCount: 1 } })
    render(<UplinkLine device={DEVICE} />)
    expect(await screen.findByText(/behind Luminex \(CARL\) · Port 5/)).toBeInTheDocument()
    expect(screen.queryByText(/^on /)).not.toBeInTheDocument()
    expect(screen.getByText(/age unknown/)).toBeInTheDocument()
  })

  it('never commits a frame showing the previous device\'s switch/port line after the device prop changes', async () => {
    const DEVICE_B = { macAddress: 'AA:BB:CC:00:00:02', label: 'Bollero Antenna #2' }
    axios.get.mockImplementation((url) => {
      if (url.includes(DEVICE.macAddress)) {
        return Promise.resolve({ data: { found: true, switchLabel: 'Luminex (CARL)',
          switchMac: 'D0:69:9E:04:78:72', port: 5, portName: 'Port 5', deviceCount: 1 } })
      }
      return new Promise(() => {}) // device B's own lookup never resolves
    })

    const container = document.createElement('div')
    document.body.appendChild(container)
    const snapshots = []
    const onRender = () => { snapshots.push(container.textContent) }

    const { rerender } = render(
      <Profiler id="probe" onRender={onRender}><UplinkLine device={DEVICE} /></Profiler>,
      { container }
    )
    // Let device A's response resolve and commit the "on ..." line.
    await waitFor(() => expect(container.textContent).toMatch(/Luminex \(CARL\)/))

    snapshots.length = 0
    rerender(
      <Profiler id="probe" onRender={onRender}><UplinkLine device={DEVICE_B} /></Profiler>
    )

    expect(snapshots.length).toBeGreaterThan(0)
    for (const snapshot of snapshots) {
      expect(snapshot).not.toContain('Luminex (CARL)') // device A's switch label
      expect(snapshot).not.toContain('Port 5') // device A's port name
    }
  })
})
