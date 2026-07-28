import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import BleActionDialog from './BleActionDialog'

const PROPS = {
  deviceAlias: 'F12L - 2071',
  hardwareId: 'F1400000',
  currentMode: 'tx',
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

  it('shows the mode the server just read off the radio', () => {
    // Fix 4: prepare_command's currentMode exists so the operator confirms
    // against server-side fact, not whatever their browser last rendered —
    // so it must actually reach the dialog.
    setup()
    expect(screen.getByText(/TX/)).toBeInTheDocument()
  })

  it('does not render a mode line when none was supplied', () => {
    setup({ currentMode: undefined })
    expect(screen.queryByText(/radio's mode/i)).not.toBeInTheDocument()
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

  it('blocks Enter by preventing its default action', () => {
    // This is the assertion that actually pins the preventDefault guard.
    // jsdom does not implement a browser's native "Enter activates the focused button"
    // behavior, so a purely behavioural test cannot prove the guard is present.
    // fireEvent.keyDown returns false when a handler called preventDefault().
    setup()
    const notCancelled = fireEvent.keyDown(document, { key: 'Enter' })
    expect(notCancelled).toBe(false)
  })

  it('does not confirm on Enter when focus is on the confirm button', async () => {
    // This covers the real operator path: tab to the enabled control, hit Enter.
    // Deliberately paired with the direct preventDefault test above because jsdom
    // will not activate the button on Enter by itself.
    const { onConfirm } = setup()
    const confirm = screen.getByRole('button', { name: /^link$/i })
    await userEvent.click(screen.getByRole('checkbox'))
    expect(confirm).toBeEnabled()
    confirm.focus()
    expect(confirm).toHaveFocus()
    await userEvent.keyboard('{Enter}')
    expect(onConfirm).not.toHaveBeenCalled()
  })

  it('cancels on Escape', async () => {
    const { onCancel } = setup()
    await userEvent.keyboard('{Escape}')
    expect(onCancel).toHaveBeenCalledTimes(1)
  })

  it('does not cancel on Escape while the command is in flight', async () => {
    const { onCancel } = setup({ busy: true })
    await userEvent.keyboard('{Escape}')
    expect(onCancel).not.toHaveBeenCalled()
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
