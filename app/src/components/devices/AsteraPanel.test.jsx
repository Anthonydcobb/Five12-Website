import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import AsteraPanel from './AsteraPanel'
import axios from 'axios'

vi.mock('axios')

const REAL_STATUS = {
  available: true,
  simulated: false,
  protocolVerified: false,
  appOnline: true,
  appVersion: '13.18',
  platform: 'Android',
  bridge: { name: 'ART7 90210', batteryPct: 82 },
  radioPinAlias: 'PIN-3F2A',
  targets: [
    { id: 1, name: 'Key Tubes', selected: true, brightnessPct: 80 },
    { id: 2, name: 'BG NYX', selected: false, brightnessPct: 45 },
  ],
  targetCount: 2,
  alerts: [],
}

function wire(status, history = []) {
  axios.get.mockImplementation((url) =>
    url.includes('/history')
      ? Promise.resolve({ data: history })
      : Promise.resolve({ data: status }))
}

beforeEach(() => {
  vi.resetAllMocks()
})

describe('AsteraPanel', () => {
  it('renders the disabled gate state without implying a search happened', async () => {
    wire({ available: false, disabled: true,
           reason: 'Astera tools disabled — set FIVE12_ASTERA_TOOLS=1 to enable',
           alerts: [] })
    render(<AsteraPanel />)
    expect(await screen.findByText(/Astera tools disabled/)).toBeInTheDocument()
    expect(screen.queryByText(/not found/i)).toBeNull()
    expect(screen.queryByText(/unreachable/i)).toBeNull()
  })

  it('shows bridge identity, battery, and the PIN alias — never a raw PIN', async () => {
    wire(REAL_STATUS)
    render(<AsteraPanel />)
    expect(await screen.findByText('ART7 90210')).toBeInTheDocument()
    expect(screen.getByText(/82/)).toBeInTheDocument()
    expect(screen.getByText('PIN-3F2A')).toBeInTheDocument()
  })

  it('labels real reads as protocol-unverified', async () => {
    wire(REAL_STATUS)
    render(<AsteraPanel />)
    expect(await screen.findByText(/unverified/i)).toBeInTheDocument()
  })

  it('labels simulated data loudly and does not call it unverified', async () => {
    wire({ ...REAL_STATUS, simulated: true, protocolVerified: false })
    render(<AsteraPanel />)
    expect(await screen.findByText(/simulated/i)).toBeInTheDocument()
    expect(screen.queryByText(/unverified/i)).toBeNull()
  })

  it('lists targets with brightness and selection', async () => {
    wire(REAL_STATUS)
    render(<AsteraPanel />)
    expect(await screen.findByText('Key Tubes')).toBeInTheDocument()
    expect(screen.getByText('BG NYX')).toBeInTheDocument()
    expect(screen.getByText(/80%/)).toBeInTheDocument()
  })

  it('shows the failure reason instead of stale-looking data', async () => {
    wire({ available: false, reason: 'refused redirect (HTTP 302)', alerts: [] })
    render(<AsteraPanel />)
    expect(await screen.findByText(/refused redirect/)).toBeInTheDocument()
  })
})

// ── Hermes review 2026-08-03 ────────────────────────────────────────────────

describe('AsteraPanel — unknown vs known-negative state (W2)', () => {
  it('renders an absent appOnline as unknown, not offline', async () => {
    wire({ ...REAL_STATUS, appOnline: null })
    render(<AsteraPanel />)
    expect(await screen.findByText(/app unknown/i)).toBeInTheDocument()
    expect(screen.queryByText(/app offline/i)).toBeNull()
  })

  it('still renders a real false as offline', async () => {
    wire({ ...REAL_STATUS, appOnline: false })
    render(<AsteraPanel />)
    expect(await screen.findByText(/app offline/i)).toBeInTheDocument()
  })

  it('renders an absent bridge battery as unknown, not zero', async () => {
    wire({ ...REAL_STATUS, bridge: { name: 'ART7 90210', batteryPct: null } })
    render(<AsteraPanel />)
    expect(await screen.findByText('ART7 90210')).toBeInTheDocument()
    expect(await screen.findByText(/bridge battery unknown/i)).toBeInTheDocument()
  })
})

describe('AsteraPanel — disabled is not unavailable (S2 copy)', () => {
  it('does not use the searched-and-failed wording for the gate-off state', async () => {
    wire({ available: false, disabled: true,
           reason: 'Astera tools disabled — set FIVE12_ASTERA_TOOLS=1 to enable',
           alerts: [] })
    render(<AsteraPanel />)
    expect(await screen.findByText(/Astera tools disabled/)).toBeInTheDocument()
    expect(screen.queryByText(/device unavailable/i)).toBeNull()
  })

  it('still says unavailable when a real read actually failed', async () => {
    wire({ available: false, reason: 'refused redirect (HTTP 302)', alerts: [] })
    render(<AsteraPanel />)
    expect(await screen.findByText(/device unavailable/i)).toBeInTheDocument()
  })
})
