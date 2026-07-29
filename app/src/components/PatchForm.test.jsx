import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import PatchForm from './PatchForm'

const PROFILE = {
  id: 42,
  fixture: 'SkyPanel S60-C Mode 1',
  displayName: 'ARRI — SkyPanel S60-C Mode 1',
  manufacturer: 'ARRI',
  channelCount: 12,
  wattage: null,
  weight: null,
  firmware: null,
  notes: null,
  libraryType: 'type',
  isPatchable: true,
}

function apiResponse(data, ok = true) {
  return { ok, status: ok ? 200 : 500, json: vi.fn().mockResolvedValue(data) }
}

afterEach(() => vi.restoreAllMocks())

describe('PatchForm fixture-library search', () => {
  it('debounces server search, shows unknown metadata, and patches a disambiguated name', async () => {
    global.fetch = vi.fn().mockResolvedValue(apiResponse({
      items: [PROFILE], total: 21625, limit: 200, offset: 0,
    }))
    const onPatch = vi.fn()
    const onClose = vi.fn()
    const user = userEvent.setup()

    render(<PatchForm onPatch={onPatch} onClose={onClose} />)

    expect(await screen.findByText('ARRI — SkyPanel S60-C Mode 1')).toBeInTheDocument()
    expect(screen.getByText(/Showing the first 200 of 21,625/)).toBeInTheDocument()

    const search = screen.getByPlaceholderText(/search manufacturer or profile/i)
    await user.clear(search)
    await user.type(search, 'arri')
    await waitFor(() => {
      expect(global.fetch.mock.calls.some(([url]) => url.includes('q=arri'))).toBe(true)
    })

    await user.click(screen.getByText('ARRI — SkyPanel S60-C Mode 1'))
    expect(screen.getByText('Wattage: Unknown')).toBeInTheDocument()
    expect(screen.getByText('Weight: Unknown')).toBeInTheDocument()
    await user.type(screen.getByPlaceholderText('e.g. 101'), '101')
    await user.click(screen.getByRole('button', { name: /^patch$/i }))

    expect(onPatch).toHaveBeenCalledWith(expect.objectContaining({
      fixtureNumber: '101',
      fixture: expect.objectContaining({
        id: 42,
        fixture: 'ARRI — SkyPanel S60-C Mode 1',
        wattage: null,
        weight: null,
      }),
    }))
    expect(onClose).toHaveBeenCalled()
  })

  it('cancels stale searches and shows actionable API errors', async () => {
    global.fetch = vi.fn().mockResolvedValue(apiResponse({ error: 'Catalog unavailable' }, false))
    render(<PatchForm onPatch={vi.fn()} onClose={vi.fn()} />)
    expect(await screen.findByText('Catalog unavailable')).toBeInTheDocument()
  })
})
