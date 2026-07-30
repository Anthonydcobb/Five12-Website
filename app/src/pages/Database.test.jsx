import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Database from './Database'

const FIXTURES = [
  {
    id: 1,
    fixture: 'SkyPanel S60-C Mode 1',
    displayName: 'ARRI — SkyPanel S60-C Mode 1',
    manufacturer: 'ARRI',
    channelCount: 12,
    libraryType: 'type',
    wattage: null,
    weight: null,
    firmware: null,
    notes: null,
  },
]

const STATUS = {
  fixtureCount: 1, source: 'Hog 5', version: '5.0.766', catalogChecksum: 'catalog-sha256',
}
const BACKUPS = [
  { id: 7, fixtureCount: 4, reason: 'Before importing Hog 5', source: null, version: null },
]

function response(data, ok = true, status = 200) {
  return { ok, status, json: vi.fn().mockResolvedValue(data) }
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function installFetch(importResult = null, restoreResult = null, updateResult = null) {
  global.fetch = vi.fn((url, options = {}) => {
    if (url.startsWith('/api/fixture-library/catalog?')) {
      return Promise.resolve(response({ items: FIXTURES, total: FIXTURES.length, limit: 500, offset: 0 }))
    }
    if (url === '/api/fixture-library/status') return Promise.resolve(response(STATUS))
    if (url === '/api/fixture-library/backups') return Promise.resolve(response(BACKUPS))
    if (url === '/api/fixture-library/hog/preview') {
      return Promise.resolve(response({
        version: '5.0.766', fixtureCount: 29936, manufacturers: 519,
        patchable: 21625, unsupported: 8311, currentCount: 4,
        previewToken: 'signed-preview',
      }))
    }
    if (url === '/api/fixture-library/hog/import') return Promise.resolve(response(importResult, true, 201))
    if (url === '/api/fixture-library/backups/7/restore') return Promise.resolve(response(restoreResult))
    if (url === '/api/fixtures/1' && options.method === 'PUT') {
      return Promise.resolve(response(updateResult))
    }
    throw new Error(`Unexpected fetch: ${url}`)
  })
}

beforeEach(() => {
  vi.spyOn(window, 'confirm').mockReturnValue(true)
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Database fixture-library safety UI', () => {
  it('shows the active library and exposes download plus restore for saved backups', async () => {
    installFetch()
    render(<Database />)

    expect(await screen.findByText(/Hog 5 5\.0\.766/)).toBeInTheDocument()
    expect(screen.getByText('#7 · 4 fixtures')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /download json/i })).toHaveAttribute(
      'href', '/api/fixture-library/backups/7/download'
    )
    expect(screen.getByRole('button', { name: /^restore$/i })).toBeInTheDocument()
  })

  it('requires operator confirmation and sends the selected XML with the replace flag', async () => {
    const result = {
      imported: 29936,
      manufacturers: 519,
      version: '5.0.766',
      backup: { id: 8, fixtureCount: 4 },
    }
    installFetch(result)
    render(<Database />)
    await screen.findByText(/Hog 5 5\.0\.766/)

    const file = new File(['<library/>'], 'summary.xml', { type: 'application/xml' })
    await userEvent.upload(screen.getByLabelText(/replace with hog summary\.xml/i), file)

    expect(window.confirm).toHaveBeenCalledWith(expect.stringMatching(/backup/i))
    await waitFor(() => {
      const call = global.fetch.mock.calls.find(([url]) => url === '/api/fixture-library/hog/import')
      expect(call).toBeTruthy()
      expect(call[1].method).toBe('POST')
      expect(call[1].body).toBeInstanceOf(FormData)
      expect(call[1].body.get('confirmReplace')).toBe('true')
      expect(call[1].body.get('previewToken')).toBe('signed-preview')
      expect(call[1].body.get('file').name).toBe('summary.xml')
    })
    expect(await screen.findByText(/Imported 29,936 Hog 5\.0\.766 profiles/)).toBeInTheDocument()
  })

  it('backs up the current catalog again before restoring an older snapshot', async () => {
    const restoreResult = {
      restored: 4,
      rollbackBackup: { id: 9, fixtureCount: 29936 },
    }
    installFetch(null, restoreResult)
    render(<Database />)
    await screen.findByText('#7 · 4 fixtures')

    await userEvent.click(screen.getByRole('button', { name: /^restore$/i }))

    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('back up the current catalog'))
    await waitFor(() => {
      const call = global.fetch.mock.calls.find(
        ([url]) => url === '/api/fixture-library/backups/7/restore'
      )
      expect(JSON.parse(call[1].body)).toEqual({
        confirmReplace: true,
        expectedCatalogChecksum: 'catalog-sha256',
      })
    })
    expect(await screen.findByText(/saved as backup #9/)).toBeInTheDocument()
  })

  it('saves fixture edits on blur and uses the authoritative server row', async () => {
    const saved = {
      ...FIXTURES[0], fixture: 'Custom SkyPanel', displayName: 'Custom SkyPanel',
      manufacturer: null, libraryType: null, librarySource: null,
    }
    installFetch(null, null, saved)
    render(<Database />)
    const input = await screen.findByDisplayValue('SkyPanel S60-C Mode 1')

    await userEvent.clear(input)
    await userEvent.type(input, 'Custom SkyPanel')
    expect(global.fetch.mock.calls.some(([, options]) => options?.method === 'PUT')).toBe(false)
    await userEvent.tab()

    await waitFor(() => {
      const call = global.fetch.mock.calls.find(([, options]) => options?.method === 'PUT')
      expect(JSON.parse(call[1].body).fixture).toBe('Custom SkyPanel')
    })
    expect(await screen.findByDisplayValue('Custom SkyPanel')).toBeInTheDocument()
  })

  it('identifies a metadata transport failure and clears it after retry succeeds', async () => {
    let backupAttempts = 0
    global.fetch = vi.fn((url) => {
      if (url.startsWith('/api/fixture-library/catalog?')) {
        return Promise.resolve(response({ items: FIXTURES, total: 1, limit: 500, offset: 0 }))
      }
      if (url === '/api/fixture-library/status') return Promise.resolve(response(STATUS))
      if (url === '/api/fixture-library/backups') {
        backupAttempts += 1
        if (backupAttempts === 1) {
          return Promise.reject(new TypeError('NetworkError when attempting to fetch resource.'))
        }
        return Promise.resolve(response(BACKUPS))
      }
      throw new Error(`Unexpected fetch: ${url}`)
    })

    render(<Database />)

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Fixture backup list could not reach the Five12 backend')
    expect(alert).toHaveTextContent('NetworkError when attempting to fetch resource.')

    await userEvent.click(screen.getByRole('button', { name: /retry fixture data/i }))

    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
    expect(screen.getByText('#7 · 4 fixtures')).toBeInTheDocument()
  })

  it('labels an HTTP error without misreporting it as a transport failure', async () => {
    global.fetch = vi.fn((url) => {
      if (url.startsWith('/api/fixture-library/catalog?')) {
        return Promise.resolve(response({ items: FIXTURES, total: 1, limit: 500, offset: 0 }))
      }
      if (url === '/api/fixture-library/status') return Promise.resolve(response(STATUS))
      if (url === '/api/fixture-library/backups') {
        return Promise.resolve(response({ error: 'Database temporarily unavailable' }, false, 503))
      }
      throw new Error(`Unexpected fetch: ${url}`)
    })

    render(<Database />)

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(
      'Fixture backup list failed (503): Database temporarily unavailable'
    )
    expect(alert).not.toHaveTextContent('could not reach the Five12 backend')
  })

  it('preserves a successful import message when the follow-up catalog refresh fails', async () => {
    let importCompleted = false
    global.fetch = vi.fn((url) => {
      if (url.startsWith('/api/fixture-library/catalog?')) {
        if (importCompleted) {
          return Promise.reject(new TypeError('NetworkError when attempting to fetch resource.'))
        }
        return Promise.resolve(response({ items: FIXTURES, total: 1, limit: 500, offset: 0 }))
      }
      if (url === '/api/fixture-library/status') return Promise.resolve(response(STATUS))
      if (url === '/api/fixture-library/backups') return Promise.resolve(response(BACKUPS))
      if (url === '/api/fixture-library/hog/preview') {
        return Promise.resolve(response({
          version: '5.0.766', fixtureCount: 29936, manufacturers: 519,
          patchable: 21625, unsupported: 8311, currentCount: 1,
          previewToken: 'signed-preview',
        }))
      }
      if (url === '/api/fixture-library/hog/import') {
        importCompleted = true
        return Promise.resolve(response({
          imported: 29936, manufacturers: 519, version: '5.0.766',
          backup: { id: 8, fixtureCount: 1 },
        }, true, 201))
      }
      throw new Error(`Unexpected fetch: ${url}`)
    })

    render(<Database />)
    await screen.findByText(/Hog 5 5\.0\.766/)

    const file = new File(['<library/>'], 'summary.xml', { type: 'application/xml' })
    await userEvent.upload(screen.getByLabelText(/replace with hog summary\.xml/i), file)

    expect(await screen.findByText(/Imported 29,936 Hog 5\.0\.766 profiles/)).toBeInTheDocument()
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Fixture catalog could not reach the Five12 backend'
    )
  })

  it('preserves a successful restore message when the follow-up catalog refresh fails', async () => {
    let restoreCompleted = false
    global.fetch = vi.fn((url) => {
      if (url.startsWith('/api/fixture-library/catalog?')) {
        if (restoreCompleted) {
          return Promise.reject(new TypeError('NetworkError when attempting to fetch resource.'))
        }
        return Promise.resolve(response({ items: FIXTURES, total: 1, limit: 500, offset: 0 }))
      }
      if (url === '/api/fixture-library/status') return Promise.resolve(response(STATUS))
      if (url === '/api/fixture-library/backups') return Promise.resolve(response(BACKUPS))
      if (url === '/api/fixture-library/backups/7/restore') {
        restoreCompleted = true
        return Promise.resolve(response({ restored: 4, rollbackBackup: { id: 9 } }))
      }
      throw new Error(`Unexpected fetch: ${url}`)
    })

    render(<Database />)
    await screen.findByText('#7 · 4 fixtures')
    await userEvent.click(screen.getByRole('button', { name: /^restore$/i }))

    expect(await screen.findByText(/Restored 4 fixtures/)).toBeInTheDocument()
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Fixture catalog could not reach the Five12 backend'
    )
  })

  it('does not let an older retry overwrite a newer search result', async () => {
    const pendingRetry = deferred()
    let emptyQueryCalls = 0
    const newerFixture = { ...FIXTURES[0], id: 2, fixture: 'ARRI newer result' }
    const olderFixture = { ...FIXTURES[0], id: 3, fixture: 'Older retry result' }

    global.fetch = vi.fn((url) => {
      if (url === '/api/fixture-library/status') return Promise.resolve(response(STATUS))
      if (url === '/api/fixture-library/backups') return Promise.resolve(response(BACKUPS))
      if (url.startsWith('/api/fixture-library/catalog?')) {
        const query = new URL(url, 'http://localhost').searchParams.get('q')
        if (query === 'ARRI') {
          return Promise.resolve(response({ items: [newerFixture], total: 1, limit: 500, offset: 0 }))
        }
        emptyQueryCalls += 1
        if (emptyQueryCalls === 1) {
          return Promise.reject(new TypeError('NetworkError when attempting to fetch resource.'))
        }
        return pendingRetry.promise
      }
      throw new Error(`Unexpected fetch: ${url}`)
    })

    render(<Database />)
    await screen.findByRole('alert')

    await userEvent.click(screen.getByRole('button', { name: /retry fixture data/i }))
    await userEvent.type(screen.getByRole('searchbox'), 'ARRI')

    expect(await screen.findByDisplayValue('ARRI newer result')).toBeInTheDocument()
    pendingRetry.resolve(response({ items: [olderFixture], total: 1, limit: 500, offset: 0 }))

    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
    expect(screen.getByDisplayValue('ARRI newer result')).toBeInTheDocument()
    expect(screen.queryByDisplayValue('Older retry result')).not.toBeInTheDocument()
  })
})
