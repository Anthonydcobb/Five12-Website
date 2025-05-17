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
        mode: '',
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
      // Persist update
      fetch(`/api/fixtures/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          fixture: updated.fixture,
          mode: updated.mode,
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

  // Sort rows alphabetically by fixture
  const sortedRows = useMemo(() => {
    return [...rows].sort((a, b) => {
      const fa = a.fixture.trim().toLowerCase();
      const fb = b.fixture.trim().toLowerCase();
      if (!fa && !fb) return 0;
      if (!fa) return 1;
      if (!fb) return -1;
      return fa.localeCompare(fb);
    });
  }, [rows]);

  return (
    <div className="p-6 bg-gray-900 min-h-screen text-white">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-bold">Lighting Database</h1>
        <button
          onClick={addRow}
          className="px-4 py-2 bg-green-600 hover:bg-green-700 rounded"
        >
          + Add Row
        </button>
      </div>
      <div className="overflow-auto">
        <table className="min-w-full table-auto bg-gray-800 rounded">
          <thead>
            <tr className="bg-gray-700">
              <th className="px-4 py-2 border">Fixture</th>
              <th className="px-4 py-2 border">Mode</th>
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
              <tr key={row.id} className="even:bg-gray-800 odd:bg-gray-900">
                {/* Text fields */}
                {['fixture', 'mode'].map(field => (
                  <td key={field} className="px-4 py-2 border">
                    <input
                      type="text"
                      value={row[field]}
                      onChange={e => updateCell(row.id, field, e.target.value)}
                      className="w-full bg-transparent focus:outline-none text-white"
                    />
                  </td>
                ))}
                {/* Numeric fields */}
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
                {/* Firmware */}
                <td className="px-4 py-2 border">
                  <input
                    type="text"
                    value={row.firmware}
                    onChange={e => updateCell(row.id, 'firmware', e.target.value)}
                    className="w-full bg-transparent focus:outline-none text-white"
                  />
                </td>
                {/* Notes */}
                <td className="px-4 py-2 border">
                  <input
                    type="text"
                    value={row.notes}
                    onChange={e => updateCell(row.id, 'notes', e.target.value)}
                    className="w-full bg-transparent focus:outline-none text-white"
                  />
                </td>
                {/* Actions */}
                <td className="px-4 py-2 border text-center">
                  <button
                    onClick={() => deleteRow(row.id)}
                    className="text-red-500 hover:text-red-700"
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
