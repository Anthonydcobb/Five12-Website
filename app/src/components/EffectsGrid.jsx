import React from 'react';

const PARAM_LABELS = {
  intensity: 'INT',
  pan:       'PAN',
  tilt:      'TILT',
  red:       'RED',
  green:     'GRN',
  blue:      'BLU',
};

const DEFAULT_BASES = { intensity: 1.0, pan: 0.5, tilt: 0.5, red: 1.0, green: 1.0, blue: 1.0 };

const TABLE_ABBREV = {
  sine: 'SIN', tangent: 'TAN', sawtooth: 'SAW', ramp: 'RMP',
  inverseRamp: 'INV', step: 'STP', markOn: 'MON', markOff: 'MOF',
  spiral: 'SPI', random1: 'RNL', random2: 'RNH', random3: 'RNM',
};

const PARAM_COLORS = {
  intensity: { text: 'text-yellow-400',  dim: 'text-yellow-800',  bg: 'bg-yellow-900/20' },
  pan:       { text: 'text-blue-400',    dim: 'text-blue-900',    bg: 'bg-blue-900/20'   },
  tilt:      { text: 'text-cyan-400',    dim: 'text-cyan-900',    bg: 'bg-cyan-900/20'   },
  red:       { text: 'text-red-400',     dim: 'text-red-900',     bg: 'bg-red-900/20'    },
  green:     { text: 'text-green-400',   dim: 'text-green-900',   bg: 'bg-green-900/20'  },
  blue:      { text: 'text-blue-300',    dim: 'text-blue-950',    bg: 'bg-blue-950/30'   },
};

const VIEW_MODES = ['Table', 'Rate', 'Size', 'Offset', 'Length', 'N-Shot'];

function getCellValue(param, mode) {
  if (!param?.table) return null;
  switch (mode) {
    case 'Table':  return TABLE_ABBREV[param.table] || param.table;
    case 'Rate':   return `${param.rate ?? 60}`;
    case 'Size':   return `${param.size ?? 50}%`;
    case 'Offset': return `${param.offset ?? 0}°`;
    case 'Length': return `${param.length ?? 100}%`;
    case 'N-Shot': return param.nShot != null ? `${param.nShot}×` : '∞';
    default:       return TABLE_ABBREV[param.table] || param.table;
  }
}

export default function EffectsGrid({ fixtures, selectedCells, onCellClick, paramKeys, viewMode, onViewModeChange }) {
  const isSelected = (fi, pk) => selectedCells.has(`${fi}:${pk}`);

  return (
    <div className="flex flex-col h-full bg-[#0d0d0d]">

      {/* ── View Mode Bar ──────────────────────────────────────────────── */}
      <div className="flex items-center gap-px px-2 py-1 bg-[#0a0a0a] border-b border-[#1c1c1c] flex-shrink-0">
        <span className="text-[8px] text-gray-700 uppercase tracking-widest mr-2">View</span>
        {VIEW_MODES.map(mode => (
          <button
            key={mode}
            onClick={() => onViewModeChange(mode)}
            className={`px-2.5 py-1 text-[9px] font-mono tracking-wide rounded-sm transition-all leading-none border ${
              viewMode === mode
                ? 'bg-blue-600 border-blue-500 text-white shadow-[0_0_4px_rgba(59,130,246,0.4)]'
                : 'bg-[#141414] border-[#222] text-gray-500 hover:text-gray-300 hover:border-gray-600'
            }`}
          >
            {mode.toUpperCase()}
          </button>
        ))}
      </div>

      {/* ── Grid ───────────────────────────────────────────────────────── */}
      <div className="overflow-auto flex-1">
        <table className="text-xs border-collapse w-full">
          <thead className="sticky top-0 z-10 bg-[#0a0a0a]">
            <tr className="border-b border-[#1c1c1c]">
              <th className="px-3 py-1.5 text-left text-gray-600 font-mono text-[10px] w-14 border-r border-[#1c1c1c]">
                FIX
              </th>
              {paramKeys.map(pk => (
                <th key={pk} className={`px-2 py-1.5 text-center font-mono text-[10px] min-w-[76px] tracking-widest ${PARAM_COLORS[pk]?.text || 'text-gray-400'}`}>
                  {PARAM_LABELS[pk]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {fixtures.map((fix, fi) => (
              <tr key={fix.id} className="border-b border-[#141414] hover:bg-[#111]/60">
                <td className="px-3 py-1 text-gray-600 font-mono text-[10px] border-r border-[#1c1c1c]">
                  #{fix.id}
                </td>
                {paramKeys.map(pk => {
                  const param    = fix.params[pk];
                  const selected = isSelected(fi, pk);
                  const hasEffect = param?.table != null;
                  const base     = fix.bases?.[pk] ?? DEFAULT_BASES[pk];
                  const basePct  = Math.round(base * 100);
                  const isDefaultBase = basePct === Math.round(DEFAULT_BASES[pk] * 100);
                  const colors   = PARAM_COLORS[pk] || { text: 'text-gray-400', dim: 'text-gray-700', bg: '' };

                  const displayVal = getCellValue(param, viewMode);

                  return (
                    <td
                      key={pk}
                      onClick={(e) => onCellClick(fi, pk, e)}
                      className={`px-1 py-1 text-center cursor-pointer select-none transition-all ${
                        selected
                          ? 'bg-blue-600/30 outline outline-2 outline-blue-500 outline-offset-[-2px] z-10 relative shadow-[inset_0_0_8px_rgba(59,130,246,0.2)]'
                          : hasEffect
                          ? `${colors.bg} hover:brightness-125`
                          : 'hover:bg-[#181818]'
                      }`}
                    >
                      {hasEffect ? (
                        <div className="flex flex-col items-center leading-none gap-0.5 py-0.5">
                          {/* Primary value based on view mode */}
                          <span className={`font-mono font-bold text-[11px] ${selected ? 'text-white' : colors.text}`}>
                            {displayVal}
                          </span>
                          {/* Secondary info — show table abbrev when NOT in Table view */}
                          {viewMode !== 'Table' && (
                            <span className={`text-[8px] ${selected ? 'text-blue-300/70' : 'text-gray-600'}`}>
                              {TABLE_ABBREV[param.table] || param.table}
                            </span>
                          )}
                          {/* Rate when in Table view */}
                          {viewMode === 'Table' && (
                            <span className={`text-[8px] ${selected ? 'text-blue-200/60' : 'text-gray-600'}`}>
                              {param.rate ?? 60}cpm
                            </span>
                          )}
                          {/* Non-default base indicator */}
                          {!isDefaultBase && (
                            <span className={`text-[8px] ${selected ? 'text-amber-200/70' : 'text-amber-700'}`}>
                              b:{basePct}%
                            </span>
                          )}
                        </div>
                      ) : isDefaultBase ? (
                        <span className="text-[#222] text-base leading-none">─</span>
                      ) : (
                        <span className={`text-[10px] ${selected ? 'text-amber-200' : 'text-amber-700'}`}>
                          {basePct}%
                        </span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
