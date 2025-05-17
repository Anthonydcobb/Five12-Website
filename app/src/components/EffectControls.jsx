// File: src/components/EffectControls.jsx
import React from 'react';

export default function EffectControls({ params, setParams }) {
  const updateValue = (key) => (e) => {
    let v = parseFloat(e.target.value);
    if (isNaN(v)) v = 0;
    setParams({ ...params, [key]: v });
  };
  const updateCheckbox = (key) => (e) => {
    setParams({ ...params, [key]: e.target.checked });
  };
  const tableOptions = [
    'sine','tangent','sawtooth','ramp','inverseRamp',
    'step','markOn','markOff','spiral',
    'random1','random2','random3'
  ];

  const sliders = [
    { key: 'rate',    label: 'Rate (CPM)', min: 0,   max: 600 },
    { key: 'size',    label: 'Size (%)',  min: 0,   max: 150 },
    { key: 'offset',  label: 'Offset (°)',min: 0,   max: 360 },
    { key: 'length',  label: 'Length (%)',min: 0,   max: 100 },
  ];

  return (
    <div className="space-y-6">
      {/* Table selector */}
      <div>
        <label className="text-white font-semibold">Table</label>
        <select
          value={params.table}
          onChange={e => setParams({ ...params, table: e.target.value })}
          className="w-full mt-1 p-2 bg-gray-600 text-white rounded"
        >
          {tableOptions.map(opt => (
            <option key={opt} value={opt}>{opt}</option>
          ))}
        </select>
      </div>

      {/* Numeric sliders with typed input */}
      {sliders.map(({ key, label, min, max }) => (
        <div key={key}>
          <label className="text-white font-semibold block">
            {label}: {params[key]}
          </label>
          <div className="flex items-center space-x-2">
            <input
              type="range"
              min={min}
              max={max}
              value={params[key]}
              onChange={updateValue(key)}
              className="flex-1"
            />
            <input
              type="number"
              min={min}
              max={max}
              value={params[key]}
              onChange={updateValue(key)}
              className="w-16 p-1 bg-gray-600 text-white rounded"
            />
          </div>
        </div>
      ))}

      {/* Bounce toggle */}
      <div className="flex items-center space-x-2">
        <input
          type="checkbox"
          checked={params.bounce}
          onChange={updateCheckbox('bounce')}
          className="h-4 w-4"
        />
        <label className="text-white font-semibold">
          Bounce (Ping-Pong)
        </label>
      </div>

      {/* Direction selector */}
      <div>
        <label className="text-white font-semibold">Direction</label>
        <select
          value={params.direction}
          onChange={e => setParams({ ...params, direction: e.target.value })}
          className="w-full mt-1 p-2 bg-gray-600 text-white rounded"
        >
          <option value="forward">Forward</option>
          <option value="reverse">Reverse</option>
        </select>
      </div>
    </div>
  );
}
