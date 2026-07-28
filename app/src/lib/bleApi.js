// Wrapper for /api/ble/*. Those routes exist only when FIVE12_BLE_TOOLS=1, so
// a 404 is a normal state (feature off), not a failure to shout about.
import axios from 'axios'

export async function fetchBleCapabilities() {
  try {
    const { data } = await axios.get('/api/ble/capabilities')
    return data
  } catch {
    return {
      bleToolsEnabled: false,
      bleWriteEnabled: false,
      adapterAvailable: false,
      platformSupported: true,
    }
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

// The backend sends typed errors with operator-ready copy. Pass them through
// rather than replacing them with a generic message — same contract as
// fetchBleSnapshot. Note these reject with a plain object, not an Error;
// consumers read `.message`, so do NOT add instanceof Error checks against it.
function rethrowTyped(err, fallback) {
  const payload = err?.response?.data
  throw payload?.code ? payload : { code: 'unknown', message: fallback }
}

// Step one of a write. Reads the radio's real mode server-side and returns a
// single-use confirmation bound to it, plus the warning copy the dialog must
// render verbatim. Nothing is written by this call.
export async function prepareBleCommand(osId, command) {
  try {
    const { data } = await axios.post(
      `/api/ble/devices/${encodeURIComponent(osId)}/commands/prepare`,
      { command },
    )
    return data
  } catch (err) {
    rethrowTyped(err, 'Could not prepare that action.')
  }
}

// Step two. The body carries a command NAME only — never a characteristic
// UUID and never a payload byte. The server owns that mapping.
export async function executeBleCommand(osId, { command, expectedMode, confirmationToken }) {
  try {
    const { data } = await axios.post(
      `/api/ble/devices/${encodeURIComponent(osId)}/commands`,
      { command, expectedMode, confirmationToken },
    )
    return data
  } catch (err) {
    rethrowTyped(err, 'Could not complete that action.')
  }
}
