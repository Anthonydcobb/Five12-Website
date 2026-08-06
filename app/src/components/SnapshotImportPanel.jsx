import React, { useState } from 'react';
import axios from 'axios';

const HINT = 'In the switch UI at Configure → Overview, open the browser console and run '
  + 'copy(document.documentElement.outerHTML), then paste here.';

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
    axios.post('/api/network/snapshot', { html })
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
              Imported {result.systemName || result.macAddress} — {result.profileCount} profiles,
              {' '}{result.portCount} ports.
              {result.hostDataAvailable === false && (
                <span style={{ color: 'var(--color-brand-hi)' }}>
                  {' '}Per-port host details were not readable from this page.
                </span>
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
