import React, { useState, useEffect, useRef, useCallback } from 'react';

const IS_ELECTRON = typeof window !== 'undefined' && typeof window.networkMonitor !== 'undefined';

// ── Canvas DMX display ────────────────────────────────────────────────────────
function DMXCanvas({ channels }) {
  const canvasRef  = useRef(null);
  const [hover, setHover] = useState(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const W   = canvas.width;
    const H   = canvas.height;
    const barW = W / 512;

    ctx.fillStyle = '#111827';
    ctx.fillRect(0, 0, W, H);

    if (!channels) return;

    for (let i = 0; i < 512; i++) {
      const val = channels[i] ?? 0;
      if (val === 0) continue;
      const pct  = val / 255;
      const barH = pct * H;
      // green → amber → red as level rises
      const hue  = Math.round(120 - pct * 120);
      ctx.fillStyle = `hsl(${hue}, 85%, 50%)`;
      ctx.fillRect(Math.floor(i * barW), H - barH, Math.max(1, Math.ceil(barW) - 1), barH);
    }
  }, [channels]);

  const onMouseMove = useCallback((e) => {
    const canvas = canvasRef.current;
    if (!canvas || !channels) return;
    const rect  = canvas.getBoundingClientRect();
    const x     = e.clientX - rect.left;
    const idx   = Math.floor((x / rect.width) * 512);
    if (idx >= 0 && idx < 512) {
      setHover({ ch: idx + 1, val: channels[idx] ?? 0 });
    }
  }, [channels]);

  return (
    <div>
      <canvas
        ref={canvasRef}
        width={1024}
        height={96}
        className="w-full rounded bg-gray-950 cursor-crosshair"
        onMouseMove={onMouseMove}
        onMouseLeave={() => setHover(null)}
      />
      <div className="flex justify-between text-xs text-gray-600 font-mono mt-0.5 px-0.5 select-none">
        {[1, 65, 129, 193, 257, 321, 385, 449, 512].map(n => (
          <span key={n}>{n}</span>
        ))}
      </div>
      <div className="h-5 mt-0.5">
        {hover && (
          <span className="text-xs font-mono text-gray-400">
            Ch <span className="text-white">{hover.ch}</span>
            {'  '}
            <span className="text-amber-300">{hover.val}</span>
            <span className="text-gray-600"> / 255</span>
            {'  '}
            <span className="text-gray-500">({Math.round(hover.val / 255 * 100)}%)</span>
          </span>
        )}
      </div>
    </div>
  );
}

// ── Universe row ──────────────────────────────────────────────────────────────
function UniverseRow({ universe, sourceName, isExpanded, channels, onToggle }) {
  return (
    <div className="bg-gray-800 rounded-lg overflow-hidden border border-gray-700">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-gray-750 transition-colors text-left"
      >
        <div className="flex items-center gap-3">
          <span className="text-sm font-mono font-bold bg-gray-700 text-white px-2.5 py-0.5 rounded">
            U{universe}
          </span>
          {sourceName && (
            <span className="text-gray-400 text-sm">{sourceName}</span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <div className="w-2 h-2 bg-green-400 rounded-full animate-pulse" />
          <span className="text-gray-500 text-xs">{isExpanded ? '▲' : '▼'}</span>
        </div>
      </button>

      {isExpanded && (
        <div className="border-t border-gray-700 px-4 pt-3 pb-4">
          {channels
            ? <DMXCanvas channels={channels} />
            : <p className="text-gray-500 text-xs py-2">Waiting for data…</p>
          }
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function NetworkMonitor() {
  const [protocol,  setProtocol]  = useState('sacn');
  const [running,   setRunning]   = useState(false);
  const [universes, setUniverses] = useState([]);
  const [expanded,  setExpanded]  = useState(null);
  const [channelMap, setChannelMap] = useState({});   // universe# → channels[]

  // Wire up IPC listeners while running
  useEffect(() => {
    if (!IS_ELECTRON || !running) return;

    const unsubU = window.networkMonitor.onUniverses(setUniverses);
    const unsubC = window.networkMonitor.onChannels(({ universe, channels }) => {
      setChannelMap(prev => ({ ...prev, [universe]: channels }));
    });

    return () => { unsubU(); unsubC(); };
  }, [running]);

  const start = () => {
    if (!IS_ELECTRON) return;
    window.networkMonitor.start(protocol);
    setRunning(true);
    setUniverses([]);
    setExpanded(null);
    setChannelMap({});
  };

  const stop = () => {
    window.networkMonitor.stop();
    setRunning(false);
    setUniverses([]);
    setExpanded(null);
    setChannelMap({});
  };

  const toggle = (universe) => {
    if (expanded === universe) {
      setExpanded(null);
      window.networkMonitor.unsubscribe();
    } else {
      setExpanded(universe);
      window.networkMonitor.subscribe(universe);
    }
  };

  const switchProtocol = (p) => {
    if (running) stop();
    setProtocol(p);
  };

  return (
    <div className="min-h-screen bg-gray-900 text-white p-6">
      <div className="max-w-4xl mx-auto">

        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-xl font-bold">Network Monitor</h1>
            <p className="text-gray-500 text-xs mt-0.5">
              Live DMX over {protocol === 'sacn' ? 'sACN E1.31 (port 5568)' : 'Art-Net (port 6454)'}
            </p>
          </div>

          <div className="flex items-center gap-3">
            {/* Protocol toggle */}
            <div className="flex bg-gray-800 border border-gray-700 rounded overflow-hidden text-sm">
              {['sacn', 'artnet'].map(p => (
                <button
                  key={p}
                  onClick={() => switchProtocol(p)}
                  className={`px-3 py-1.5 font-medium transition-colors ${
                    protocol === p
                      ? 'bg-blue-600 text-white'
                      : 'text-gray-400 hover:text-white'
                  }`}
                >
                  {p === 'sacn' ? 'sACN' : 'Art-Net'}
                </button>
              ))}
            </div>

            {/* Start / Stop */}
            {!running ? (
              <button
                onClick={start}
                disabled={!IS_ELECTRON}
                className="px-4 py-2 bg-green-600 hover:bg-green-500 disabled:opacity-40 rounded text-sm font-medium"
              >
                Start
              </button>
            ) : (
              <button
                onClick={stop}
                className="px-4 py-2 bg-red-600 hover:bg-red-500 rounded text-sm font-medium"
              >
                Stop
              </button>
            )}

            {running && (
              <div className="flex items-center gap-1.5 text-green-400 text-xs">
                <div className="w-2 h-2 bg-green-400 rounded-full animate-pulse" />
                Listening
              </div>
            )}
          </div>
        </div>

        {/* Not in Electron warning */}
        {!IS_ELECTRON && (
          <div className="bg-yellow-900/30 border border-yellow-700/50 rounded-lg p-4 text-yellow-300 text-sm mb-6">
            Network monitoring requires the desktop app — not available in the browser.
          </div>
        )}

        {/* Empty state */}
        {IS_ELECTRON && running && universes.length === 0 && (
          <div className="text-center py-16 text-gray-600">
            <div className="text-4xl mb-3">📡</div>
            <p className="text-sm">Listening for {protocol === 'sacn' ? 'sACN' : 'Art-Net'} traffic…</p>
            <p className="text-xs mt-1">Make sure you're on the same VLAN as the console.</p>
          </div>
        )}

        {/* Universe count badge */}
        {universes.length > 0 && (
          <div className="flex items-center gap-2 mb-3">
            <span className="text-xs text-gray-500">
              {universes.length} universe{universes.length !== 1 ? 's' : ''} active
            </span>
          </div>
        )}

        {/* Universe list */}
        <div className="space-y-2">
          {universes.map(({ universe, sourceName }) => (
            <UniverseRow
              key={universe}
              universe={universe}
              sourceName={sourceName}
              isExpanded={expanded === universe}
              channels={expanded === universe ? channelMap[universe] ?? null : null}
              onToggle={() => toggle(universe)}
            />
          ))}
        </div>

      </div>
    </div>
  );
}
