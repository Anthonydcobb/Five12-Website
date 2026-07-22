// File: src/components/LabelSidebar.jsx
import React from 'react';

export default function LabelSidebar({ view, onSelect }) {
  const sections = [
    { id: 'saved', label: 'Saved Designs' },
    { id: 'blank', label: 'Blank Templates' },
    { id: 'pre',   label: 'Pre-Designed Templates' },
  ];

  return (
    <aside className="w-64 bg-surface text-white min-h-screen flex-shrink-0">
      <div className="p-4 border-b border-border">
        {/* Sidebar title */}
        <h2 className="text-xl font-semibold text-center">Label Creator</h2>
      </div>

      <nav className="mt-4">
        {sections.map(sec => (
          <button
            key={sec.id}
            onClick={() => onSelect(sec.id)}
            className={`w-full text-left px-4 py-3 hover:bg-surface-2 focus:bg-surface-2 ${view === sec.id ? 'bg-surface-2' : ''}`}
          >
            {sec.label}
          </button>
        ))}
      </nav>
    </aside>
  );
}
