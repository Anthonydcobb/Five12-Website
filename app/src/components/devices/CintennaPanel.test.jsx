import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
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

  it('says so when scanning finds nothing', async () => {
    bleApi.fetchBleDevices.mockResolvedValue({ deviceCount: 0, devices: [] })
    render(<CintennaPanel />)
    expect(await screen.findByText(/no CRMX devices nearby/i)).toBeInTheDocument()
  })

  it('renders no control that could write to a radio', async () => {
    // RELEASE GATE for this phase.
    bleApi.fetchBleDevices.mockResolvedValue(DEVICES)
    bleApi.fetchBleSnapshot.mockResolvedValue(SNAPSHOT)
    render(<CintennaPanel />)
    await userEvent.click(await screen.findByRole('button', { name: /F12L - 1946/ }))
    for (const label of [/^link$/i, /unlink/i, /set mode/i, /apply/i]) {
      expect(screen.queryByRole('button', { name: label })).not.toBeInTheDocument()
    }
  })
})
