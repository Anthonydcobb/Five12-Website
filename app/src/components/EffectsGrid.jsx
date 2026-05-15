import React from 'react';

const PARAM_LABELS = {
  intensity: 'INT',
  pan: 'PAN',
  tilt: 'TILT',
  red: 'RED',
  green: 'GRN',
  blue: 'BLU',
};

const DEFAULT_BASES = { intensity: 1.0, pan: 0.5, tilt: 0.5, red: 1.0, green: 1.0, blue: 1.0 };

const TABLE_ABBREV = {
  sine: 'SIN',
  tangent: 'TAN',
  sawtooth: 'SAW',
  ramp: 'RMP',
  inverseRamp: 'INV',
  step: 'STP',
  markOn: 'MON',
  markOff: 'MOF',
  spiral: 'SPI',
  random1: 'RNL',
  random2: 'RNH',
  random3: 'RNM',
};

const PARAM_COLORS = {
  intensity: 'text-yellow-300',
  pan: 'text-blue-300',
  tilt: 'text-cyan-300',
  red: 'text-red-300',
  green: 'text-green-300',
  blue: 'text-blue-400',
};

export default function EffectsGrid({ fixtures, selectedCells, onCellClick, paramKeys }) {
  const isSelected = (fi, pk) => selectedCells.has(`${fi}:${pk}`);

  return (
    <div className="overflow-auto flex-1 h-full">
      <table className="text-xs border-collapse w-full">
        <thead className="sticky top-0 z-10 bg-gray-900">
          <tr className="border-b border-gray-700">
            <th className="px-4 py-2 text-left text-gray-500 font-medium w-16">FIX</th>
            {paramKeys.map(pk => (
              <th key={pk} className={`px-2 py-2 text-center font-medium min-w-[80px] ${PARAM_COLORS[pk]}`}>
                {PARAM_LABELS[pk]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {fixtures.map((fix, fi) => (
            <tr key={fix.id} className="border-b border-gray-800 hover:bg-gray-800/30">
              <td className="px-4 py-1 text-gray-500 font-mono text-xs">#{fix.id}</td>
              {paramKeys.map(pk => {
                const param = fix.params[pk];
                const selected = isSelected(fi, pk);
                const hasEffect = param?.table != null;
                return (
                  <td
                    key={pk}
                    onClick={(e) => onCellClick(fi, pk, e)}
                    className={`px-1 py-1 text-center cursor-pointer select-none transition-all ${
                      selected
                        ? 'bg-blue-600 text-white outline outline-2 outline-blue-400 outline-offset-[-2px] z-10 relative'
                        : hasEffect
                        ? 'bg-gray-700/80 hover:bg-gray-700'
                        : 'hover:bg-gray-800/60'
                    }`}
                  >
                    {(() => {
                      const base = fix.bases?.[pk] ?? DEFAULT_BASES[pk];
                      const basePct = Math.round(base * 100);
                      const isDefaultBase = basePct === Math.round(DEFAULT_BASES[pk] * 100);
                      return hasEffect ? (
                        <div className="flex flex-col items-center leading-none gap-0.5 py-0.5">
                          <span className={`font-mono font-bold ${selected ? 'text-white' : PARAM_COLORS[pk]}`}>
                            {TABLE_ABBREV[param.table] || param.table}
                          </span>
                          <span className={`text-[9px] ${selected ? 'text-blue-200' : 'text-gray-500'}`}>
                            {param.rate}cpm
                          </span>
                          {!isDefaultBase && (
                            <span className={`text-[9px] ${selected ? 'text-yellow-200' : 'text-yellow-600'}`}>
                              b:{basePct}%
                            </span>
                          )}
                        </div>
                      ) : isDefaultBase ? (
                        <span className="text-gray-700 text-base leading-none">─</span>
                      ) : (
                        <span className={`text-[10px] ${selected ? 'text-yellow-200' : 'text-yellow-600'}`}>
                          {basePct}%
                        </span>
                      );
                    })()}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
