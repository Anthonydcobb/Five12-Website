import React, { useState, useCallback } from 'react';
import axios from 'axios';

// ── Device type metadata ──────────────────────────────────────────────────────
const TYPE_META = {
  gigacore: { label: 'GigaCore',    color: 'cyan',   dot: 'bg-cyan-400'   },
  swisson:  { label: 'Swisson XND', color: 'green',  dot: 'bg-green-400'  },
  ubiquiti: { label: 'Ubiquiti',    color: 'blue',   dot: 'bg-blue-400'   },
  router:   { label: 'Router',      color: 'amber',  dot: 'bg-amber-400'  },
  host:     { label: 'Host',        color: 'gray',   dot: 'bg-gray-500'   },
};

function typeMeta(type) {
  return TYPE_META[type] || TYPE_META.host;
}

function TypeBadge({ type, small }) {
  const m = typeMeta(type);
  const colorMap = {
    cyan:  'bg-cyan-900/50 text-cyan-300 border-cyan-700/40',
    green: 'bg-green-900/50 text-green-300 border-green-700/40',
    blue:  'bg-blue-900/50 text-blue-300 border-blue-700/40',
    amber: 'bg-amber-900/50 text-amber-300 border-amber-700/40',
    gray:  'bg-gray-700/50 text-gray-400 border-gray-600/40',
  };
  return (
    <span className={`border rounded px-1.5 py-0.5 font-medium ${small ? 'text-xs' : 'text-xs'} ${colorMap[m.color]}`}>
      {m.label}
    </span>
  );
}

// ── Health panel ──────────────────────────────────────────────────────────────
function HealthPanel({ health, elapsed, total }) {
  const errors   = health.filter(h => h.level === 'error');
  const warnings = health.filter(h => h.level === 'warning');
  const infos    = health.filter(h => h.level === 'info');
  const allClear = health.length === 0;

  return (
    <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-gray-300">Network Health</h2>
        <span className="text-xs text-gray-600">{total} host{total !== 1 ? 's' : ''} · {elapsed}s</span>
      </div>

      {allClear ? (
        <div className="flex items-center gap-2 text-green-400 text-sm">
          <span className="text-base">✓</span>
          <span>No issues detected</span>
        </div>
      ) : (
        <div className="space-y-2">
          {[...errors, ...warnings, ...infos].map((issue, i) => (
            <div key={i} className={`flex gap-2 text-sm rounded px-3 py-2 ${
              issue.level === 'error'   ? 'bg-red-900/30 border border-red-700/50 text-red-300' :
              issue.level === 'warning' ? 'bg-yellow-900/30 border border-yellow-700/50 text-yellow-300' :
                                          'bg-gray-700/50 border border-gray-600/50 text-gray-400'
            }`}>
              <span className="shrink-0">
                {issue.level === 'error' ? '✕' : issue.level === 'warning' ? '⚠' : 'ℹ'}
              </span>
              <div>
                <p>{issue.message}</p>
                {issue.ips?.length > 0 && (
                  <p className="text-xs mt-0.5 font-mono opacity-70">{issue.ips.join(', ')}</p>
                )}
                {issue.macs?.length > 0 && (
                  <p className="text-xs mt-0.5 font-mono opacity-70">{issue.macs.join(' · ')}</p>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Device card (lighting nodes + Ubiquiti) ───────────────────────────────────
function DeviceCard({ device, onConfigure, selected }) {
  const m = typeMeta(device.type);
  const colorMap = {
    cyan:  selected ? 'border-cyan-500'  : 'border-gray-700 hover:border-cyan-700',
    green: selected ? 'border-green-500' : 'border-gray-700 hover:border-green-700',
    blue:  selected ? 'border-blue-500'  : 'border-gray-700 hover:border-blue-400',
    amber: selected ? 'border-amber-500' : 'border-gray-700 hover:border-amber-700',
    gray:  selected ? 'border-gray-500'  : 'border-gray-700',
  };
  // GigaCores are deliberately NOT configurable here. They are Ethernet
  // switches: their twelve ports are RJ45 and carry no DMX, so the universe /
  // protocol / merge-mode panel this button opens has nothing to act on. The
  // backend branch behind it was removed for the same reason. They stay listed
  // — the Network tab shows what is plugged into each of their ports — and if
  // real GigaCore configuration arrives (Groups, PoE, port enable) this is
  // where it would go.
  const canConfigure = device.type === 'swisson';

  return (
    <div className={`bg-gray-800 border rounded-lg p-4 transition-colors ${colorMap[m.color]}`}>
      <div className="flex items-start justify-between gap-2 mb-2">
        <TypeBadge type={device.type} />
        <div className={`w-2 h-2 rounded-full shrink-0 mt-0.5 ${m.dot}`} />
      </div>

      <p className="font-mono text-sm text-white mt-2">{device.ip}</p>

      {(device.model || device.title) && (
        <p className="text-xs text-gray-400 mt-1 truncate">{device.model || device.title}</p>
      )}
      {device.hostname && (
        <p className="text-xs text-gray-600 mt-0.5 truncate font-mono">{device.hostname}</p>
      )}
      {device.firmware && (
        <p className="text-xs text-gray-600 mt-0.5">fw {device.firmware}</p>
      )}
      {device.manufacturer && !device.model && (
        <p className="text-xs text-gray-600 mt-0.5">{device.manufacturer}</p>
      )}
      {device.mac && (
        <p className="text-xs text-gray-700 mt-1 font-mono">{device.mac}</p>
      )}

      {canConfigure && (
        <button
          onClick={() => onConfigure(device)}
          className={`mt-3 w-full py-1.5 rounded text-sm font-medium transition-colors ${
            selected
              ? 'bg-blue-600 hover:bg-blue-500 text-white'
              : 'bg-gray-700 hover:bg-gray-600 text-gray-200'
          }`}
        >
          {selected ? 'Configuring…' : 'Configure'}
        </button>
      )}
    </div>
  );
}

// ── Compact host row ──────────────────────────────────────────────────────────
function HostRow({ device }) {
  return (
    <div className="flex items-center gap-3 py-2 border-b border-gray-700/50 last:border-0 text-sm">
      <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${typeMeta(device.type).dot}`} />
      <span className="font-mono text-gray-300 w-32 shrink-0">{device.ip}</span>
      <span className="text-gray-500 truncate">
        {device.hostname || device.title || device.manufacturer || '—'}
      </span>
      {device.mac && (
        <span className="font-mono text-gray-700 text-xs ml-auto shrink-0 hidden sm:block">
          {device.mac}
        </span>
      )}
    </div>
  );
}

// ── Config panel (GigaCore / Swisson) ─────────────────────────────────────────
function CredRow({ creds, onChange }) {
  return (
    <div className="flex gap-2 items-center mt-2">
      <input value={creds.user} onChange={e => onChange({ ...creds, user: e.target.value })}
        placeholder="username"
        className="w-28 bg-gray-900 border border-gray-600 rounded px-2 py-1 text-xs font-mono focus:outline-none focus:border-blue-500" />
      <input type="password" value={creds.pass} onChange={e => onChange({ ...creds, pass: e.target.value })}
        placeholder="password"
        className="w-28 bg-gray-900 border border-gray-600 rounded px-2 py-1 text-xs font-mono focus:outline-none focus:border-blue-500" />
    </div>
  );
}

function PortRow({ port, editing, onEdit, onSave, saving }) {
  const [universe,  setUniverse]  = useState(String(port.universe  ?? ''));
  const [protocol,  setProtocol]  = useState(port.protocol  ?? 'sacn');
  const [mergeMode, setMergeMode] = useState(port.mergeMode ?? 'htp');

  if (editing) return (
    <tr className="border-b border-gray-700 last:border-0 bg-gray-900/40">
      <td className="py-2 px-3 text-gray-400 font-mono text-sm w-14">P{port.port}</td>
      <td className="py-2 px-3">
        <input value={universe} onChange={e => setUniverse(e.target.value)}
          className="w-20 bg-gray-900 border border-gray-600 rounded px-2 py-1 text-xs font-mono focus:outline-none focus:border-blue-500" />
      </td>
      <td className="py-2 px-3">
        <select value={protocol} onChange={e => setProtocol(e.target.value)}
          className="bg-gray-900 border border-gray-600 rounded px-2 py-1 text-xs focus:outline-none focus:border-blue-500">
          <option value="sacn">sACN</option>
          <option value="artnet">Art-Net</option>
        </select>
      </td>
      <td className="py-2 px-3">
        <select value={mergeMode} onChange={e => setMergeMode(e.target.value)}
          className="bg-gray-900 border border-gray-600 rounded px-2 py-1 text-xs focus:outline-none focus:border-blue-500">
          <option value="htp">HTP</option>
          <option value="ltp">LTP</option>
        </select>
      </td>
      <td className="py-2 px-3 flex gap-1">
        <button onClick={() => onSave(port.port, { universe: parseInt(universe,10)||1, protocol, mergeMode })}
          disabled={saving}
          className="text-xs px-2 py-1 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 rounded">
          {saving ? '…' : 'Save'}
        </button>
        <button onClick={() => onEdit(null)} className="text-xs px-2 py-1 bg-gray-700 hover:bg-gray-600 rounded">Cancel</button>
      </td>
    </tr>
  );

  return (
    <tr className="border-b border-gray-700 last:border-0">
      <td className="py-2 px-3 text-gray-400 font-mono text-sm w-14">P{port.port}</td>
      <td className="py-2 px-3 font-mono text-sm">{port.universe ?? '—'}</td>
      <td className="py-2 px-3">
        <span className={`text-xs px-1.5 py-0.5 rounded ${
          String(port.protocol).toLowerCase().includes('sacn')
            ? 'bg-purple-900/50 text-purple-300 border border-purple-700/40'
            : 'bg-amber-900/50 text-amber-300 border border-amber-700/40'
        }`}>{port.protocol || '—'}</span>
      </td>
      <td className="py-2 px-3 text-xs text-gray-400">{port.mergeMode || '—'}</td>
      <td className="py-2 px-3">
        <button onClick={() => onEdit(port.port)} className="text-xs px-2 py-1 bg-gray-700 hover:bg-gray-600 rounded">Edit</button>
      </td>
    </tr>
  );
}

function ConfigPanel({ node, onClose }) {
  const [creds,    setCreds]    = useState({ user: 'admin', pass: 'admin' });
  const [config,   setConfig]   = useState(null);
  const [loading,  setLoading]  = useState(false);
  const [error,    setError]    = useState(null);
  const [editPort, setEditPort] = useState(null);
  const [saving,   setSaving]   = useState(false);
  const [saveErr,  setSaveErr]  = useState(null);
  const [showRaw,  setShowRaw]  = useState(false);

  const load = async () => {
    setLoading(true); setError(null); setConfig(null);
    try {
      const { data } = await axios.get(`/api/nodes/${node.ip}/config`, {
        params: { type: node.type, user: creds.user, pass: creds.pass },
      });
      setConfig(data);
    } catch (e) {
      setError(e.response?.data?.error || 'Failed to read config');
    } finally { setLoading(false); }
  };

  const savePort = async (portId, values) => {
    setSaving(true); setSaveErr(null);
    try {
      await axios.put(`/api/nodes/${node.ip}/config`, {
        type: node.type, portId, ...values,
        user: creds.user, pass: creds.pass, token: config?.token ?? '',
      });
      setEditPort(null);
      load();
    } catch (e) {
      setSaveErr(e.response?.data?.error || 'Save failed');
    } finally { setSaving(false); }
  };

  const ports = config?.ports ?? [];

  return (
    <div className="bg-gray-800 border border-blue-500 rounded-lg p-5">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="font-semibold">
            <TypeBadge type={node.type} />
            <span className="text-gray-400 font-mono text-sm ml-2">{node.ip}</span>
          </h3>
          {node.title && <p className="text-xs text-gray-500 mt-0.5">{node.title}</p>}
        </div>
        <button onClick={onClose} className="text-gray-500 hover:text-white text-xl leading-none">×</button>
      </div>

      <div className="flex items-end gap-3 mb-4">
        <div>
          <span className="text-xs text-gray-500">Credentials</span>
          <CredRow creds={creds} onChange={setCreds} />
        </div>
        <button onClick={load} disabled={loading}
          className="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 rounded text-sm mb-0.5">
          {loading ? 'Reading…' : config ? 'Refresh' : 'Read Config'}
        </button>
      </div>

      {error && (
        <div className="bg-red-900/30 border border-red-700/50 text-red-300 text-xs rounded px-3 py-2 mb-3">
          {error}
        </div>
      )}
      {saveErr && (
        <div className="bg-red-900/30 border border-red-700/50 text-red-300 text-xs rounded px-3 py-2 mb-3">{saveErr}</div>
      )}

      {config && (
        <>
          <div className="flex items-center gap-2 mb-3">
            <span className={`text-xs px-2 py-0.5 rounded-full border ${
              config.method === 'rest'
                ? 'bg-green-900/40 text-green-300 border-green-700/40'
                : 'bg-yellow-900/40 text-yellow-300 border-yellow-700/40'
            }`}>{config.method === 'rest' ? 'REST API' : 'Web scrape'}</span>
            {config.device?.model    && <span className="text-xs text-gray-500">{config.device.model}</span>}
            {config.device?.firmware && <span className="text-xs text-gray-600">fw {config.device.firmware}</span>}
          </div>

          {ports.length > 0 ? (
            <div className="overflow-x-auto rounded border border-gray-700 mb-3">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-700 bg-gray-900/50 text-xs text-gray-500 uppercase tracking-wider">
                    <th className="text-left py-2 px-3">Port</th>
                    <th className="text-left py-2 px-3">Universe</th>
                    <th className="text-left py-2 px-3">Protocol</th>
                    <th className="text-left py-2 px-3">Merge</th>
                    <th className="py-2 px-3"></th>
                  </tr>
                </thead>
                <tbody>
                  {ports.map(p => (
                    <PortRow key={p.port} port={p}
                      editing={editPort === p.port} onEdit={setEditPort}
                      onSave={savePort} saving={saving && editPort === p.port} />
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-gray-500 text-sm mb-3">No port data parsed — check raw response below.</p>
          )}

          {(node.type === 'swisson' || ports.length === 0) && (
            <div>
              <button onClick={() => setShowRaw(v => !v)}
                className="text-xs text-gray-500 hover:text-gray-300 underline mb-2">
                {showRaw ? 'Hide' : 'Show'} raw response
              </button>
              {showRaw && (
                <pre className="bg-gray-900 text-gray-400 text-xs rounded p-3 overflow-auto max-h-64 border border-gray-700">
                  {JSON.stringify(config, null, 2)}
                </pre>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function NodesPage() {
  const [result,   setResult]   = useState(null);
  const [scanning, setScanning] = useState(false);
  const [selected, setSelected] = useState(null);

  const scan = useCallback(async () => {
    setScanning(true);
    setSelected(null);
    try {
      const { data } = await axios.get('/api/nodes/scan');
      setResult(data);
    } catch {
      setResult({ devices: [], health: [], elapsed: 0 });
    } finally {
      setScanning(false);
    }
  }, []);

  const devices   = result?.devices ?? [];
  const health    = result?.health  ?? [];
  const elapsed   = result?.elapsed ?? 0;

  const lighting  = devices.filter(d => d.type === 'gigacore' || d.type === 'swisson');
  const ubiquiti  = devices.filter(d => d.type === 'ubiquiti');
  const routers   = devices.filter(d => d.type === 'router');
  const hosts     = devices.filter(d => d.type === 'host');

  const handleConfigure = (node) =>
    setSelected(prev => prev?.ip === node.ip ? null : node);

  function Section({ title, count, children }) {
    if (count === 0) return null;
    return (
      <section>
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
          {title} <span className="text-gray-700 normal-case font-normal">— {count}</span>
        </h2>
        {children}
      </section>
    );
  }

  return (
    <div className="min-h-screen bg-gray-900 text-white p-6">
      <div className="max-w-4xl mx-auto space-y-5">

        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold">Network Scanner</h1>
            <p className="text-gray-500 text-xs mt-0.5">
              ARP cache + Ubiquiti discovery · GigaCore · Swisson · hosts
            </p>
          </div>
          <button onClick={scan} disabled={scanning}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 rounded text-sm font-medium flex items-center gap-2">
            {scanning && <span className="inline-block w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />}
            {scanning ? 'Scanning…' : result ? 'Scan Again' : 'Scan Network'}
          </button>
        </div>

        {scanning && (
          <p className="text-sm text-gray-500">
            Probing ARP cache, running Ubiquiti discovery broadcast, checking for web interfaces…
          </p>
        )}

        {/* Health */}
        {result && !scanning && (
          <HealthPanel health={health} elapsed={elapsed} total={devices.length} />
        )}

        {/* Lighting nodes */}
        {result && !scanning && (
          <>
            <Section title="Lighting Nodes" count={lighting.length}>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
                {lighting.map(d => (
                  <DeviceCard key={d.ip} device={d}
                    selected={selected?.ip === d.ip} onConfigure={handleConfigure} />
                ))}
              </div>
            </Section>

            {/* Config panel inline */}
            {selected && (
              <ConfigPanel node={selected} onClose={() => setSelected(null)} />
            )}

            <Section title="Ubiquiti" count={ubiquiti.length}>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
                {ubiquiti.map(d => (
                  <DeviceCard key={d.ip} device={d}
                    selected={false} onConfigure={() => {}} />
                ))}
              </div>
            </Section>

            <Section title="Routers & Gateways" count={routers.length}>
              <div className="bg-gray-800 border border-gray-700 rounded-lg divide-y divide-gray-700/50">
                {routers.map(d => <HostRow key={d.ip} device={d} />)}
              </div>
            </Section>

            <Section title="Other Hosts" count={hosts.length}>
              <div className="bg-gray-800 border border-gray-700 rounded-lg divide-y divide-gray-700/50">
                {hosts.map(d => <HostRow key={d.ip} device={d} />)}
              </div>
            </Section>

            {devices.length === 0 && (
              <div className="text-center py-12 text-gray-600">
                <p className="text-sm">No hosts found.</p>
                <p className="text-xs mt-1">Make sure you're on a network and devices have been active recently.</p>
              </div>
            )}
          </>
        )}

        {/* Explainer */}
        {!result && !scanning && (
          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4 text-sm text-gray-500 space-y-1">
            <p className="font-medium text-gray-400">What gets scanned</p>
            <p>ARP cache — all hosts recently seen on your network (instant, no flooding)</p>
            <p>Ubiquiti discovery — UDP broadcast on port 10001 returns model + firmware for GigaBeam, UniFi, EdgeSwitch, etc.</p>
            <p>HTTP probe — each host's web interface is checked for device signatures</p>
            <p>Reverse DNS — hostnames resolved for all found IPs</p>
            <p className="text-gray-600 text-xs pt-1">Health checks: APIPA addresses, IP conflicts, duplicate MACs</p>
          </div>
        )}

      </div>
    </div>
  );
}
