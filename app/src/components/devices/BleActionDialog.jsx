import { useEffect, useState } from 'react'

// Deliberately NOT window.confirm, which the Stardust panel uses for its own
// link action. A browser confirm accepts on Enter, and these commands can put
// a live fixture dark — muscle memory must not be able to fire one. So:
// a real modal, Enter does nothing, and confirm stays disabled until the
// operator ticks an acknowledgement.
export default function BleActionDialog({
  deviceAlias, hardwareId, warning, actionLabel, busy, onConfirm, onCancel,
}) {
  const [acknowledged, setAcknowledged] = useState(false)

  useEffect(() => {
    const onKeyDown = (e) => {
      if (e.key === 'Escape' && !busy) onCancel()
      // Enter is swallowed on purpose. There is no keyboard shortcut to
      // confirm; the operator must click.
      if (e.key === 'Enter') e.preventDefault()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [busy, onCancel])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`${actionLabel} ${deviceAlias}`}
        className="border border-brand bg-[var(--color-surface)] rounded-sm p-4 max-w-sm w-full space-y-3"
      >
        <div>
          <div className="text-[11px] font-mono font-bold text-text">
            {actionLabel} — {deviceAlias}
          </div>
          <div className="text-[8px] font-mono text-text-muted mt-[2px]">
            hardware id {hardwareId}
          </div>
        </div>

        {/* Server-supplied copy, rendered verbatim: the text the operator
            agrees to is the text the server will enforce. */}
        <p className="text-[10px] font-mono text-warn leading-relaxed">{warning}</p>

        <label className="flex items-start gap-2 text-[10px] font-mono text-text cursor-pointer">
          <input
            type="checkbox"
            checked={acknowledged}
            disabled={busy}
            onChange={(e) => setAcknowledged(e.target.checked)}
            className="mt-[2px]"
          />
          <span>I understand what this will do.</span>
        </label>

        <div className="flex justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="text-[9px] font-mono px-3 py-1 border border-[var(--color-border)] rounded-sm hover:border-brand disabled:opacity-40"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={!acknowledged || busy}
            className="text-[9px] font-mono px-3 py-1 border border-brand text-brand-hi rounded-sm hover:bg-brand/10 disabled:opacity-40"
          >
            {busy ? 'working…' : actionLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
