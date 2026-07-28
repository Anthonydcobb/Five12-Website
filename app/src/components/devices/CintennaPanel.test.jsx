import { describe, expect, it, vi, beforeEach } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import CintennaPanel from './CintennaPanel'
import * as bleApi from '../../lib/bleApi'

vi.mock('../../lib/bleApi')

const DEVICES = {
  deviceCount: 2,
  devices: [
    { osId: 'rx-1', localName: 'F12L - 1946', rssi: -41, rssiSmoothed: -41,
      platform: 'lumenradio-timotwo-compatible', product: null,
      hardwareId: 'F1400000', evidence: ['service-uuid', 'manufacturer-data'],
      firstSeen: 100, lastSeen: 160 },
    { osId: 'tx-1', localName: 'F12L - 2071', rssi: -70, rssiSmoothed: -70,
      platform: 'lumenradio-timotwo-compatible', product: null,
      hardwareId: 'F1400000', evidence: ['manufacturer-data'],
      firstSeen: 100, lastSeen: 160 },
  ],
}

const SNAPSHOT = {
  osId: 'rx-1',
  fields: {
    name: { decoded: 'F12L - 1946', raw: '', source: 'gatt-read', readAt: 1 },
    battery: { decoded: 65, raw: '41', source: 'gatt-read', readAt: 1 },
    firmware: { decoded: '1.0.7.2', raw: '02070001', source: 'gatt-read', readAt: 1 },
    mode: { decoded: 'rx', raw: '00', source: 'gatt-read', readAt: 1 },
    dmxHold: { decoded: false, raw: '00', source: 'gatt-read', readAt: 1 },
  },
  warnings: [],
}

beforeEach(() => {
  vi.resetAllMocks()
  bleApi.signalBars.mockReturnValue(3)
  bleApi.fetchBleCapabilities.mockResolvedValue({ bleToolsEnabled: true, bleWriteEnabled: false })
})

describe('CintennaPanel', () => {
  it('lists nearby radios', async () => {
    bleApi.fetchBleDevices.mockResolvedValue(DEVICES)
    render(<CintennaPanel />)
    expect(await screen.findByText('F12L - 1946')).toBeInTheDocument()
    expect(screen.getByText('F12L - 2071')).toBeInTheDocument()
  })

  it('labels the platform without claiming an enclosure model', async () => {
    bleApi.fetchBleDevices.mockResolvedValue(DEVICES)
    render(<CintennaPanel />)
    await screen.findByText('F12L - 1946')
    expect(screen.getAllByText(/TimoTwo-compatible/i).length).toBeGreaterThan(0)
    expect(screen.queryByText(/Cintenna 2/)).not.toBeInTheDocument()
  })

  it('shows no battery or firmware before connecting', async () => {
    // Nearby is not connected. The roster is advertisement-only.
    bleApi.fetchBleDevices.mockResolvedValue(DEVICES)
    render(<CintennaPanel />)
    await screen.findByText('F12L - 1946')
    expect(screen.queryByText(/65%/)).not.toBeInTheDocument()
    expect(screen.queryByText(/1\.0\.7\.2/)).not.toBeInTheDocument()
  })

  it('reads a snapshot when the operator asks for one', async () => {
    bleApi.fetchBleDevices.mockResolvedValue(DEVICES)
    bleApi.fetchBleSnapshot.mockResolvedValue(SNAPSHOT)
    render(<CintennaPanel />)
    await userEvent.click(await screen.findByRole('button', { name: /F12L - 1946/ }))
    await userEvent.click(screen.getByRole('button', { name: /read status/i }))
    expect(await screen.findByText(/65%/)).toBeInTheDocument()
    expect(screen.getByText('1.0.7.2')).toBeInTheDocument()
  })

  it('shows the operator message for a Toolbox conflict', async () => {
    bleApi.fetchBleDevices.mockResolvedValue(DEVICES)
    bleApi.fetchBleSnapshot.mockRejectedValue({
      code: 'toolbox-holding-connection',
      message: 'CRMX Toolbox appears to be connected to this device. Close it completely.',
    })
    render(<CintennaPanel />)
    await userEvent.click(await screen.findByRole('button', { name: /F12L - 1946/ }))
    await userEvent.click(screen.getByRole('button', { name: /read status/i }))
    expect(await screen.findByText(/CRMX Toolbox/)).toBeInTheDocument()
  })

  it('explains itself when BLE tools are switched off', async () => {
    bleApi.fetchBleDevices.mockResolvedValue({ deviceCount: 0, devices: [], unavailable: true })
    render(<CintennaPanel />)
    expect(await screen.findByText(/FIVE12_BLE_TOOLS/)).toBeInTheDocument()
  })

  it('shows an honest error message on a real backend failure, not the switched-off copy', async () => {
    // Finding 2 regression: a 500 must not tell the operator to flip a
    // setting that is already correct.
    bleApi.fetchBleDevices.mockResolvedValue({ deviceCount: 0, devices: [], error: true })
    render(<CintennaPanel />)
    expect(await screen.findByText(/could not reach the bluetooth scan service/i)).toBeInTheDocument()
    expect(screen.queryByText(/FIVE12_BLE_TOOLS/)).not.toBeInTheDocument()
    expect(screen.queryByText(/switched off/i)).not.toBeInTheDocument()
  })

  it('says so when scanning finds nothing', async () => {
    bleApi.fetchBleDevices.mockResolvedValue({ deviceCount: 0, devices: [] })
    render(<CintennaPanel />)
    expect(await screen.findByText(/no CRMX devices nearby/i)).toBeInTheDocument()
  })

  const WRITE_ON = { bleToolsEnabled: true, bleWriteEnabled: true }

  const TX_SNAPSHOT = {
    osId: 'tx-1',
    fields: { mode: { decoded: 'tx', raw: '01', source: 'gatt-read', readAt: 1 } },
    warnings: [],
  }

  // Note: once the Control section renders, 'TX' appears BOTH as the mode
  // field and as the active segment of the mode toggle, so findByText would
  // throw on multiple matches. findAllByText is correct in both states.
  async function openTx() {
    bleApi.fetchBleDevices.mockResolvedValue(DEVICES)
    bleApi.fetchBleSnapshot.mockResolvedValue(TX_SNAPSHOT)
    render(<CintennaPanel />)
    await userEvent.click(await screen.findByRole('button', { name: /F12L - 2071/ }))
    await userEvent.click(screen.getByRole('button', { name: /read status/i }))
    await screen.findAllByText('TX')
  }

  // With the dialog open, the panel's trigger and the dialog's confirm share a
  // label. The confirm button is the last one in the DOM.
  function confirmButton(label) {
    return screen.getAllByRole('button', { name: label }).pop()
  }

  it('renders no write control when the write gate is off', async () => {
    // RELEASE GATE, inverted: the read-only build must stay read-only.
    bleApi.fetchBleCapabilities.mockResolvedValue({
      bleToolsEnabled: true, bleWriteEnabled: false,
    })
    bleApi.fetchBleDevices.mockResolvedValue(DEVICES)
    bleApi.fetchBleSnapshot.mockResolvedValue(TX_SNAPSHOT)
    render(<CintennaPanel />)
    await userEvent.click(await screen.findByRole('button', { name: /F12L - 2071/ }))
    await userEvent.click(screen.getByRole('button', { name: /read status/i }))
    // Single-match findByText on purpose here, unlike openTx(): with the gate
    // off the mode toggle must not render, so a second 'TX' would mean the
    // control leaked into the read-only build. Do not "fix" this to findAll.
    await screen.findByText('TX')
    for (const label of [/^link$/i, /^unlink$/i, /switch to/i]) {
      expect(screen.queryByRole('button', { name: label })).not.toBeInTheDocument()
    }
  })

  it('renders no write control before a status read, when the mode is unknown', async () => {
    bleApi.fetchBleCapabilities.mockResolvedValue(WRITE_ON)
    bleApi.fetchBleDevices.mockResolvedValue(DEVICES)
    render(<CintennaPanel />)
    await userEvent.click(await screen.findByRole('button', { name: /F12L - 2071/ }))
    expect(screen.queryByRole('button', { name: /^link$/i })).not.toBeInTheDocument()
  })

  it('offers Link but never Unlink on a transmitter', async () => {
    bleApi.fetchBleCapabilities.mockResolvedValue(WRITE_ON)
    await openTx()
    expect(screen.getByRole('button', { name: /^link$/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^unlink$/i })).not.toBeInTheDocument()
  })

  it('offers Unlink but never Link on a receiver', async () => {
    bleApi.fetchBleCapabilities.mockResolvedValue(WRITE_ON)
    bleApi.fetchBleDevices.mockResolvedValue(DEVICES)
    bleApi.fetchBleSnapshot.mockResolvedValue(SNAPSHOT)   // mode rx
    render(<CintennaPanel />)
    await userEvent.click(await screen.findByRole('button', { name: /F12L - 1946/ }))
    await userEvent.click(screen.getByRole('button', { name: /read status/i }))
    await screen.findAllByText('RX')
    expect(screen.getByRole('button', { name: /^unlink$/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^link$/i })).not.toBeInTheDocument()
  })

  it('confirms before writing, and sends the prepared token', async () => {
    bleApi.fetchBleCapabilities.mockResolvedValue(WRITE_ON)
    bleApi.prepareBleCommand.mockResolvedValue({
      command: 'link', token: 'tok-1', ttlS: 60, deviceAlias: 'F12L - 2071',
      currentMode: 'tx', warning: 'Any unlinked receiver in range will pair to it.',
    })
    bleApi.executeBleCommand.mockResolvedValue({
      command: 'link', attAcknowledged: true, verification: 'ack-only',
      mode: { decoded: 'tx' }, durationMs: 400,
    })
    await openTx()
    await userEvent.click(screen.getByRole('button', { name: /^link$/i }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    expect(bleApi.executeBleCommand).not.toHaveBeenCalled()

    await userEvent.click(screen.getByRole('checkbox'))
    await userEvent.click(confirmButton(/^link$/i))

    await waitFor(() => expect(bleApi.executeBleCommand).toHaveBeenCalledWith('tx-1', {
      command: 'link', expectedMode: 'tx', confirmationToken: 'tok-1',
    }))
  })

  it('never claims a link was made', async () => {
    bleApi.fetchBleCapabilities.mockResolvedValue(WRITE_ON)
    bleApi.prepareBleCommand.mockResolvedValue({
      command: 'link', token: 'tok-1', ttlS: 60, deviceAlias: 'F12L - 2071',
      currentMode: 'tx', warning: 'warning copy',
    })
    bleApi.executeBleCommand.mockResolvedValue({
      command: 'link', attAcknowledged: true, verification: 'ack-only',
      mode: { decoded: 'tx' }, durationMs: 400,
    })
    await openTx()
    await userEvent.click(screen.getByRole('button', { name: /^link$/i }))
    await userEvent.click(screen.getByRole('checkbox'))
    await userEvent.click(confirmButton(/^link$/i))

    expect(await screen.findByText(/not confirmation/i)).toBeInTheDocument()
    expect(screen.queryByText(/^linked/i)).not.toBeInTheDocument()
  })

  it('reports an accepted-but-unverified mode change as neither success nor failure', async () => {
    bleApi.fetchBleCapabilities.mockResolvedValue(WRITE_ON)
    bleApi.prepareBleCommand.mockResolvedValue({
      command: 'set_mode_rx', token: 'tok-2', ttlS: 60,
      deviceAlias: 'F12L - 2071', currentMode: 'tx', warning: 'It will restart.',
    })
    bleApi.executeBleCommand.mockResolvedValue({
      command: 'set_mode_rx', attAcknowledged: true,
      verification: 'accepted-unverified', mode: { decoded: 'tx' }, durationMs: 31000,
    })
    await openTx()
    await userEvent.click(screen.getByRole('button', { name: /switch to rx/i }))
    await userEvent.click(screen.getByRole('checkbox'))
    await userEvent.click(confirmButton(/switch to rx/i))
    expect(await screen.findByText(/accepted, but not verified/i)).toBeInTheDocument()
  })

  it('shows the operator copy when the server refuses the write', async () => {
    bleApi.fetchBleCapabilities.mockResolvedValue(WRITE_ON)
    bleApi.prepareBleCommand.mockRejectedValue({
      code: 'wrong-mode', message: 'Link is a transmitter action; Unlink is a receiver action.',
    })
    await openTx()
    await userEvent.click(screen.getByRole('button', { name: /^link$/i }))
    expect(await screen.findByText(/transmitter action/i)).toBeInTheDocument()
  })

  it('discards a stale snapshot response for a radio that is no longer selected', async () => {
    // Regression for: operator selects A, clicks Read status, switches to B
    // before A's response lands. A's data must never render under B's name.
    bleApi.fetchBleDevices.mockResolvedValue(DEVICES)
    let resolveA
    const pendingA = new Promise((resolve) => { resolveA = resolve })
    bleApi.fetchBleSnapshot.mockImplementation((osId) =>
      osId === 'rx-1' ? pendingA : Promise.resolve(SNAPSHOT))

    render(<CintennaPanel />)
    await userEvent.click(await screen.findByRole('button', { name: /F12L - 1946/ }))
    await userEvent.click(screen.getByRole('button', { name: /read status/i }))
    expect(bleApi.fetchBleSnapshot).toHaveBeenCalledWith('rx-1')

    // Switch to device B while A's read is still in flight.
    await userEvent.click(screen.getByRole('button', { name: /F12L - 2071/ }))

    // Now let A's (stale) response resolve.
    resolveA(SNAPSHOT)

    // The panel must not show A's battery/firmware attributed to B, and
    // must not get stuck showing "reading…" forever.
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /read status/i })).not.toBeDisabled()
    })
    expect(screen.queryByText(/65%/)).not.toBeInTheDocument()
    expect(screen.queryByText('1.0.7.2')).not.toBeInTheDocument()
    expect(screen.queryByText(/reading…/i)).not.toBeInTheDocument()
  })

  it('exposes aria-pressed reflecting which roster entry is selected', async () => {
    bleApi.fetchBleDevices.mockResolvedValue(DEVICES)
    render(<CintennaPanel />)
    const btnA = await screen.findByRole('button', { name: /F12L - 1946/ })
    const btnB = screen.getByRole('button', { name: /F12L - 2071/ })
    expect(btnA).toHaveAttribute('aria-pressed', 'false')
    expect(btnB).toHaveAttribute('aria-pressed', 'false')

    await userEvent.click(btnA)
    expect(btnA).toHaveAttribute('aria-pressed', 'true')
    expect(btnB).toHaveAttribute('aria-pressed', 'false')
  })

  it('flags a selected device that drops out of the roster without blanking the panel', async () => {
    const ROSTER_WITHOUT_RX1 = { deviceCount: 1, devices: [DEVICES.devices[1]] }
    bleApi.fetchBleDevices
      .mockResolvedValueOnce(DEVICES)
      .mockResolvedValue(ROSTER_WITHOUT_RX1)
    bleApi.fetchBleSnapshot.mockResolvedValue(SNAPSHOT)

    vi.useFakeTimers({ shouldAdvanceTime: true })
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    try {
      render(<CintennaPanel />)
      await user.click(await screen.findByRole('button', { name: /F12L - 1946/ }))
      await user.click(screen.getByRole('button', { name: /read status/i }))
      expect(await screen.findByText(/65%/)).toBeInTheDocument()

      // Next 5s poll returns a roster that no longer includes rx-1.
      await act(async () => { await vi.advanceTimersByTimeAsync(5000) })

      expect(await screen.findByText(/no longer nearby/i)).toBeInTheDocument()
      // The last reading stays visible — a blank panel is treated as a defect.
      expect(screen.getByText(/65%/)).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /read status/i })).toBeDisabled()
    } finally {
      vi.useRealTimers()
    }
  })
})
