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
    wire({ available: false,
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
