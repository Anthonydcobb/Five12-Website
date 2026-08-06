import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import NetgearProfilesTable from './NetgearProfilesTable'

const PROFILES = [
  { name: 'HogNet', template: 'Data', vlan: 600, portCount: 3, color: '#ffa600' },
  { name: 'FixtureNet', template: 'Lighting', vlan: 300, portCount: 8, color: '#00ff00' },
]

const device = (vendorData) => ({ macAddress: 'AA', vendorData })

describe('NetgearProfilesTable', () => {
  it('renders nothing when there are no profiles', () => {
    const absent = render(<NetgearProfilesTable device={device({})} />)
    expect(absent.container).toBeEmptyDOMElement()

    const empty = render(<NetgearProfilesTable device={device({ profiles: [] })} />)
    expect(empty.container).toBeEmptyDOMElement()
  })

  it('renders a row per profile with name, template, VLAN and port count', () => {
    render(<NetgearProfilesTable device={device({ profiles: PROFILES })} />)
    expect(screen.getByText('HogNet')).toBeTruthy()
    expect(screen.getByText('Data')).toBeTruthy()
    expect(screen.getByText('600')).toBeTruthy()
    expect(screen.getByText('3')).toBeTruthy()
    expect(screen.getByText('FixtureNet')).toBeTruthy()
    expect(screen.getByText('Lighting')).toBeTruthy()
    expect(screen.getByText('300')).toBeTruthy()
    expect(screen.getByText('8')).toBeTruthy()
  })

  it('shows the capture age when a snapshot time is present', () => {
    render(<NetgearProfilesTable device={device({
      profiles: PROFILES,
      snapshotAsOf: new Date().toISOString(),
    })} />)
    expect(screen.getByText(/^snapshot /i)).toBeTruthy()
  })

  it('shows time unknown rather than a blank or a bogus date when the snapshot time is missing', () => {
    render(<NetgearProfilesTable device={device({ profiles: PROFILES })} />)
    expect(screen.getByText(/time unknown/i)).toBeTruthy()
  })
})
