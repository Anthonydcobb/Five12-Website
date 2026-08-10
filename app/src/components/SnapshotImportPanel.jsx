import React, { useState } from 'react';
import axios from 'axios';

const HINT = 'In the switch UI at Configure → Overview (or Port Configuration), open the '
  + 'browser console and run copy(document.documentElement.outerHTML), then paste here. '
  + 'A Port Configuration page only carries the rows you scrolled into view.';

export default function SnapshotImportPanel({ device, onImported }) {
  const [open, setOpen] = useState(false);
  const [html, setHtml] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  if (device.deviceType !== 'netgear') return null;

  const submit = () => {
    setBusy(true);
    setError(null);
    setResult(null);
    // A Port Configuration page carries no identity of its own -- and the only
    // IP readable as text on it belongs to the LLDP neighbour. The switch the
    // operator has open is the only honest answer to "which device is this?".
    axios.post('/api/network/snapshot', { html, macAddress: device.macAddress })
      .then(res => {
        setResult(res.data);
        setHtml('');
        onImported?.();
      })
      // The server's refusals are specific and actionable -- which switch the
      // MAC belongs to, which serial conflicts. Showing a generic "import
      // failed" would throw away the only part that tells the operator what to
      // do next.
      .catch(err => setError(err?.response?.data?.detail || 'Import failed.'))
      .finally(() => setBusy(false));
  };

  return (
    <div style={{ background: 'var(--color-surface)', borderRadius: 4, padding: 8, marginBottom: 8 }}>
      <div
        onClick={() => setOpen(o => !o)}
        style={{ color: 'var(--color-text-muted)', fontSize: 11, letterSpacing: 1, cursor: 'pointer' }}
      >
        {open ? '▾' : '▸'} IMPORT SWITCH SNAPSHOT
      </div>

      {open && (
        <div style={{ marginTop: 8 }}>
          <div style={{ color: 'var(--color-text-muted)', fontSize: 10, marginBottom: 6 }}>{HINT}</div>
          <textarea
            value={html}
            onChange={e => setHtml(e.target.value)}
            placeholder="Paste the page HTML"
            style={{
              width: '100%', height: 70, boxSizing: 'border-box',
              background: 'var(--color-bg)', color: 'var(--color-text)',
              border: '1px solid var(--color-border)', borderRadius: 4,
              fontSize: 11, padding: 6,
            }}
          />
          <button
            onClick={submit}
            disabled={busy || !html.trim()}
            style={{
              marginTop: 6, background: 'var(--color-surface-2)', color: 'var(--color-gel)',
              border: '1px solid var(--color-border)', borderRadius: 4,
              padding: '4px 10px', fontSize: 11, cursor: 'pointer',
            }}
          >
            {busy ? 'Importing…' : 'Import'}
          </button>

          {result && (
            <div style={{ marginTop: 6, fontSize: 10, color: 'var(--color-online)' }}>
              {result.portCount !== undefined && (
                <>
                  Imported {result.systemName || result.macAddress} — {result.profileCount} profiles,
                  {' '}{result.portCount} ports.
                  {result.hostDataAvailable === false && (
                    <span style={{ color: 'var(--color-brand-hi)' }}>
                      {' '}Per-port host details were not readable from this page.
                    </span>
                  )}
                </>
              )}

              {result.portsUpdated !== undefined && (
                <>
                  Port configuration: {result.portsUpdated} ports updated.
                  {result.portsInCaptureNotInBase?.length > 0 && (
                    <span style={{ color: 'var(--color-text-muted)' }}>
                      {' '}Not in the snapshot: {result.portsInCaptureNotInBase.join(', ')}.
                    </span>
                  )}
                  {result.disagreements?.map(d => (
                    <div key={`${d.port}-${d.field}`} style={{ color: 'var(--color-brand-hi)' }}>
                      Port {d.port}: the snapshot says {d.field} “{d.popover}”, this page says
                      {' '}“{d.portConfig}”. The snapshot value came from the page's popovers,
                      which are matched by document order — treat this page as correct.
                    </div>
                  ))}
                </>
              )}
            </div>
          )}
          {error && (
            <div style={{ marginTop: 6, fontSize: 10, color: 'var(--color-brand-hi)' }}>{error}</div>
          )}
        </div>
      )}
    </div>
  );
}
