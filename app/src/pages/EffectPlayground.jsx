// File: src/pages/EffectPlayground.jsx
import React, { useState } from 'react';
import EffectControls from '../components/EffectControls';
import WaveformViewer from '../components/WaveformViewer';
import AllWaveforms from '../components/AllWaveforms';
import LightSimulator from '../components/LightSimulator';
import CueListManager from '../components/CueListManager';

export default function EffectPlayground() {
  const [params, setParams] = useState({
    table: 'sine',
    rate: 60,
    size: 50,
    offset: 0,
    length: 100,
    bounce: false,
    direction: 'forward',
  });
  const [showAll, setShowAll] = useState(false);

  return (
    <div className="min-h-screen flex flex-col bg-gray-800">
      {/* No <Header /> here — it's in App.jsx */}
      <div className="flex flex-1 overflow-hidden">
        <aside className="w-1/5 bg-gray-700 p-4 overflow-y-auto">
          <button
            onClick={() => setShowAll(!showAll)}
            className="mb-4 w-full px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white font-semibold rounded"
          >
            {showAll ? 'Single View' : 'Show All Waves'}
          </button>
          {!showAll && (
            <EffectControls params={params} setParams={setParams} />
          )}
        </aside>

        <main className="flex-1 p-4 overflow-y-auto">
          {showAll ? (
            <AllWaveforms params={params} />
          ) : (
            <WaveformViewer params={params} />
          )}
          <LightSimulator params={params} />
        </main>

        <aside className="w-1/5 bg-gray-700 p-4 overflow-y-auto">
          <CueListManager params={params} setParams={setParams} />
        </aside>
      </div>
    </div>
  );
}
