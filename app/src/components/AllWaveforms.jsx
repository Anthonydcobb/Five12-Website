// File: src/components/AllWaveforms.jsx
import React from 'react';
import WaveformViewer from './WaveformViewer';

const TABLES = [
  'sine',
  'tangent',
  'sawtooth',
  'ramp',
  'inverseRamp',
  'step',
  'markOn',
  'markOff',
  'spiral',
  'random1',
  'random2',
  'random3'
];

export default function AllWaveforms({ params }) {
  return (
    <div className="
      grid 
      grid-cols-1           /* 1 column on very small screens */
      sm:grid-cols-2        /* ≥640px: 2 cols */
      md:grid-cols-3        /* ≥768px: 3 cols */
      lg:grid-cols-4        /* ≥1024px: 4 cols */
      gap-6 
      p-4
    ">
      {TABLES.map((table) => (
        <div
          key={table}
          className="bg-gray-800 p-4 rounded-2xl shadow-lg"
        >
          <h4 className="text-white capitalize mb-2">{table}</h4>
          <WaveformViewer
            params={{ ...params, table }}
            width={300}    // override canvas width
            height={120}   // override canvas height
          />
        </div>
      ))}
    </div>
  );
}
