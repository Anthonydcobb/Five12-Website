// ------------------------------
// Cue List Manager Component
// File: src/components/CueListManager.jsx
import React from 'react';

function CueListManager({ params, setParams }) {
  // Placeholder array of cues
  const cues = [
    { id: 1, label: 'Initial', settings: params },
    { id: 2, label: 'Flicker', settings: params }
  ];

  return (
    <div className="space-y-4">
      <button className="w-full bg-indigo-600 hover:bg-indigo-700 text-white py-2 rounded-lg font-semibold">
        Record Cue
      </button>
      <ul className="space-y-2">
        {cues.map(cue => (
          <li key={cue.id} className="bg-gray-600 p-2 rounded flex justify-between">
            <span>{cue.label}</span>
            <button className="text-sm text-gray-300 hover:text-white">Load</button>
          </li>
        ))}
      </ul>
      <div className="flex justify-between">
        <button className="px-3 py-1 bg-gray-500 hover:bg-gray-600 rounded">◄ Back</button>
        <button className="px-3 py-1 bg-gray-500 hover:bg-gray-600 rounded">Play</button>
        <button className="px-3 py-1 bg-gray-500 hover:bg-gray-600 rounded">Next ►</button>
      </div>
    </div>
  );
}

export default CueListManager;
