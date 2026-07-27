// Wrapper for /api/ble/*. Those routes exist only when FIVE12_BLE_TOOLS=1, so
// a 404 is a normal state (feature off), not a failure to shout about.
import axios from 'axios'

export async function fetchBleCapabilities() {
  try {
    const { data } = await axios.get('/api/ble/capabilities')
    return data
  } catch {
    return { bleToolsEnabled: false, adapterAvailable: false, platformSupported: true }
  }
}

export async function fetchBleDevices() {
  try {
    const { data } = await axios.get('/api/ble/devices')
    return data
  } catch (err) {
    // Only a genuine 404 means "the route doesn't exist because the gate is
    // off" — that's the normal, expected shape when FIVE12_BLE_TOOLS is
    // unset. Any other failure (500, network drop, stalled backend) is a
    // real error and must not be reported to the operator as a setting they
    // need to flip, since it's already correct.
    if (err?.response?.status === 404) {
      return { deviceCount: 0, devices: [], unavailable: true }
    }
    return { deviceCount: 0, devices: [], error: true }
  }
}

export async function fetchBleSnapshot(osId) {
  try {
    const { data } = await axios.get(`/api/ble/devices/${encodeURIComponent(osId)}/snapshot`)
    return data
  } catch (err) {
    // The backend sends typed errors with operator-ready copy; pass them
    // through rather than replacing them with a generic message.
    const payload = err?.response?.data
    throw payload?.code ? payload : { code: 'unknown', message: 'Could not read this device.' }
  }
}

// RSSI → 0-4 bars. Deliberately NOT a distance: signal strength depends on
// orientation, obstruction, and antenna, so the UI shows bars and raw dBm only.
export function signalBars(rssi) {
  if (typeof rssi !== 'number') return 0
  if (rssi >= -50) return 4
  if (rssi >= -65) return 3
  if (rssi >= -80) return 2
  return 1
}
