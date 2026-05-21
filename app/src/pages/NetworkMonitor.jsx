import React, { useState, useEffect, useCallback, useRef } from 'react';
import axios from 'axios';

// ── Helpers ───────────────────────────────────────────────────────────────────

function timeAgo(iso) {
  if (!iso) return 'never';
  const secs = Math.floor((Date.now() - new Date(iso)) / 1000);
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  return `${Math.floor(secs / 3600)}h ago`;
}

function isOnline(device) {
  if (!device.lastSeen) return false;
  return (Date.now() - new Date(device.lastSeen)) < 90_000; // 90s threshold
}

function formatDate(iso) {
  if (!iso) return '';
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

// ── Sidebar ───────────────────────────────────────────────────────────────────

function Sidebar({ subnets, locations, devices, selectedSubnet, selectedLocation, onSelectSubnet, onSelectLocation, onSaveLocation }) {
  function onlineCount(subnetId) {
    return devices.filter(d => d.subnetId === subnetId && isOnline(d)).length;
  }
  function totalCount(subnetId) {
    return devices.filter(d => d.subnetId === subnetId).length;
  }

  return (
    <div style={{ width: 148, flexShrink: 0, background: '#111', borderRight: '1px solid #222', padding: '12px 0', display: 'flex', flexDirection: 'column', gap: 0 }}>
      <div style={{ padding: '0 10px', color: '#555', fontSize: 9, letterSpacing: 1, marginBottom: 6 }}>NETWORKS</div>
      {subnets.map(s => {
        const active = selectedSubnet === s.id && !selectedLocation;
        return (
          <button
            key={s.id}
            onClick={() => { onSelectSubnet(s.id); }}
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '5px 10px', margin: '1px 4px', borderRadius: 4,
              background: active ? '#1e3a5f' : 'transparent',
              border: 'none', cursor: 'pointer', color: s.color || '#7dd3fc',
              fontSize: 10, textAlign: 'left',
            }}
          >
            <span>● {s.label}</span>
            <span style={{ color: '#555', fontSize: 9 }}>{onlineCount(s.id)}/{totalCount(s.id)}</span>
          </button>
        );
      })}
      {subnets.length === 0 && (
        <div style={{ padding: '4px 10px', color: '#444', fontSize: 10 }}>No subnets configured</div>
      )}

      <div style={{ padding: '8px 10px 4px', color: '#555', fontSize: 9, letterSpacing: 1, borderTop: '1px solid #1a1a1a', marginTop: 8 }}>LOCATIONS</div>
      {locations.map(loc => {
        const active = selectedLocation === loc.id;
        return (
          <button
            key={loc.id}
            onClick={() => onSelectLocation(loc.id)}
            style={{
              display: 'block', width: '100%', padding: '5px 10px', margin: '1px 4px',
              borderRadius: 4, background: active ? '#1a2a1a' : 'transparent',
              border: 'none', cursor: 'pointer', color: active ? '#86efac' : '#888',
              fontSize: 10, textAlign: 'left',
            }}
          >
            {loc.name}
          </button>
        );
      })}
      <button
        onClick={onSaveLocation}
        style={{ padding: '5px 10px', margin: '4px 4px 0', border: 'none', background: 'transparent', color: '#444', fontSize: 10, cursor: 'pointer', textAlign: 'left', fontStyle: 'italic' }}
      >
        + Save current...
      </button>
    </div>
  );
}

// ── Device list ───────────────────────────────────────────────────────────────

function DeviceRow({ device, selected, onClick }) {
  const online = isOnline(device);
  const name = device.label || device.lastIp || device.macAddress;

  return (
    <div
      onClick={onClick}
      style={{
        background: selected ? '#1e3a5f' : online ? '#141414' : '#1a0f0f',
        border: `1px solid ${selected ? '#2a4a7f' : online ? '#222' : '#2a1010'}`,
        borderRadius: 4, padding: '7px 8px', marginBottom: 4, cursor: 'pointer',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ color: online ? '#fff' : '#f87171', fontSize: 11 }}>
          {online ? '🟢' : '🔴'} {name}
        </span>
        {online && device.lastIp && (
          <a
            href={`http://${device.lastIp}`} target="_blank" rel="noreferrer"
            onClick={e => e.stopPropagation()}
            style={{ color: '#7dd3fc', fontSize: 9, textDecoration: 'none' }}
          >↗</a>
        )}
      </div>
      {online && device.lastIp && (
        <div style={{ color: '#7dd3fc', fontSize: 9, marginTop: 2 }}>{device.lastIp}</div>
      )}
      {!online && (
        <div style={{ color: '#f87171', fontSize: 9, marginTop: 2 }}>offline · last seen {timeAgo(device.lastSeen)}</div>
      )}
      {!device.label && online && (
        <div style={{ color: '#f59e0b', fontSize: 9, marginTop: 1 }}>⚠ unlabeled</div>
      )}
      {device.notes && (
        <div style={{ color: '#475569', fontSize: 9, marginTop: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          "{device.notes}"
        </div>
      )}
    </div>
  );
}

function DeviceList({ devices, subnets, selectedSubnet, selectedLocation, locationDevices, selectedDevice, onSelectDevice }) {
  let list = selectedLocation
    ? locationDevices
    : selectedSubnet
      ? devices.filter(d => d.subnetId === selectedSubnet)
      : devices;

  if (!selectedLocation) {
    list = [...list].sort((a, b) => {
      const ao = isOnline(a), bo = isOnline(b);
      if (ao !== bo) return ao ? -1 : 1;
      if (!a.label && b.label) return 1;
      if (a.label && !b.label) return -1;
      return 0;
    });
  }

  const subnet = selectedSubnet ? subnets.find(s => s.id === selectedSubnet) : null;
  const online = list.filter(d => isOnline(d)).length;

  return (
    <div style={{ width: 220, flexShrink: 0, background: '#0f0f0f', borderRight: '1px solid #1a1a1a', padding: 8, overflowY: 'auto' }}>
      <div style={{ color: subnet?.color || '#7dd3fc', fontSize: 10, marginBottom: 8 }}>
        {selectedLocation ? 'Snapshot devices' : subnet ? `${subnet.label} · ${online} online` : `All networks · ${online} online`}
      </div>
      {list.length === 0 && (
        <div style={{ color: '#333', fontSize: 10, textAlign: 'center', marginTop: 24 }}>No devices yet</div>
      )}
      {list.map(d => (
        <DeviceRow
          key={d.macAddress}
          device={d}
          selected={selectedDevice?.macAddress === d.macAddress}
          onClick={() => onSelectDevice(d)}
        />
      ))}
    </div>
  );
}

// ── Device detail ─────────────────────────────────────────────────────────────

function MetaCell({ label, value }) {
  return (
    <div style={{ background: '#1a1a1a', borderRadius: 4, padding: 7 }}>
      <div style={{ color: '#555', fontSize: 9, letterSpacing: 1 }}>{label}</div>
      <div style={{ color: '#ccc', fontSize: 10, marginTop: 2 }}>{value || '—'}</div>
    </div>
  );
}

function DeviceDetail({ device, locations, onUpdate }) {
  const [editingLabel, setEditingLabel] = useState(false);
  const [labelVal, setLabelVal] = useState('');
  const [notesVal, setNotesVal] = useState('');
  const labelRef = useRef(null);

  useEffect(() => {
    setLabelVal(device.label || '');
    setNotesVal(device.notes || '');
    setEditingLabel(false);
  }, [device.macAddress]);

  useEffect(() => {
    if (editingLabel) labelRef.current?.focus();
  }, [editingLabel]);

  const saveLabel = () => {
    setEditingLabel(false);
    if (labelVal !== (device.label || '')) onUpdate(device.macAddress, { label: labelVal });
  };

  const saveNotes = () => {
    if (notesVal !== (device.notes || '')) onUpdate(device.macAddress, { notes: notesVal });
  };

  const online = isOnline(device);
  const vd = device.vendorData || {};

  const appearances = locations.filter(loc =>
    (loc.devices || []).some(ld => ld.macAddress === device.macAddress)
  );

  return (
    <div style={{ flex: 1, background: '#0a0a0a', padding: 14, overflowY: 'auto', height: '100%', boxSizing: 'border-box' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
        <div>
          {editingLabel ? (
            <input
              ref={labelRef}
              value={labelVal}
              onChange={e => setLabelVal(e.target.value)}
              onBlur={saveLabel}
              onKeyDown={e => e.key === 'Enter' && saveLabel()}
              style={{ background: '#1a1a1a', border: '1px solid #7dd3fc', borderRadius: 4, color: '#fff', fontSize: 13, fontWeight: 'bold', padding: '2px 6px', width: 180 }}
            />
          ) : (
            <div
              onClick={() => setEditingLabel(true)}
              style={{ color: '#fff', fontSize: 13, fontWeight: 'bold', cursor: 'text' }}
              title="Click to edit label"
            >
              {device.label || <span style={{ color: '#444' }}>Unlabeled device</span>}
            </div>
          )}
          {device.lastIp && (
            <a href={`http://${device.lastIp}`} target="_blank" rel="noreferrer"
              style={{ color: '#7dd3fc', fontSize: 10, textDecoration: 'underline', marginTop: 2, display: 'block' }}>
              http://{device.lastIp} ↗ Open device GUI
            </a>
          )}
        </div>
        <div style={{
          background: online ? '#22c55e22' : '#ef444422',
          color: online ? '#22c55e' : '#ef4444',
          padding: '3px 8px', borderRadius: 4, fontSize: 10,
        }}>
          ● {online ? 'ONLINE' : 'OFFLINE'}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, marginBottom: 10 }}>
        <MetaCell label="MAC ADDRESS" value={device.macAddress} />
        <MetaCell label="DEVICE TYPE" value={device.deviceType} />
        <MetaCell label="FIRMWARE" value={vd.firmware} />
        <MetaCell label="UPTIME" value={vd.uptime} />
        <MetaCell label="PORTS" value={vd.portCount ? `${vd.portCount} · ${vd.activePorts ?? '?'} active` : null} />
        <MetaCell label="LAST SEEN" value={device.lastSeen ? timeAgo(device.lastSeen) : 'never'} />
      </div>

      <div style={{ background: '#1a1a1a', borderRadius: 4, padding: 8, marginBottom: 8 }}>
        <div style={{ color: '#555', fontSize: 9, letterSpacing: 1, marginBottom: 4 }}>NOTES</div>
        <textarea
          value={notesVal}
          onChange={e => setNotesVal(e.target.value)}
          onBlur={saveNotes}
          placeholder="Add notes about this device..."
          style={{
            width: '100%', background: '#111', border: '1px solid #333', borderRadius: 3,
            padding: 6, color: '#ccc', fontSize: 10, minHeight: 52, resize: 'vertical', boxSizing: 'border-box',
          }}
        />
        <div style={{ color: '#333', fontSize: 9, marginTop: 4 }}>Autosaves on blur · keyed to MAC address · persists across locations</div>
      </div>

      <div style={{ background: '#1a1a1a', borderRadius: 4, padding: 8 }}>
        <div style={{ color: '#555', fontSize: 9, letterSpacing: 1, marginBottom: 4 }}>SEEN AT LOCATIONS</div>
        {appearances.length === 0 && (
          <div style={{ color: '#333', fontSize: 10 }}>Not seen at any saved location yet</div>
        )}
        {appearances.map(loc => {
          const ld = (loc.devices || []).find(d => d.macAddress === device.macAddress);
          return (
            <div key={loc.id} style={{ fontSize: 10, color: '#aaa', padding: '2px 0' }}>
              📍 {loc.name} · {formatDate(loc.createdAt)} · IP was {ld?.ipAtTime || '?'}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Save location modal ───────────────────────────────────────────────────────

function SaveLocationModal({ onSave, onCancel }) {
  const [name, setName] = useState('');
  const inputRef = useRef(null);
  useEffect(() => inputRef.current?.focus(), []);

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50 }}>
      <div style={{ background: '#1a1a1a', border: '1px solid #333', borderRadius: 8, padding: 24, width: 320 }}>
        <div style={{ color: '#fff', fontSize: 14, fontWeight: 'bold', marginBottom: 12 }}>Save Location Snapshot</div>
        <input
          ref={inputRef}
          value={name}
          onChange={e => setName(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && name.trim()) onSave(name.trim()); if (e.key === 'Escape') onCancel(); }}
          placeholder="e.g. Warner Bros Lot 3 - Stage A"
          style={{ width: '100%', background: '#111', border: '1px solid #444', borderRadius: 4, padding: '8px 10px', color: '#fff', fontSize: 12, boxSizing: 'border-box', marginBottom: 12 }}
        />
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button onClick={onCancel} style={{ padding: '6px 14px', background: '#333', border: 'none', borderRadius: 4, color: '#aaa', fontSize: 12, cursor: 'pointer' }}>Cancel</button>
          <button
            onClick={() => name.trim() && onSave(name.trim())}
            disabled={!name.trim()}
            style={{ padding: '6px 14px', background: '#22c55e', border: 'none', borderRadius: 4, color: '#000', fontSize: 12, fontWeight: 'bold', cursor: 'pointer', opacity: name.trim() ? 1 : 0.4 }}
          >Save</button>
        </div>
      </div>
    </div>
  );
}

// ── Subnet settings ───────────────────────────────────────────────────────────

function SubnetSettings({ subnets, onAdd, onDelete, onClose }) {
  const [label, setLabel] = useState('');
  const [cidr, setCidr] = useState('');
  const [color, setColor] = useState('#7dd3fc');

  const add = () => {
    if (!label.trim() || !cidr.trim()) return;
    onAdd({ label: label.trim(), cidr: cidr.trim(), color });
    setLabel(''); setCidr('');
  };

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50 }}>
      <div style={{ background: '#1a1a1a', border: '1px solid #333', borderRadius: 8, padding: 24, width: 380 }}>
        <div style={{ color: '#fff', fontSize: 14, fontWeight: 'bold', marginBottom: 12 }}>Subnet Settings</div>
        {subnets.map(s => (
          <div key={s.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '5px 0', borderBottom: '1px solid #222' }}>
            <span style={{ color: s.color, fontSize: 11 }}>● {s.label}</span>
            <span style={{ color: '#555', fontSize: 10 }}>{s.cidr}</span>
            <button onClick={() => onDelete(s.id)} style={{ background: 'none', border: 'none', color: '#f87171', cursor: 'pointer', fontSize: 11 }}>✕</button>
          </div>
        ))}
        <div style={{ marginTop: 12, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <input value={label} onChange={e => setLabel(e.target.value)} placeholder="Label" style={{ flex: 1, minWidth: 80, background: '#111', border: '1px solid #444', borderRadius: 4, padding: '5px 8px', color: '#fff', fontSize: 11 }} />
          <input value={cidr} onChange={e => setCidr(e.target.value)} placeholder="192.168.10.0/24" style={{ flex: 2, minWidth: 130, background: '#111', border: '1px solid #444', borderRadius: 4, padding: '5px 8px', color: '#fff', fontSize: 11 }} />
          <input type="color" value={color} onChange={e => setColor(e.target.value)} style={{ width: 32, height: 30, background: 'none', border: '1px solid #444', borderRadius: 4, cursor: 'pointer', padding: 2 }} />
          <button onClick={add} style={{ background: '#2563eb', border: 'none', borderRadius: 4, color: '#fff', fontSize: 11, padding: '5px 10px', cursor: 'pointer' }}>Add</button>
        </div>
        <div style={{ textAlign: 'right', marginTop: 14 }}>
          <button onClick={onClose} style={{ background: '#333', border: 'none', borderRadius: 4, color: '#aaa', fontSize: 12, padding: '6px 14px', cursor: 'pointer' }}>Done</button>
        </div>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function NetworkMonitor() {
  const [subnets, setSubnets] = useState([]);
  const [devices, setDevices] = useState([]);
  const [locations, setLocations] = useState([]);
  const [locationDetail, setLocationDetail] = useState({});

  const [selectedSubnet, setSelectedSubnet] = useState(null);
  const [selectedLocation, setSelectedLocation] = useState(null);
  const [selectedDevice, setSelectedDevice] = useState(null);

  const [scanning, setScanning] = useState(false);
  const [lastScan, setLastScan] = useState(null);
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [showSubnetSettings, setShowSubnetSettings] = useState(false);

  const fetchDevices = useCallback(async () => {
    try {
      const res = await axios.get('/api/network/devices');
      setDevices(res.data);
      setLastScan(new Date());
      setSelectedDevice(prev => prev ? res.data.find(d => d.macAddress === prev.macAddress) || prev : null);
    } catch (e) {
      console.error('fetch devices', e);
    }
  }, []);

  const fetchAll = useCallback(async () => {
    try {
      const [subRes, devRes, locRes] = await Promise.all([
        axios.get('/api/network/subnets'),
        axios.get('/api/network/devices'),
        axios.get('/api/network/locations'),
      ]);
      setSubnets(subRes.data);
      setDevices(devRes.data);
      setLocations(locRes.data);
      setLastScan(new Date());
    } catch (e) {
      console.error('fetchAll', e);
    }
  }, []);

  useEffect(() => {
    fetchAll();
    const timer = setInterval(fetchDevices, 15_000);
    return () => clearInterval(timer);
  }, [fetchAll, fetchDevices]);

  const triggerScan = async () => {
    setScanning(true);
    try {
      await axios.post('/api/network/scan/trigger');
      setTimeout(() => { fetchDevices(); setScanning(false); }, 5000);
    } catch (e) {
      setScanning(false);
    }
  };

  const handleSelectLocation = async (locId) => {
    setSelectedLocation(locId);
    setSelectedSubnet(null);
    if (!locationDetail[locId]) {
      try {
        const res = await axios.get(`/api/network/locations/${locId}`);
        setLocationDetail(prev => ({ ...prev, [locId]: res.data }));
      } catch (e) {
        console.error('fetch location detail', e);
      }
    }
  };

  const handleSelectSubnet = (subnetId) => {
    setSelectedSubnet(subnetId);
    setSelectedLocation(null);
  };

  const saveLocation = async (name) => {
    setShowSaveModal(false);
    try {
      await axios.post('/api/network/locations', { name });
      const res = await axios.get('/api/network/locations');
      setLocations(res.data);
    } catch (e) {
      console.error('save location', e);
    }
  };

  const updateDevice = async (mac, patch) => {
    try {
      const res = await axios.patch(`/api/network/devices/${mac}`, patch);
      setDevices(prev => prev.map(d => d.macAddress === mac ? res.data : d));
      setSelectedDevice(prev => prev?.macAddress === mac ? res.data : prev);
    } catch (e) {
      console.error('update device', e);
    }
  };

  const addSubnet = async (data) => {
    try {
      const res = await axios.post('/api/network/subnets', data);
      setSubnets(prev => [...prev, res.data]);
    } catch (e) {
      console.error('add subnet', e);
    }
  };

  const deleteSubnet = async (id) => {
    try {
      await axios.delete(`/api/network/subnets/${id}`);
      setSubnets(prev => prev.filter(s => s.id !== id));
      if (selectedSubnet === id) setSelectedSubnet(null);
    } catch (e) {
      console.error('delete subnet', e);
    }
  };

  const locDevices = selectedLocation && locationDetail[selectedLocation]
    ? (locationDetail[selectedLocation].devices || []).map(ld => ({
        macAddress: ld.macAddress,
        lastIp: ld.ipAtTime,
        lastSeen: ld.onlineAtTime ? new Date().toISOString() : null,
        label: devices.find(d => d.macAddress === ld.macAddress)?.label || null,
        notes: devices.find(d => d.macAddress === ld.macAddress)?.notes || null,
        deviceType: 'unknown',
        vendorData: ld.vendorDataAtTime,
        subnetId: null,
      }))
    : [];

  const locationsWithDevices = locations.map(loc => ({
    ...loc,
    devices: locationDetail[loc.id]?.devices || [],
  }));

  const secondsAgo = lastScan ? Math.floor((Date.now() - lastScan) / 1000) : null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 48px)', background: '#0a0a0a', color: '#fff', fontFamily: 'monospace' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 14px', borderBottom: '1px solid #1a1a1a', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 13, fontWeight: 'bold' }}>Network Monitor</span>
          {scanning && <span style={{ color: '#7dd3fc', fontSize: 10 }}>● scanning...</span>}
          {!scanning && secondsAgo !== null && (
            <span style={{ color: '#444', fontSize: 10 }}>Last scan: {secondsAgo}s ago</span>
          )}
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <button
            onClick={() => setShowSubnetSettings(true)}
            style={{ padding: '4px 10px', background: '#1a1a1a', border: '1px solid #333', borderRadius: 4, color: '#888', fontSize: 11, cursor: 'pointer' }}
          >
            ⚙ Subnets
          </button>
          <button
            onClick={triggerScan}
            disabled={scanning}
            style={{ padding: '4px 10px', background: '#1e3a5f', border: '1px solid #2a4a7f', borderRadius: 4, color: '#7dd3fc', fontSize: 11, cursor: scanning ? 'default' : 'pointer', opacity: scanning ? 0.5 : 1 }}
          >
            Scan Now
          </button>
          <button
            onClick={() => setShowSaveModal(true)}
            style={{ padding: '4px 10px', background: '#1a2a1a', border: '1px solid #2a4a2a', borderRadius: 4, color: '#86efac', fontSize: 11, cursor: 'pointer' }}
          >
            ⊞ Save Location
          </button>
        </div>
      </div>

      {/* Body */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <Sidebar
          subnets={subnets}
          locations={locations}
          devices={devices}
          selectedSubnet={selectedSubnet}
          selectedLocation={selectedLocation}
          onSelectSubnet={handleSelectSubnet}
          onSelectLocation={handleSelectLocation}
          onSaveLocation={() => setShowSaveModal(true)}
        />
        <DeviceList
          devices={devices}
          subnets={subnets}
          selectedSubnet={selectedSubnet}
          selectedLocation={selectedLocation}
          locationDevices={locDevices}
          selectedDevice={selectedDevice}
          onSelectDevice={setSelectedDevice}
        />
        <div style={{ flex: 1, overflow: 'auto' }}>
          {selectedDevice
            ? <DeviceDetail device={selectedDevice} locations={locationsWithDevices} onUpdate={updateDevice} />
            : (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#333', fontSize: 12 }}>
                Select a device to view details
              </div>
            )
          }
        </div>
      </div>

      {showSaveModal && <SaveLocationModal onSave={saveLocation} onCancel={() => setShowSaveModal(false)} />}
      {showSubnetSettings && (
        <SubnetSettings
          subnets={subnets}
          onAdd={addSubnet}
          onDelete={deleteSubnet}
          onClose={() => setShowSubnetSettings(false)}
        />
      )}
    </div>
  );
}
