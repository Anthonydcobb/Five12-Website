import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import BleActionDialog from './BleActionDialog'

const PROPS = {
  deviceAlias: 'F12L - 2071',
  hardwareId: 'F1400000',
  warning: 'Any unlinked receiver in range will pair to it.',
  actionLabel: 'Link',
  busy: false,
}

function setup(overrides = {}) {
  const onConfirm = vi.fn()
  const onCancel = vi.fn()
  render(<BleActionDialog {...PROPS} {...overrides} onConfirm={onConfirm} onCancel={onCancel} />)
  return { onConfirm, onCancel }
}

describe('BleActionDialog', () => {
  it('names the device it is about to change', () => {
    setup()
    expect(screen.getByText(/F12L - 2071/)).toBeInTheDocument()
    expect(screen.getByText(/F1400000/)).toBeInTheDocument()
  })

  it('renders the server-supplied warning verbatim', () => {
    setup()
    expect(screen.getByText(PROPS.warning)).toBeInTheDocument()
  })

  it('disables confirm until the operator acknowledges', async () => {
    const { onConfirm } = setup()
    const confirm = screen.getByRole('button', { name: /^link$/i })
    expect(confirm).toBeDisabled()
    await userEvent.click(screen.getByRole('checkbox'))
    expect(confirm).toBeEnabled()
    await userEvent.click(confirm)
    expect(onConfirm).toHaveBeenCalledTimes(1)
  })

  it('does not confirm on Enter', async () => {
    // The whole reason this is not window.confirm: muscle memory must not be
    // able to fire an action that can black out a fixture.
    const { onConfirm } = setup()
    await userEvent.click(screen.getByRole('checkbox'))
    await userEvent.keyboard('{Enter}')
    expect(onConfirm).not.toHaveBeenCalled()
  })

  it('cancels on Escape', async () => {
    const { onCancel } = setup()
    await userEvent.keyboard('{Escape}')
    expect(onCancel).toHaveBeenCalledTimes(1)
  })

  it('cancels from the cancel button', async () => {
    const { onCancel } = setup()
    await userEvent.click(screen.getByRole('button', { name: /cancel/i }))
    expect(onCancel).toHaveBeenCalledTimes(1)
  })

  it('locks both buttons while the command is in flight', async () => {
    setup({ busy: true })
    expect(screen.getByRole('button', { name: /working/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /cancel/i })).toBeDisabled()
  })

  it('is announced as a modal dialog', () => {
    setup()
    expect(screen.getByRole('dialog')).toHaveAttribute('aria-modal', 'true')
  })
})
