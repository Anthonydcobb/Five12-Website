// File: src/components/BlankTemplatesView.jsx

import React from 'react';

const BLANK_TEMPLATES = [
  
  {
    id: '5161',
    name: 'Avery 5161 (20/Sheet)',
    preview: '/static/previews/5161.png',
    config: { fields: [] },
  },
  {
    id: '5163',
    name: 'Avery 5163 (14/Sheet)',
    preview: '/static/previews/5163.png',
    config: { fields: [] },
  },
  {
    id: '18294',
    name: 'Avery 18294 (8/Sheet)',
    preview: '/static/previews/18294.png',
    config: { fields: [] },
  },
];

export default function BlankTemplatesView({ onSelectTpl }) {
  return (
    <div className="mt-6">
      <h3 className="text-lg font-semibold mb-2">Blank Templates</h3>
      <div className="grid grid-cols-2 gap-4">
        {BLANK_TEMPLATES.map(tpl => (
          <div key={tpl.id} className="border p-2 rounded shadow-sm">
            <img
              src={tpl.preview}
              alt={tpl.name}
              className="w-full h-32 object-contain mb-2"
              onError={e => (e.currentTarget.style.display = 'none')}
            />
            <div className="flex justify-between items-center">
              <span className="text-sm">{tpl.name}</span>
              <button
                onClick={() => onSelectTpl(tpl)}
                className="px-2 py-1 bg-blue-600 text-white rounded text-sm"
              >
                Use
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
