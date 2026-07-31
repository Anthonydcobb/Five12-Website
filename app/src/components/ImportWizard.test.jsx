import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ImportWizard from './ImportWizard'

function response(data, ok = true, status = 200) {
  return {
    ok,
    status,
    text: vi.fn().mockResolvedValue(JSON.stringify(data)),
  }
}

function deferred() {
  let resolve
  const promise = new Promise(resolvePromise => { resolve = resolvePromise })
  return { promise, resolve }
}

const analysis = {
  rowCount: 3,
  headerRowIndex: 0,
  theirColumns: ['Fixture Type', 'DMX Addr', 'Ch'],
  suggestedMapping: {
    'Fixture Type': 'type',
    'DMX Addr': 'address',
    Ch: 'channelCount',
  },
  previewRows: [{ 'Fixture Type': 'ARRI SkyPanel S60-C Mode 6', 'DMX Addr': 1, Ch: 20 }],
}

const exactProfile = {
  id: 1,
  fixture: 'SkyPanel S60-C Mode 6',
  displayName: 'ARRI — SkyPanel S60-C Mode 6',
  manufacturer: 'ARRI',
  channelCount: 20,
  exact: true,
  score: 1,
}

const matchGroups = [
  {
    key: '["arri skypanel s60-c mode 6",20]',
    sourceType: 'ARRI SkyPanel S60-C Mode 6',
    channelCount: 20,
    rowCount: 2,
    suggestions: [exactProfile],
    selectedFixtureId: 1,
  },
  {
    key: '["mystery panel",12]',
    sourceType: 'Mystery Panel',
    channelCount: 12,
    rowCount: 1,
    suggestions: [],
    selectedFixtureId: null,
  },
]

function installBaseFetch(extraHandler = null, groups = matchGroups) {
  global.fetch = vi.fn((url, options = {}) => {
    if (url === '/api/patch-sheets/7/import/analyze') return Promise.resolve(response(analysis))
    if (extraHandler) {
      const handled = extraHandler(url, options)
      if (handled) return handled
    }
    if (url === '/api/patch-sheets/7/import/matches') {
      return Promise.resolve(response({ groups }))
    }
    if (url === '/api/patch-sheets/7/import/commit') {
      return Promise.resolve(response({ inserted: 3, matchedRows: 2, unmatchedRows: 1, skipped: 0 }))
    }
    throw new Error(`Unexpected fetch: ${url}`)
  })
}

async function uploadAndReview(expectedFixture = 'ARRI SkyPanel S60-C Mode 6') {
  const file = new File(
    ['Fixture Type,DMX Addr,Ch\nARRI SkyPanel S60-C Mode 6,1,20\n'],
    'patch.csv',
    { type: 'text/csv' },
  )
  await userEvent.upload(screen.getByLabelText(/choose an .*patch sheet/i), file)
  expect(await screen.findByText(/3 rows .* header row 1/i)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: /review fixture matches/i }))
  expect(await screen.findByText(expectedFixture)).toBeInTheDocument()
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('ImportWizard fixture matching', () => {
  it('preselects exact matches and requires explicit acknowledgement of unmatched fixtures', async () => {
    const onImported = vi.fn()
    installBaseFetch()
    render(<ImportWizard patchId={7} onClose={vi.fn()} onImported={onImported} />)

    await uploadAndReview()

    expect(screen.getByText('Exact match')).toBeInTheDocument()
    expect(screen.getByText('Mystery Panel')).toBeInTheDocument()
    expect(screen.getByText(/not matched/i)).toBeInTheDocument()
    const importButton = screen.getByRole('button', { name: /import 3 rows/i })
    expect(importButton).toBeDisabled()

    await userEvent.click(screen.getByRole('button', { name: /keep mystery panel unmatched/i }))
    expect(importButton).toBeEnabled()
    const closeButton = screen.getByRole('button', { name: /close import/i })
    closeButton.focus()
    await userEvent.tab({ shift: true })
    expect(importButton).toHaveFocus()
    await userEvent.click(importButton)

    await waitFor(() => expect(onImported).toHaveBeenCalledWith({
      inserted: 3, matchedRows: 2, unmatchedRows: 1, skipped: 0,
    }))
    const commitCall = global.fetch.mock.calls.find(([url]) => url.endsWith('/import/commit'))
    expect(JSON.parse(commitCall[1].body.get('fixtureSelections'))).toEqual({
      '["arri skypanel s60-c mode 6",20]': 1,
      '["mystery panel",12]': null,
    })
  })

  it('locks mapping while fixture match review is in flight', async () => {
    const pending = deferred()
    installBaseFetch((url) => {
      if (url === '/api/patch-sheets/7/import/matches') return pending.promise
      return null
    })
    render(<ImportWizard patchId={7} onClose={vi.fn()} onImported={vi.fn()} />)
    const file = new File(
      ['Fixture Type,DMX Addr,Ch\nARRI SkyPanel S60-C Mode 6,1,20\n'],
      'patch.csv',
      { type: 'text/csv' },
    )
    await userEvent.upload(screen.getByLabelText(/choose an .*patch sheet/i), file)
    expect(await screen.findByText(/3 rows .* header row 1/i)).toBeInTheDocument()

    const fixtureMapping = screen.getByLabelText('Map Fixture Type')
    expect(fixtureMapping).toBeEnabled()
    await userEvent.click(screen.getByRole('button', { name: /review fixture matches/i }))
    expect(fixtureMapping).toBeDisabled()

    pending.resolve(response({ groups: matchGroups }))
    expect(await screen.findByText('Mystery Panel')).toBeInTheDocument()
  })

  it('does not allow dismissal while the patch import commit is in flight', async () => {
    const pending = deferred()
    const onClose = vi.fn()
    const onImported = vi.fn()
    installBaseFetch((url) => {
      if (url === '/api/patch-sheets/7/import/commit') return pending.promise
      return null
    })
    render(<ImportWizard patchId={7} onClose={onClose} onImported={onImported} />)
    await uploadAndReview()

    await userEvent.click(screen.getByRole('button', { name: /keep mystery panel unmatched/i }))
    await userEvent.click(screen.getByRole('button', { name: /add mystery panel to fixture database/i }))
    const createButton = screen.getByRole('button', { name: /create and select fixture/i })
    expect(createButton).toBeEnabled()
    await userEvent.click(screen.getByRole('button', { name: /import 3 rows/i }))
    expect(screen.getByRole('button', { name: /close import/i })).toBeDisabled()
    expect(createButton).toBeDisabled()
    expect(screen.getByRole('button', { name: /keep mystery panel unmatched/i })).toBeDisabled()
    await userEvent.keyboard('{Escape}')
    expect(onClose).not.toHaveBeenCalled()

    const result = { inserted: 3, matchedRows: 2, unmatchedRows: 1, skipped: 0 }
    pending.resolve(response(result))
    await waitFor(() => expect(onImported).toHaveBeenCalledWith(result))
  })

  it('searches the catalog and only allows a profile with the imported footprint', async () => {
    const compatible = {
      id: 8,
      fixture: 'Mystery Panel Mode A',
      displayName: 'Vendor — Mystery Panel Mode A',
      manufacturer: 'Vendor',
      channelCount: 12,
    }
    const incompatible = { ...compatible, id: 9, fixture: 'Mystery Panel Mode B', channelCount: 10,
      displayName: 'Vendor — Mystery Panel Mode B' }
    installBaseFetch((url) => {
      if (url.startsWith('/api/fixture-library/patch-profiles?')) {
        return Promise.resolve(response({ items: [compatible, incompatible] }))
      }
      return null
    })
    render(<ImportWizard patchId={7} onClose={vi.fn()} onImported={vi.fn()} />)
    await uploadAndReview()

    const search = screen.getByLabelText(/search profile for mystery panel/i)
    await userEvent.clear(search)
    await userEvent.type(search, 'Mystery mode')
    await userEvent.click(screen.getByRole('button', { name: /search library for mystery panel/i }))

    const goodButton = await screen.findByRole('button', { name: /choose vendor .* mystery panel mode a/i })
    const badButton = screen.getByRole('button', { name: /vendor .* mystery panel mode b .* footprint mismatch/i })
    expect(badButton).toBeDisabled()
    await userEvent.click(goodButton)
    expect(screen.getByText(/selected: vendor .* mystery panel mode a/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /import 3 rows/i })).toBeEnabled()
  })

  it('does not show an old search response after the operator changes the query', async () => {
    const pending = deferred()
    installBaseFetch((url) => {
      if (url.startsWith('/api/fixture-library/patch-profiles?')) return pending.promise
      return null
    })
    render(<ImportWizard patchId={7} onClose={vi.fn()} onImported={vi.fn()} />)
    await uploadAndReview()

    const search = screen.getByLabelText(/search profile for mystery panel/i)
    await userEvent.click(screen.getByRole('button', { name: /search library for mystery panel/i }))
    await userEvent.clear(search)
    await userEvent.type(search, 'new query')
    pending.resolve(response({ items: [{
      id: 99, fixture: 'Old Result', displayName: 'Vendor — Old Result', channelCount: 12,
    }] }))

    await waitFor(() => expect(search).toHaveValue('new query'))
    expect(screen.queryByText(/vendor .* old result/i)).not.toBeInTheDocument()
  })

  it('keeps profiles with a missing imported footprint unmatched', async () => {
    const noFootprintGroups = [{
      key: '["unknown profile",null]', sourceType: 'Unknown Profile', channelCount: null,
      rowCount: 1, suggestions: [], selectedFixtureId: null,
    }]
    const candidate = {
      id: 81, fixture: 'Unknown Profile', displayName: 'Vendor — Unknown Profile',
      manufacturer: 'Vendor', channelCount: 12,
    }
    installBaseFetch((url) => {
      if (url.startsWith('/api/fixture-library/patch-profiles?')) {
        return Promise.resolve(response({ items: [candidate] }))
      }
      return null
    }, noFootprintGroups)
    render(<ImportWizard patchId={7} onClose={vi.fn()} onImported={vi.fn()} />)
    await uploadAndReview('Unknown Profile')

    expect(screen.getByRole('button', {
      name: /cannot add unknown profile; imported channel count is missing/i,
    })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: /search library for unknown profile/i }))
    expect(await screen.findByRole('button', {
      name: /vendor .* unknown profile .* imported footprint missing/i,
    })).toBeDisabled()
    expect(screen.getByRole('button', { name: /import 3 rows/i })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: /keep unknown profile unmatched/i }))
    expect(screen.getByRole('button', { name: /import 3 rows/i })).toBeEnabled()
  })

  it('creates a custom fixture and selects it for the imported group', async () => {
    const custom = {
      id: 44,
      fixture: 'Mystery Panel',
      displayName: 'Indie Light Co — Mystery Panel',
      manufacturer: 'Indie Light Co',
      channelCount: 12,
      librarySource: null,
    }
    installBaseFetch((url, options) => {
      if (url === '/api/fixtures' && options.method === 'POST') {
        return Promise.resolve(response(custom, true, 201))
      }
      return null
    })
    render(<ImportWizard patchId={7} onClose={vi.fn()} onImported={vi.fn()} />)
    await uploadAndReview()

    await userEvent.click(screen.getByRole('button', { name: /add mystery panel to fixture database/i }))
    await userEvent.type(screen.getByLabelText(/custom manufacturer/i), 'Indie Light Co')
    expect(screen.getByLabelText(/custom fixture profile name/i)).toHaveValue('Mystery Panel')
    const channelCount = screen.getByLabelText(/custom fixture channel count/i)
    expect(channelCount).toHaveValue(12)
    await userEvent.clear(channelCount)
    await userEvent.type(channelCount, '13')
    await userEvent.click(screen.getByRole('button', { name: /create and select fixture/i }))
    expect(await screen.findByText(/must stay at the imported 12-channel footprint/i)).toBeInTheDocument()
    expect(global.fetch.mock.calls.some(([url]) => url === '/api/fixtures')).toBe(false)
    await userEvent.clear(channelCount)
    await userEvent.type(channelCount, '12')
    await userEvent.click(screen.getByRole('button', { name: /create and select fixture/i }))

    expect(await screen.findByText(/selected: indie light co .* mystery panel/i)).toBeInTheDocument()
    const createCall = global.fetch.mock.calls.find(([url]) => url === '/api/fixtures')
    expect(JSON.parse(createCall[1].body)).toEqual({
      manufacturer: 'Indie Light Co', fixture: 'Mystery Panel', channelCount: 12,
      notes: 'Created during patch-sheet import',
    })
  })

  it('does not allow dismissal or import while custom fixture creation is in flight', async () => {
    const pending = deferred()
    const onClose = vi.fn()
    installBaseFetch((url, options) => {
      if (url === '/api/fixtures' && options.method === 'POST') return pending.promise
      return null
    })
    render(<ImportWizard patchId={7} onClose={onClose} onImported={vi.fn()} />)
    await uploadAndReview()

    await userEvent.click(screen.getByRole('button', { name: /keep mystery panel unmatched/i }))
    const importButton = screen.getByRole('button', { name: /import 3 rows/i })
    expect(importButton).toBeEnabled()
    await userEvent.click(screen.getByRole('button', { name: /add mystery panel to fixture database/i }))
    await userEvent.click(screen.getByRole('button', { name: /create and select fixture/i }))

    expect(screen.getByRole('button', { name: /close import/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /keep mystery panel unmatched/i })).toBeDisabled()
    expect(importButton).toBeDisabled()
    await userEvent.keyboard('{Escape}')
    expect(onClose).not.toHaveBeenCalled()

    pending.resolve(response({
      id: 46, fixture: 'Mystery Panel', displayName: 'Mystery Panel',
      manufacturer: '', channelCount: 12, libraryType: null,
    }, true, 201))
    expect(await screen.findByText(/selected: mystery panel/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /close import/i })).toBeEnabled()
  })

  it('recovers duplicate custom creation by selecting the existing patchable profile', async () => {
    const existing = {
      id: 45,
      fixture: 'Mystery Panel',
      displayName: 'Indie Light Co — Mystery Panel',
      manufacturer: 'Indie Light Co',
      channelCount: 12,
      libraryType: null,
    }
    installBaseFetch((url, options) => {
      if (url === '/api/fixtures' && options.method === 'POST') {
        return Promise.resolve(response({
          error: 'That fixture profile already exists', existing,
        }, false, 409))
      }
      return null
    })
    render(<ImportWizard patchId={7} onClose={vi.fn()} onImported={vi.fn()} />)
    await uploadAndReview()

    await userEvent.click(screen.getByRole('button', { name: /add mystery panel to fixture database/i }))
    await userEvent.type(screen.getByLabelText(/custom manufacturer/i), 'Indie Light Co')
    await userEvent.click(screen.getByRole('button', { name: /create and select fixture/i }))

    expect(await screen.findByText(/selected: indie light co .* mystery panel/i)).toBeInTheDocument()
    expect(screen.queryByText(/already exists/i)).not.toBeInTheDocument()
  })
})
