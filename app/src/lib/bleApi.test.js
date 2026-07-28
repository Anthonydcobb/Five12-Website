import { describe, expect, it, vi, beforeEach } from 'vitest'
import axios from 'axios'
import {
  executeBleCommand,
  fetchBleDevices,
  fetchBleSnapshot,
  fetchBleCapabilities,
  prepareBleCommand,
  signalBars,
} from './bleApi'

vi.mock('axios')

beforeEach(() => { vi.resetAllMocks() })

describe('bleApi', () => {
  it('fetches the device roster', async () => {
    axios.get.mockResolvedValue({ data: { deviceCount: 1, devices: [{ osId: 'a' }] } })
    const out = await fetchBleDevices()
    expect(axios.get).toHaveBeenCalledWith('/api/ble/devices')
    expect(out.devices).toHaveLength(1)
  })

  it('returns an empty roster with unavailable:true on a genuine 404', async () => {
    // The BLE gate defaults off, so a 404 (route doesn't exist) is the
    // NORMAL case, not an error the operator should see as a crash.
    axios.get.mockRejectedValue({ response: { status: 404 } })
    expect(await fetchBleDevices()).toEqual({ deviceCount: 0, devices: [], unavailable: true })
  })

  it('returns an empty roster with error:true (not unavailable) on a 500', async () => {
    // A real backend failure must not be reported as "the feature is
    // switched off" — that would send the operator to flip a setting that
    // is already correct.
    axios.get.mockRejectedValue({ response: { status: 500 } })
    expect(await fetchBleDevices()).toEqual({ deviceCount: 0, devices: [], error: true })
  })

  it('returns the error state (not unavailable) on a network drop', async () => {
    // No response at all — e.g. a stalled backend — is not a 404 either.
    axios.get.mockRejectedValue(new Error('Network Error'))
    expect(await fetchBleDevices()).toEqual({ deviceCount: 0, devices: [], error: true })
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
    expect(await fetchBleCapabilities()).toMatchObject({
      bleToolsEnabled: false, adapterAvailable: false, platformSupported: true, bleWriteEnabled: false,
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

describe('prepareBleCommand', () => {
  it('posts only the command name', async () => {
    axios.post.mockResolvedValue({ data: { token: 't', currentMode: 'tx' } })
    await prepareBleCommand('tx-1', 'link')
    expect(axios.post).toHaveBeenCalledWith(
      '/api/ble/devices/tx-1/commands/prepare',
      { command: 'link' },
    )
  })

  it('encodes an os id containing a colon', async () => {
    axios.post.mockResolvedValue({ data: {} })
    await prepareBleCommand('AA:BB:CC', 'link')
    expect(axios.post.mock.calls[0][0]).toBe(
      '/api/ble/devices/AA%3ABB%3ACC/commands/prepare')
  })

  it('rethrows the backend typed error so the operator sees its copy', async () => {
    axios.post.mockRejectedValue({
      response: { data: { code: 'wrong-mode', message: 'Link is a transmitter action.' } },
    })
    await expect(prepareBleCommand('rx-1', 'link')).rejects.toMatchObject({
      code: 'wrong-mode',
    })
  })

  it('falls back to a generic typed error when the backend sends nothing usable', async () => {
    axios.post.mockRejectedValue(new Error('network down'))
    await expect(prepareBleCommand('tx-1', 'link')).rejects.toMatchObject({
      code: 'unknown',
    })
  })
})

describe('executeBleCommand', () => {
  it('sends the command, expected mode and confirmation', async () => {
    axios.post.mockResolvedValue({ data: { attAcknowledged: true } })
    await executeBleCommand('tx-1', {
      command: 'link', expectedMode: 'tx', confirmationToken: 'tok',
    })
    expect(axios.post).toHaveBeenCalledWith('/api/ble/devices/tx-1/commands', {
      command: 'link', expectedMode: 'tx', confirmationToken: 'tok',
    })
  })

  it('never sends a uuid or a payload', async () => {
    axios.post.mockResolvedValue({ data: {} })
    await executeBleCommand('tx-1', {
      command: 'link', expectedMode: 'tx', confirmationToken: 'tok',
    })
    const body = axios.post.mock.calls[0][1]
    expect(Object.keys(body).sort()).toEqual(
      ['command', 'confirmationToken', 'expectedMode'])
  })
})
