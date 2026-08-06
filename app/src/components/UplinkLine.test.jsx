import { describe, expect, it, vi, beforeEach } from 'vitest'
import { Profiler } from 'react'
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
