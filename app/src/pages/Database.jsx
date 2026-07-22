// File: src/pages/Database.jsx
import React, { useState, useEffect, useMemo } from 'react';

export default function Database() {
  const [rows, setRows] = useState([]);

  // Load persisted fixtures on mount
  useEffect(() => {
    fetch('/api/fixtures')
      .then(res => res.json())
      .then(data => setRows(data))
      .catch(err => console.error('Error loading fixtures:', err));
  }, []);

  // Add a new fixture row via API
  const addRow = () => {
    fetch('/api/fixtures', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        fixture: '',
        notes: '',
        channelCount: 0,
        wattage: 0,
        weight: 0,
        firmware: ''
      })
    })
      .then(res => res.json())
      .then(newRow => setRows(prev => [...prev, newRow]))
      .catch(err => console.error('Error creating fixture:', err));
  };

  // Delete a fixture via API
  const deleteRow = (id) => {
    fetch(`/api/fixtures/${id}`, { method: 'DELETE' })
      .then(() => setRows(prev => prev.filter(r => r.id !== id)))
      .catch(err => console.error('Error deleting fixture:', err));
  };

  // Update a cell locally and via API
  const updateCell = (id, field, value) => {
    setRows(prev => {
      const updatedRows = prev.map(r => (r.id === id ? { ...r, [field]: value } : r));
      const updated = updatedRows.find(r => r.id === id);
      fetch(`/api/fixtures/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          fixture: updated.fixture,
          notes: updated.notes,
          channelCount: Number(updated.channelCount),
          wattage: Number(updated.wattage),
          weight: Number(updated.weight),
          firmware: updated.firmware
        })
      }).catch(err => console.error('Error updating fixture:', err));
      return updatedRows;
    });
  };

  const handleImportExcel = (e) => {
    const file = e.target.files[0];
    const formData = new FormData();
    formData.append('file', file);

    fetch('/api/fixtures/import-excel', {
      method: 'POST',
      body: formData
    })
      .then(res => res.json())
      .then(data => {
        if (data.error) {
          alert(`Import error: ${data.error}`);
          return;
        }

        if (data.duplicates && data.duplicates.length > 0) {
          const names = data.duplicates.map(d => `• ${d.new.fixture}`).join('\n');
          const shouldReplace = confirm(`The following fixtures already exist:\n\n${names}\n\nReplace existing fixtures?`);

          if (shouldReplace) {
            Promise.all(
              data.duplicates.map(d =>
                fetch(`/api/fixtures/${d.existing.id}`, { method: 'DELETE' }).then(() =>
                  fetch('/api/fixtures', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                      fixture: d.new.fixture,
                      notes: d.new.notes || '',
                      channelCount: Number(d.new.channel_count) || 0,
                      wattage: Number(d.new.wattage) || 0,
                      weight: Number(d.new.weight) || 0,
                      firmware: d.new.firmware || ''
                    })
                  })
                )
              )
            ).then(() => {
              alert(`✅ Imported ${data.inserted} fixtures (duplicates replaced)`);
              window.location.reload();
            });
          } else {
            alert(`Skipped ${data.duplicates.length} duplicate rows.`);
            window.location.reload();
          }
        } else {
          alert(`✅ Imported ${data.inserted} fixtures.`);
          window.location.reload();
        }
      })
      .catch(err => {
        console.error('Import failed:', err);
        alert('Import failed. See console for details.');
      });
  };

  const sortedRows = useMemo(() => {
    return [...rows].sort((a, b) => {
      const fa = a.fixture?.trim().toLowerCase();
      const fb = b.fixture?.trim().toLowerCase();
      if (!fa && !fb) return 0;
      if (!fa) return 1;
      if (!fb) return -1;
      return fa.localeCompare(fb);
    });
  }, [rows]);

  return (
    <div className="p-6 bg-bg min-h-screen text-white">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-bold">Lighting Database</h1>
        <div className="flex gap-4">
          <button
            onClick={addRow}
            className="px-4 py-2 bg-online hover:brightness-110 rounded"
          >
            + Add Row
          </button>
          <label className="px-4 py-2 bg-brand hover:bg-brand-hi rounded cursor-pointer text-sm">
            Import Excel
            <input
              type="file"
              accept=".xlsx"
              className="hidden"
              onChange={handleImportExcel}
            />
          </label>
        </div>
      </div>
      <div className="overflow-auto">
        <table className="min-w-full table-auto bg-surface rounded">
          <thead>
            <tr className="bg-surface-2">
              <th className="px-4 py-2 border">Fixture</th>
              <th className="px-4 py-2 border">Channel Count</th>
              <th className="px-4 py-2 border">Wattage</th>
              <th className="px-4 py-2 border">Weight</th>
              <th className="px-4 py-2 border">Firmware</th>
              <th className="px-4 py-2 border">Notes</th>
              <th className="px-4 py-2 border">Actions</th>
            </tr>
          </thead>
          <tbody>
            {sortedRows.map(row => (
              <tr key={row.id} className="even:bg-surface odd:bg-bg">
                {['fixture'].map(field => (
                  <td key={field} className="px-4 py-2 border">
                    <input
                      type="text"
                      value={row[field]}
                      onChange={e => updateCell(row.id, field, e.target.value)}
                      className="w-full bg-transparent focus:outline-none text-white"
                    />
                  </td>
                ))}
                {['channelCount', 'wattage', 'weight'].map(field => (
                  <td key={field} className="px-4 py-2 border">
                    <input
                      type="number"
                      value={row[field]}
                      onChange={e => updateCell(row.id, field, e.target.value)}
                      className="w-full bg-transparent focus:outline-none text-white"
                    />
                  </td>
                ))}
                <td className="px-4 py-2 border">
                  <input
                    type="text"
                    value={row.firmware}
                    onChange={e => updateCell(row.id, 'firmware', e.target.value)}
                    className="w-full bg-transparent focus:outline-none text-white"
                  />
                </td>
                <td className="px-4 py-2 border">
                  <input
                    type="text"
                    value={row.notes}
                    onChange={e => updateCell(row.id, 'notes', e.target.value)}
                    className="w-full bg-transparent focus:outline-none text-white"
                  />
                </td>
                <td className="px-4 py-2 border text-center">
                  <button
                    onClick={() => deleteRow(row.id)}
                    className="text-brand-hi hover:text-brand"
                  >
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
