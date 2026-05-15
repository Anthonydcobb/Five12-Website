import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';

const PROFILES_KEY = 'five12_ip_profiles';

function prefixToMask(prefix) {
  const n = parseInt(prefix, 10);
  if (isNaN(n) || n < 0 || n > 32) return '';
  const mask = n === 0 ? 0 : (~0 << (32 - n)) >>> 0;
  return [(mask >>> 24) & 255, (mask >>> 16) & 255, (mask >>> 8) & 255, mask & 255].join('.');
}

function maskToPrefix(mask) {
  const parts = mask.split('.').map(Number);
  if (parts.length !== 4 || parts.some(p => isNaN(p))) return null;
  const n = parts.reduce((acc, p) => (acc << 8) | p, 0) >>> 0;
  return (n >>> 0).toString(2).split('').filter(b => b === '1').length;
}

function StatusDot({ status }) {
  const up = status === 'Up';
  return (
    <span className={`inline-block w-2 h-2 rounded-full ${up ? 'bg-green-400' : 'bg-gray-600'}`} />
  );
}

function AdapterCard({ adapter, onConfigure, selected }) {
  return (
    <div
      className={`bg-gray-800 border rounded-lg p-4 cursor-pointer transition-colors ${
        selected ? 'border-blue-500' : 'border-gray-700 hover:border-gray-500'
      }`}
      onClick={() => onConfigure(adapter)}
    >
      <div className="flex items-center justify-between mb-2">
        <span className="font-medium text-sm truncate mr-2">{adapter.name}</span>
        <div className="flex items-center gap-1.5 shrink-0">
          <StatusDot status={adapter.status} />
          <span className="text-xs text-gray-500">{adapter.status}</span>
        </div>
      </div>

      <p className="text-xs text-gray-500 truncate mb-3">{adapter.description}</p>

      <div className="space-y-1 font-mono text-xs">
        {adapter.ip ? (
          <>
            <div className="flex gap-2">
              <span className="text-gray-500 w-8">IP</span>
              <span className="text-white">{adapter.ip}</span>
            </div>
            <div className="flex gap-2">
              <span className="text-gray-500 w-8">SN</span>
              <span className="text-gray-300">{prefixToMask(adapter.prefix)}</span>
              <span className="text-gray-600">/{adapter.prefix}</span>
            </div>
            {adapter.gateway && (
              <div className="flex gap-2">
                <span className="text-gray-500 w-8">GW</span>
                <span className="text-gray-300">{adapter.gateway}</span>
              </div>
            )}
          </>
        ) : (
          <span className="text-gray-600 italic">No IP assigned</span>
        )}
      </div>

      <div className="mt-3 flex items-center justify-between">
        <span className={`text-xs px-2 py-0.5 rounded-full ${
          adapter.dhcp
            ? 'bg-blue-900/50 text-blue-300 border border-blue-700/50'
            : 'bg-gray-700 text-gray-400'
        }`}>
          {adapter.dhcp ? 'DHCP' : 'Static'}
        </span>
        <span className="text-xs text-gray-600 font-mono">{adapter.mac}</span>
      </div>
    </div>
  );
}

function ConfigPanel({ adapter, onClose, onSuccess }) {
  const [mode, setMode]       = useState(adapter.dhcp ? 'dhcp' : 'static');
  const [ip, setIp]           = useState(adapter.ip || '');
  const [prefix, setPrefix]   = useState(String(adapter.prefix || 24));
  const [gateway, setGateway] = useState(adapter.gateway || '');
  const [applying, setApplying] = useState(false);
  const [error, setError]     = useState(null);

  // Allow typing subnet mask or prefix length in the prefix field
  const handlePrefix = (v) => {
    if (v.includes('.')) {
      const p = maskToPrefix(v);
      if (p !== null) setPrefix(String(p));
      else setPrefix(v); // let user keep typing
    } else {
      setPrefix(v);
    }
  };

  const apply = async () => {
    setApplying(true);
    setError(null);
    try {
      if (mode === 'dhcp') {
        await axios.post('/api/network/dhcp', { adapter: adapter.name });
      } else {
        await axios.post('/api/network/apply', {
          adapter:  adapter.name,
          ip,
          prefix:   parseInt(prefix, 10) || 24,
          gateway,
        });
      }
      onSuccess();
    } catch (e) {
      const data = e.response?.data;
      if (data?.adminRequired) {
        setError('Admin required — restart the app as Administrator to change IP settings.');
      } else {
        setError(data?.error || 'Apply failed');
      }
    } finally {
      setApplying(false);
    }
  };

  return (
    <div className="bg-gray-800 border border-blue-500 rounded-lg p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-medium">Configure: <span className="text-blue-300">{adapter.name}</span></h3>
        <button onClick={onClose} className="text-gray-500 hover:text-white text-lg leading-none">×</button>
      </div>

      {/* Mode toggle */}
      <div className="flex bg-gray-900 border border-gray-700 rounded overflow-hidden text-sm mb-4 w-fit">
        {['dhcp', 'static'].map(m => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={`px-4 py-1.5 font-medium transition-colors ${
              mode === m ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-white'
            }`}
          >
            {m === 'dhcp' ? 'DHCP' : 'Static'}
          </button>
        ))}
      </div>

      {mode === 'static' && (
        <div className="grid grid-cols-1 gap-3 mb-4 max-w-sm">
          <label className="block">
            <span className="text-xs text-gray-500 mb-1 block">IP Address</span>
            <input
              value={ip}
              onChange={e => setIp(e.target.value)}
              placeholder="192.168.1.100"
              className="w-full bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm font-mono focus:outline-none focus:border-blue-500"
            />
          </label>
          <label className="block">
            <span className="text-xs text-gray-500 mb-1 block">Subnet (mask or /prefix)</span>
            <div className="flex items-center gap-2">
              <input
                value={prefix.includes('.') ? prefix : prefixToMask(prefix)}
                onChange={e => handlePrefix(e.target.value)}
                placeholder="255.255.255.0"
                className="w-full bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm font-mono focus:outline-none focus:border-blue-500"
              />
              <span className="text-gray-500 text-sm font-mono whitespace-nowrap">
                /{prefix.includes('.') ? (maskToPrefix(prefix) ?? '?') : prefix}
              </span>
            </div>
          </label>
          <label className="block">
            <span className="text-xs text-gray-500 mb-1 block">Default Gateway</span>
            <input
              value={gateway}
              onChange={e => setGateway(e.target.value)}
              placeholder="192.168.1.1"
              className="w-full bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm font-mono focus:outline-none focus:border-blue-500"
            />
          </label>
        </div>
      )}

      {mode === 'dhcp' && (
        <p className="text-sm text-gray-400 mb-4">
          Switch this adapter to DHCP — the router will assign an IP automatically.
        </p>
      )}

      {error && (
        <div className="bg-red-900/30 border border-red-700/50 text-red-300 text-xs rounded px-3 py-2 mb-3">
          {error}
        </div>
      )}

      <button
        onClick={apply}
        disabled={applying}
        className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 rounded text-sm font-medium"
      >
        {applying ? 'Applying…' : 'Apply'}
      </button>
    </div>
  );
}

function ProfileSection({ adapters, onApply }) {
  const [profiles, setProfiles] = useState(() => {
    try { return JSON.parse(localStorage.getItem(PROFILES_KEY) || '[]'); }
    catch { return []; }
  });
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: '', adapter: '', ip: '', prefix: '24', gateway: '' });
  const [applying, setApplying] = useState(null);
  const [error, setError] = useState(null);

  const save = () => {
    if (!form.name || !form.adapter || !form.ip) return;
    const updated = [...profiles, { ...form, id: Date.now() }];
    setProfiles(updated);
    localStorage.setItem(PROFILES_KEY, JSON.stringify(updated));
    setShowForm(false);
    setForm({ name: '', adapter: '', ip: '', prefix: '24', gateway: '' });
  };

  const remove = (id) => {
    const updated = profiles.filter(p => p.id !== id);
    setProfiles(updated);
    localStorage.setItem(PROFILES_KEY, JSON.stringify(updated));
  };

  const applyProfile = async (profile) => {
    setApplying(profile.id);
    setError(null);
    try {
      await axios.post('/api/network/apply', {
        adapter: profile.adapter,
        ip:      profile.ip,
        prefix:  parseInt(profile.prefix, 10) || 24,
        gateway: profile.gateway,
      });
      onApply();
    } catch (e) {
      const data = e.response?.data;
      setError(data?.adminRequired
        ? 'Admin required — restart as Administrator.'
        : (data?.error || 'Apply failed'));
    } finally {
      setApplying(null);
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">Saved Profiles</h2>
        <button
          onClick={() => setShowForm(v => !v)}
          className="text-xs px-3 py-1 bg-gray-700 hover:bg-gray-600 rounded"
        >
          {showForm ? 'Cancel' : '+ New Profile'}
        </button>
      </div>

      {error && (
        <div className="bg-red-900/30 border border-red-700/50 text-red-300 text-xs rounded px-3 py-2 mb-3">
          {error}
        </div>
      )}

      {showForm && (
        <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 mb-3 grid grid-cols-2 gap-3">
          {[
            { label: 'Profile Name', key: 'name', placeholder: 'sACN Network' },
            { label: 'IP Address',   key: 'ip',   placeholder: '192.168.0.2' },
            { label: 'Subnet Prefix', key: 'prefix', placeholder: '24' },
            { label: 'Default Gateway', key: 'gateway', placeholder: '192.168.0.1' },
          ].map(({ label, key, placeholder }) => (
            <label key={key} className="block">
              <span className="text-xs text-gray-500 mb-1 block">{label}</span>
              <input
                value={form[key]}
                onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
                placeholder={placeholder}
                className="w-full bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm font-mono focus:outline-none focus:border-blue-500"
              />
            </label>
          ))}
          <label className="block col-span-2">
            <span className="text-xs text-gray-500 mb-1 block">Adapter</span>
            <select
              value={form.adapter}
              onChange={e => setForm(f => ({ ...f, adapter: e.target.value }))}
              className="w-full bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-blue-500"
            >
              <option value="">Select adapter…</option>
              {adapters.map(a => (
                <option key={a.name} value={a.name}>{a.name} — {a.description}</option>
              ))}
            </select>
          </label>
          <div className="col-span-2 flex justify-end">
            <button
              onClick={save}
              disabled={!form.name || !form.adapter || !form.ip}
              className="px-4 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 rounded text-sm"
            >
              Save Profile
            </button>
          </div>
        </div>
      )}

      {profiles.length === 0 && !showForm && (
        <p className="text-gray-600 text-sm">No saved profiles yet. Create one to quick-switch IP configs.</p>
      )}

      <div className="space-y-2">
        {profiles.map(p => (
          <div key={p.id} className="flex items-center justify-between bg-gray-800 border border-gray-700 rounded-lg px-4 py-3">
            <div>
              <span className="font-medium text-sm">{p.name}</span>
              <div className="font-mono text-xs text-gray-500 mt-0.5">
                {p.adapter} · {p.ip}/{p.prefix}{p.gateway ? ` · GW ${p.gateway}` : ''}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => applyProfile(p)}
                disabled={applying === p.id}
                className="text-xs px-3 py-1.5 bg-blue-700 hover:bg-blue-600 disabled:opacity-40 rounded font-medium"
              >
                {applying === p.id ? 'Applying…' : 'Apply'}
              </button>
              <button
                onClick={() => remove(p.id)}
                className="text-xs px-2 py-1.5 text-gray-500 hover:text-red-400 rounded"
              >
                ×
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function IPConfig() {
  const [adapters, setAdapters]   = useState([]);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState(null);
  const [selected, setSelected]   = useState(null);
  const [success, setSuccess]     = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await axios.get('/api/network/interfaces');
      setAdapters(data);
    } catch {
      setError('Failed to load network interfaces.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleSuccess = () => {
    setSelected(null);
    setSuccess(true);
    setTimeout(() => setSuccess(false), 3000);
    load();
  };

  const selectedAdapter = adapters.find(a => a.name === selected);

  return (
    <div className="min-h-screen bg-gray-900 text-white p-6">
      <div className="max-w-4xl mx-auto space-y-6">

        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold">IP Config</h1>
            <p className="text-gray-500 text-xs mt-0.5">View and manage network adapter addresses</p>
          </div>
          <button
            onClick={load}
            disabled={loading}
            className="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 disabled:opacity-40 rounded text-sm"
          >
            {loading ? 'Loading…' : 'Refresh'}
          </button>
        </div>

        {success && (
          <div className="bg-green-900/30 border border-green-700/50 text-green-300 text-sm rounded px-4 py-2">
            Applied successfully. It may take a moment for the new address to become active.
          </div>
        )}

        {error && (
          <div className="bg-red-900/30 border border-red-700/50 text-red-300 text-sm rounded px-4 py-2">
            {error}
          </div>
        )}

        {/* Adapters */}
        <div>
          <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">
            Network Adapters
            {adapters.length > 0 && <span className="ml-2 text-gray-600 normal-case font-normal">— click to configure</span>}
          </h2>

          {loading && adapters.length === 0 ? (
            <p className="text-gray-600 text-sm">Loading adapters…</p>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {adapters.map(a => (
                <AdapterCard
                  key={a.name}
                  adapter={a}
                  selected={selected === a.name}
                  onConfigure={a => setSelected(prev => prev === a.name ? null : a.name)}
                />
              ))}
            </div>
          )}
        </div>

        {/* Config panel */}
        {selectedAdapter && (
          <ConfigPanel
            adapter={selectedAdapter}
            onClose={() => setSelected(null)}
            onSuccess={handleSuccess}
          />
        )}

        {/* Saved profiles */}
        <ProfileSection adapters={adapters} onApply={handleSuccess} />

      </div>
    </div>
  );
}
