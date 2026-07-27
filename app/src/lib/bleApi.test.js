import { describe, expect, it, vi, beforeEach } from 'vitest'
import axios from 'axios'
import { fetchBleDevices, fetchBleSnapshot, fetchBleCapabilities, signalBars } from './bleApi'

vi.mock('axios')

beforeEach(() => { vi.resetAllMocks() })

describe('bleApi', () => {
  it('fetches the device roster', async () => {
    axios.get.mockResolvedValue({ data: { deviceCount: 1, devices: [{ osId: 'a' }] } })
    const out = await fetchBleDevices()
    expect(axios.get).toHaveBeenCalledWith('/api/ble/devices')
    expect(out.devices).toHaveLength(1)
  })

  it('returns an empty roster when the backend is unreachable', async () => {
    // The BLE gate defaults off, so 404 is the NORMAL case, not an error the
    // operator should see as a crash.
    axios.get.mockRejectedValue(new Error('404'))
    expect(await fetchBleDevices()).toEqual({ deviceCount: 0, devices: [], unavailable: true })
  })

  it('encodes the device id in the snapshot URL', async () => {
    axios.get.mockResolvedValue({ data: { fields: {} } })
    await fetchBleSnapshot('AA:BB:CC:DD:EE:FF')
    expect(axios.get).toHaveBeenCalledWith('/api/ble/devices/AA%3ABB%3ACC%3ADD%3AEE%3AFF/snapshot')
  })

  it('surfaces a typed backend error from a snapshot', async () => {
    axios.get.mockRejectedValue({
      response: { data: { code: 'toolbox-holding-connection', message: 'Close Toolbox.' } },
    })
    await expect(fetchBleSnapshot('a')).rejects.toMatchObject({
      code: 'toolbox-holding-connection',
    })
  })

  it('reports capabilities as disabled when the route is absent', async () => {
    axios.get.mockRejectedValue(new Error('404'))
    expect(await fetchBleCapabilities()).toEqual({
      bleToolsEnabled: false, adapterAvailable: false, platformSupported: true,
    })
  })

  it('maps RSSI to bars without ever implying distance', () => {
    expect(signalBars(-35)).toBe(4)
    expect(signalBars(-60)).toBe(3)
    expect(signalBars(-75)).toBe(2)
    expect(signalBars(-95)).toBe(1)
    expect(signalBars(null)).toBe(0)
  })
})
