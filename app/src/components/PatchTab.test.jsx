import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import PatchTab from './PatchTab'


describe('PatchTab imported fixture traceability', () => {
  it('shows the original patch-sheet identity beneath a selected library profile', () => {
    render(
      <PatchTab
        patchId={7}
        rows={[{
          id: 1, set: '', fixture: '1', universe: 1, address: 101, endAddress: 112,
          type: 'Mystery Panel Mode A', channelCount: 12,
          importedFixtureType: 'Mystery Panel', importedChannelCount: 12,
          location: '', wattage: '', weight: '', firmware: '', notes: '',
        }]}
        conflicts={[]}
        onPatch={vi.fn()}
        onRePatch={vi.fn()}
        onUnpatch={vi.fn()}
        onRemoveFixture={vi.fn()}
        updateField={vi.fn()}
      />
    )

    expect(screen.getByText('Mystery Panel Mode A')).toBeInTheDocument()
    expect(screen.getByText('Imported: Mystery Panel · 12ch')).toBeInTheDocument()
  })

  it('returns focus to the Import trigger after closing the wizard', async () => {
    render(
      <PatchTab
        patchId={7}
        rows={[]}
        conflicts={[]}
        onPatch={vi.fn()}
        onRePatch={vi.fn()}
        onUnpatch={vi.fn()}
        onRemoveFixture={vi.fn()}
        updateField={vi.fn()}
      />
    )

    const trigger = screen.getByRole('button', { name: 'Import' })
    await userEvent.click(trigger)
    await userEvent.click(screen.getByRole('button', { name: /close import/i }))
    await waitFor(() => expect(trigger).toHaveFocus())
  })
})
