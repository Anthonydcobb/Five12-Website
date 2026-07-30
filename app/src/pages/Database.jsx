// File: src/pages/Database.jsx
import React, { useEffect, useState } from 'react';

const MAX_VISIBLE_ROWS = 500;

async function readJson(response, label = 'Request') {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(`${label} failed (${response.status}): ${data.error || 'No error details returned.'}`);
  }
  return data;
}

async function requestJson(url, options, label) {
  let response;
  try {
    response = await fetch(url, options);
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    const detail = error.message ? ` (${error.message})` : '';
    throw new Error(
      `${label} could not reach the Five12 backend. ` +
      `Check that Flask is running on http://127.0.0.1:5000, then retry.${detail}`
    );
  }
  return readJson(response, label);
}

export default function Database() {
  const [rows, setRows] = useState([]);
  const [backups, setBackups] = useState([]);
  const [libraryStatus, setLibraryStatus] = useState(null);
  const [search, setSearch] = useState('');
  const [offset, setOffset] = useState(0);
  const [catalogTotal, setCatalogTotal] = useState(0);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [message, setMessage] = useState(null);
  const [loadErrors, setLoadErrors] = useState({});

  const clearLoadError = scope => {
    setLoadErrors(previous => {
      if (!previous[scope]) return previous;
      const next = { ...previous };
      delete next[scope];
      return next;
    });
  };

  const recordLoadError = (scope, error) => {
    if (error.name !== 'AbortError') {
      setLoadErrors(previous => ({ ...previous, [scope]: error.message }));
    }
  };

  const loadCatalog = async (query = search, nextOffset = offset, signal) => {
    const params = new URLSearchParams({
      q: query.trim(), limit: String(MAX_VISIBLE_ROWS), offset: String(nextOffset),
    });
    const page = await requestJson(
      `/api/fixture-library/catalog?${params}`,
      { signal },
      'Fixture catalog'
    );
    setRows(page.items);
    setCatalogTotal(page.total);
    clearLoadError('catalog');
  };

  const loadMetadata = async () => {
    const [status, savedBackups] = await Promise.all([
      requestJson('/api/fixture-library/status', undefined, 'Fixture library status'),
      requestJson('/api/fixture-library/backups', undefined, 'Fixture backup list'),
    ]);
    setLibraryStatus(status);
    setBackups(savedBackups);
    clearLoadError('metadata');
  };

  const refreshMetadata = async () => {
    try {
      await loadMetadata();
      return true;
    } catch (error) {
      recordLoadError('metadata', error);
      return false;
    }
  };

  const refreshCatalog = async (query = search, nextOffset = offset, signal) => {
    try {
      await loadCatalog(query, nextOffset, signal);
      return true;
    } catch (error) {
      recordLoadError('catalog', error);
      return false;
    }
  };

  const reloadAll = async () => {
    setOffset(0);
    setCatalogLoading(true);
    await Promise.all([refreshCatalog(search, 0), refreshMetadata()]);
    setCatalogLoading(false);
  };

  const retryFixtureData = async () => {
    const retries = [];
    if (loadErrors.catalog) {
      setCatalogLoading(true);
      retries.push(refreshCatalog(search, offset));
    }
    if (loadErrors.metadata) retries.push(refreshMetadata());
    await Promise.all(retries);
    setCatalogLoading(false);
  };

  useEffect(() => {
    refreshMetadata();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setCatalogLoading(true);
      refreshCatalog(search, offset, controller.signal)
        .finally(() => {
          if (!controller.signal.aborted) setCatalogLoading(false);
        });
    }, 200);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [search, offset]);

  const addRow = async () => {
    try {
      const newRow = await requestJson('/api/fixtures', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          fixture: '', notes: '', channelCount: 0, wattage: 0, weight: 0, firmware: '',
        }),
      }, 'Add fixture');
      setRows(previous => [...previous, newRow]);
    } catch (error) {
      setMessage({ type: 'error', text: error.message });
    }
  };

  const deleteRow = async (id) => {
    try {
      await requestJson(`/api/fixtures/${id}`, { method: 'DELETE' }, 'Delete fixture');
      setRows(previous => previous.filter(row => row.id !== id));
    } catch (error) {
      setMessage({ type: 'error', text: error.message });
    }
  };

  const editCell = (id, field, value) => {
    setRows(previous => previous.map(row => (
      row.id === id ? { ...row, [field]: value } : row
    )));
  };

  const saveRow = async id => {
    const updated = rows.find(row => row.id === id);
    if (!updated) return;
    try {
      const saved = await requestJson(`/api/fixtures/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          fixture: updated.fixture,
          notes: updated.notes || '',
          channelCount: Number(updated.channelCount),
          wattage: updated.wattage === '' || updated.wattage == null ? null : Number(updated.wattage),
          weight: updated.weight === '' || updated.weight == null ? null : Number(updated.weight),
          firmware: updated.firmware || '',
        }),
      }, 'Update fixture');
      setRows(previous => previous.map(row => row.id === id ? saved : row));
      await refreshMetadata();
    } catch (error) {
      setMessage({ type: 'error', text: `Fixture update failed: ${error.message}` });
      await refreshCatalog(search, offset);
    }
  };

  const handleImportExcel = async event => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);

    try {
      setBusy('excel');
      const data = await requestJson('/api/fixtures/import-excel', {
        method: 'POST', body: formData,
      }, 'Excel fixture import');
      setMessage({
        type: 'success',
        text: `Imported ${data.inserted} fixtures. ${data.duplicates?.length || 0} duplicates were skipped.`,
      });
      await reloadAll();
    } catch (error) {
      setMessage({ type: 'error', text: error.message });
    } finally {
      setBusy('');
    }
  };

  const handleImportHogXml = async event => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;

    try {
      setBusy('hog');
      setMessage({ type: 'info', text: 'Validating the Hog fixture library…' });
      const previewForm = new FormData();
      previewForm.append('file', file);
      const preview = await requestJson('/api/fixture-library/hog/preview', {
        method: 'POST', body: previewForm,
      }, 'Hog library preview');

      const confirmed = window.confirm(
        `Import Hog ${preview.version}?\n\n` +
        `${preview.fixtureCount.toLocaleString()} source profiles from ` +
        `${preview.manufacturers.toLocaleString()} manufacturers.\n` +
        `${preview.patchable.toLocaleString()} are currently patchable; ` +
        `${preview.unsupported.toLocaleString()} internal parts or profiles wider than one universe stay in the database but are hidden from the picker.\n\n` +
        `This replaces ${preview.currentCount.toLocaleString()} current fixtures after creating a checked, restorable backup. Existing show patch rows are not deleted.`
      );
      if (!confirmed) {
        setMessage({ type: 'info', text: 'Hog fixture import cancelled; nothing changed.' });
        return;
      }

      setMessage({ type: 'info', text: 'Backing up and importing the Hog fixture library…' });
      const importForm = new FormData();
      importForm.append('file', file);
      importForm.append('confirmReplace', 'true');
      importForm.append('previewToken', preview.previewToken);
      const data = await requestJson('/api/fixture-library/hog/import', {
        method: 'POST', body: importForm,
      }, 'Hog library import');
      setMessage({
        type: 'success',
        text: (
          `Imported ${data.imported.toLocaleString()} Hog ${data.version} profiles from ` +
          `${data.manufacturers.toLocaleString()} manufacturers. The previous ` +
          `catalog is saved as backup #${data.backup.id}.`
        ),
      });
      await reloadAll();
    } catch (error) {
      setMessage({ type: 'error', text: error.message });
    } finally {
      setBusy('');
    }
  };

  const restoreBackup = async backup => {
    const confirmed = window.confirm(
      `Restore fixture backup #${backup.id} (${backup.fixtureCount.toLocaleString()} fixtures)?\n\n` +
      'Five12 will back up the current catalog before restoring this one.'
    );
    if (!confirmed) return;

    try {
      setBusy(`restore-${backup.id}`);
      const data = await requestJson(`/api/fixture-library/backups/${backup.id}/restore`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          confirmReplace: true,
          expectedCatalogChecksum: libraryStatus?.catalogChecksum,
        }),
      }, 'Fixture backup restore');
      setMessage({
        type: 'success',
        text: (
          `Restored ${data.restored.toLocaleString()} fixtures. The catalog you just ` +
          `replaced is saved as backup #${data.rollbackBackup.id}.`
        ),
      });
      await reloadAll();
    } catch (error) {
      setMessage({ type: 'error', text: error.message });
    } finally {
      setBusy('');
    }
  };

  return (
    <div className="p-6 bg-bg min-h-screen text-white">
      <div className="flex flex-wrap items-start justify-between gap-4 mb-4">
        <div>
          <h1 className="text-2xl font-bold">Lighting Database</h1>
          <p className="text-sm text-text-muted mt-1">
            {libraryStatus?.fixtureCount?.toLocaleString() || rows.length.toLocaleString()} fixtures
            {libraryStatus?.source && ` · ${libraryStatus.source} ${libraryStatus.version || ''}`}
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <button
            onClick={addRow}
            disabled={Boolean(busy)}
            className="px-4 py-2 bg-online hover:brightness-110 rounded disabled:opacity-50"
          >
            + Add Row
          </button>
          <label className={`px-4 py-2 bg-brand hover:bg-brand-hi rounded cursor-pointer text-sm ${busy ? 'opacity-50 pointer-events-none' : ''}`}>
            {busy === 'excel' ? 'Importing…' : 'Import Excel'}
            <input type="file" accept=".xlsx" className="hidden" onChange={handleImportExcel} />
          </label>
          <label className={`px-4 py-2 bg-brand hover:bg-brand-hi rounded cursor-pointer text-sm ${busy ? 'opacity-50 pointer-events-none' : ''}`}>
            {busy === 'hog' ? 'Importing Hog XML…' : 'Replace with Hog summary.xml'}
            <input type="file" accept=".xml,text/xml,application/xml" className="hidden" onChange={handleImportHogXml} />
          </label>
        </div>
      </div>

      {message && (
        <div className={`mb-4 rounded border p-3 text-sm ${
          message.type === 'error'
            ? 'border-brand bg-brand-dim/40 text-brand-hi'
            : message.type === 'success'
              ? 'border-online/60 bg-online/10 text-online'
              : 'border-border bg-surface text-text'
        }`}>
          {message.text}
        </div>
      )}

      {Object.keys(loadErrors).length > 0 && (
        <div role="alert" className="mb-4 rounded border border-brand bg-brand-dim/40 p-3 text-sm text-brand-hi">
          <div className="font-semibold">Some fixture data could not be refreshed.</div>
          <ul className="mt-1 list-disc pl-5">
            {Object.values(loadErrors).map(error => <li key={error}>{error}</li>)}
          </ul>
          <button
            type="button"
            onClick={retryFixtureData}
            className="mt-3 rounded bg-brand px-3 py-1.5 text-white hover:bg-brand-hi"
          >
            Retry fixture data
          </button>
        </div>
      )}

      {backups.length > 0 && (
        <section className="mb-5 rounded border border-border bg-surface p-4">
          <h2 className="font-semibold mb-2">Fixture backups</h2>
          <p className="text-xs text-text-muted mb-3">
            Backups stay inside Five12. Download a JSON copy if you also want it outside the app database.
          </p>
          <div className="flex flex-wrap gap-2">
            {backups.slice(0, 8).map(backup => (
              <div key={backup.id} className="rounded bg-bg border border-border px-3 py-2 text-xs">
                <div className="font-medium">#{backup.id} · {backup.fixtureCount.toLocaleString()} fixtures</div>
                <div className="text-text-muted mb-2">{backup.reason}</div>
                <div className="flex gap-2">
                  <a
                    href={`/api/fixture-library/backups/${backup.id}/download`}
                    className="text-brand-hi hover:underline"
                  >
                    Download JSON
                  </a>
                  <button
                    type="button"
                    disabled={Boolean(busy)}
                    onClick={() => restoreBackup(backup)}
                    className="text-online hover:underline disabled:opacity-50"
                  >
                    {busy === `restore-${backup.id}` ? 'Restoring…' : 'Restore'}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      <div className="flex items-center gap-3 mb-3">
        <input
          type="search"
          value={search}
          onChange={event => { setSearch(event.target.value); setOffset(0); }}
          placeholder="Search manufacturer or profile…"
          className="w-full max-w-xl px-3 py-2 bg-surface border border-border rounded text-white"
        />
        <span className="text-xs text-text-muted whitespace-nowrap">
          {catalogLoading
            ? 'Loading…'
            : catalogTotal === 0
              ? '0 fixtures'
              : `${offset + 1}–${Math.min(offset + rows.length, catalogTotal)} of ${catalogTotal.toLocaleString()}`}
        </span>
        <button
          type="button"
          disabled={offset === 0 || catalogLoading}
          onClick={() => setOffset(Math.max(0, offset - MAX_VISIBLE_ROWS))}
          className="px-2 py-1 bg-surface-2 rounded disabled:opacity-40"
        >
          Previous
        </button>
        <button
          type="button"
          disabled={offset + rows.length >= catalogTotal || catalogLoading}
          onClick={() => setOffset(offset + MAX_VISIBLE_ROWS)}
          className="px-2 py-1 bg-surface-2 rounded disabled:opacity-40"
        >
          Next
        </button>
      </div>

      <div className="overflow-auto">
        <table className="min-w-full table-auto bg-surface rounded">
          <thead>
            <tr className="bg-surface-2">
              <th className="px-3 py-2 border">Manufacturer</th>
              <th className="px-3 py-2 border">Fixture / Profile</th>
              <th className="px-3 py-2 border">Channels</th>
              <th className="px-3 py-2 border">Kind</th>
              <th className="px-3 py-2 border">Wattage</th>
              <th className="px-3 py-2 border">Weight</th>
              <th className="px-3 py-2 border">Firmware</th>
              <th className="px-3 py-2 border">Notes</th>
              <th className="px-3 py-2 border">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(row => (
              <tr key={row.id} className="even:bg-surface odd:bg-bg">
                <td className="px-3 py-2 border text-sm">{row.manufacturer || '—'}</td>
                <td className="px-3 py-2 border">
                  <input
                    type="text"
                    value={row.fixture || ''}
                    disabled={Boolean(busy)}
                    onChange={event => editCell(row.id, 'fixture', event.target.value)}
                    onBlur={() => saveRow(row.id)}
                    className="w-full bg-transparent focus:outline-none text-white"
                  />
                </td>
                <td className="px-3 py-2 border">
                  <input
                    type="number"
                    value={row.channelCount ?? 0}
                    disabled={Boolean(busy)}
                    onChange={event => editCell(row.id, 'channelCount', event.target.value)}
                    onBlur={() => saveRow(row.id)}
                    className="w-20 bg-transparent focus:outline-none text-white"
                  />
                </td>
                <td className="px-3 py-2 border text-sm">{row.libraryType || 'manual'}</td>
                {['wattage', 'weight'].map(field => (
                  <td key={field} className="px-3 py-2 border">
                    <input
                      type="number"
                      value={row[field] ?? ''}
                      disabled={Boolean(busy)}
                      placeholder="Unknown"
                      onChange={event => editCell(row.id, field, event.target.value)}
                      onBlur={() => saveRow(row.id)}
                      className="w-20 bg-transparent focus:outline-none text-white"
                    />
                  </td>
                ))}
                <td className="px-3 py-2 border">
                  <input
                    type="text"
                    value={row.firmware || ''}
                    disabled={Boolean(busy)}
                    onChange={event => editCell(row.id, 'firmware', event.target.value)}
                    onBlur={() => saveRow(row.id)}
                    className="w-full bg-transparent focus:outline-none text-white"
                  />
                </td>
                <td className="px-3 py-2 border">
                  <input
                    type="text"
                    value={row.notes || ''}
                    disabled={Boolean(busy)}
                    onChange={event => editCell(row.id, 'notes', event.target.value)}
                    onBlur={() => saveRow(row.id)}
                    className="w-full bg-transparent focus:outline-none text-white"
                  />
                </td>
                <td className="px-3 py-2 border text-center">
                  <button disabled={Boolean(busy)} onClick={() => deleteRow(row.id)} className="text-brand-hi hover:text-brand disabled:opacity-50">
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
