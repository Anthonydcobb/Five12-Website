// File: src/components/SavedDesignsView.jsx
import React from 'react';

export default function SavedDesignsView({ templates, onSelect }) {
  return (
    <div className="mt-6">
      <h3 className="text-lg font-semibold mb-2">Saved Designs</h3>
      <ul className="space-y-1">
        {templates.map(t => (
          <li key={t.id}>
            <button
              onClick={() => onSelect(t)}
              className="w-full text-left px-3 py-2 bg-gray-200 hover:bg-gray-300 rounded"
            >
              {t.name}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
