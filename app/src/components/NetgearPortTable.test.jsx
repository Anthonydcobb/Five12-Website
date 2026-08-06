import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import NetgearPortTable from './NetgearPortTable'

const PORTS = [
  { port: 1, media: 'copper', linkUp: false, poe: false, trunk: 'manual',
    color: '#000000', vlans: [300, 400, 500, 600, 1] },
  { port: 3, media: 'copper', linkUp: false, poe: true, trunk: null,
    color: '#ffa600', vlans: [600], profile: 'HogNet', template: 'Data' },
  { port: 4, media: 'copper', linkUp: true, poe: true, trunk: null,
    color: '#00ff00', vlans: [300], profile: 'FixtureNet', template: 'Lighting',
    ip: '10.31.8.60', mac: '28:36:38:C0:73:63', linkSpeed: '100T Full' },
]

const device = (vendorData) => ({ macAddress: 'AA', vendorData })

describe('NetgearPortTable', () => {
  it('renders nothing when there are no switch ports', () => {
    const { container } = render(<NetgearPortTable device={device({})} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders a row per port with profile and VLAN', () => {
    render(<NetgearPortTable device={device({ netgearPorts: PORTS })} />)
    expect(screen.getByText('HogNet')).toBeTruthy()
    expect(screen.getByText('FixtureNet')).toBeTruthy()
    expect(screen.getByText('600')).toBeTruthy()
    expect(screen.getByText('10.31.8.60')).toBeTruthy()
    expect(screen.getByText('100T Full')).toBeTruthy()
  })

  it('shows a trunk as its VLAN list rather than a blank profile', () => {
    render(<NetgearPortTable device={device({ netgearPorts: PORTS })} />)
    expect(screen.getByText('300, 400, 500, 600, 1')).toBeTruthy()
    expect(screen.getByText('Trunk (manual)')).toBeTruthy()
  })

  it('explains missing host data instead of showing blank columns', () => {
    render(<NetgearPortTable device={device({
      netgearPorts: [{ port: 1, media: 'copper', linkUp: true, poe: false, trunk: null }],
      netgearPortHostsAvailable: false,
    })} />)
    expect(screen.getByText(/per-port host details were not readable/i)).toBeTruthy()
  })

  it('shows the snapshot age', () => {
    render(<NetgearPortTable device={device({
      netgearPorts: PORTS,
      netgearPortHostsAvailable: true,
      snapshotAsOf: new Date().toISOString(),
    })} />)
    // Anchored: the panel header is "SWITCH PORTS (SNAPSHOT)", so a bare
    // /snapshot/i matches two elements. Only the capture-age footer begins
    // with the word, and the footer is what this test is about.
    expect(screen.getByText(/^snapshot /i)).toBeTruthy()
  })
})
