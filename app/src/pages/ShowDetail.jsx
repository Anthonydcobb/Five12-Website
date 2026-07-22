// File: src/pages/ShowDetail.jsx
import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import ShowSidebar from '../components/ShowSidebar';

export default function ShowDetail() {
  const { showId } = useParams();
  const navigate = useNavigate();
  const [shows, setShows] = useState([]);
  const [patches, setPatches] = useState([]);
  const [showPatchModal, setShowPatchModal] = useState(false);
  const [newPatchName, setNewPatchName] = useState('');

  const handleDeleteShow = () => {
    const show = shows.find(s => s.id === parseInt(showId));
    if (!window.confirm(`Delete show "${show?.name}"? This will delete all its patch sheets and cannot be undone.`)) return;
    fetch(`/api/shows/${showId}`, { method: 'DELETE' })
      .then(() => navigate('/patch'))
      .catch(err => console.error('Error deleting show:', err));
  };

  const handleDeletePatch = (patchId, patchName, e) => {
    e.stopPropagation();
    if (!window.confirm(`Delete patch sheet "${patchName}"? This cannot be undone.`)) return;
    fetch(`/api/patch-sheets/${patchId}`, { method: 'DELETE' })
      .then(() => setPatches(prev => prev.filter(p => p.id !== patchId)))
      .catch(err => console.error('Error deleting patch sheet:', err));
  };

  useEffect(() => {
    fetch('/api/shows', { credentials: 'include' })
      .then(res => res.json())
      .then(data => setShows(data))
      .catch(err => console.error('Error loading shows:', err));
  }, []);

  useEffect(() => {
    fetch(`/api/shows/${showId}/patch-sheets`, { credentials: 'include' })
      .then(res => res.json())
      .then(data => setPatches(data))
      .catch(err => console.error('Error loading patches:', err));
  }, [showId]);

  const handleCreateShow = (name) => {
    fetch('/api/shows', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ name }),
    })
      .then(res => res.json())
      .then(newShow => setShows(prev => [...prev, newShow]))
      .catch(err => console.error('Error creating show:', err));
  };

  const handleCreatePatch = () => {
    const name = newPatchName.trim();
    if (!name) return;
    fetch(`/api/shows/${showId}/patch-sheets`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ name }),
    })
      .then(res => res.json())
      .then(newPatch => {
        setPatches(prev => [...prev, newPatch]);
        setNewPatchName('');
        setShowPatchModal(false);
        navigate(`/patch/${showId}/${newPatch.id}`);
      })
      .catch(err => console.error('Error creating patch:', err));
  };

  return (
    <div className="flex min-h-[calc(100vh-4rem)] text-text">
      <ShowSidebar shows={shows} onCreate={handleCreateShow} />
      <main className="flex-1 p-6 flex flex-col">
        <div className="flex items-center mb-6">
          <h1 className="text-2xl font-bold flex-1">
            Show: {shows.find(s => s.id === parseInt(showId))?.name || showId}
          </h1>
          <button
            onClick={() => setShowPatchModal(true)}
            className="px-4 py-2 bg-online hover:brightness-110 text-bg font-semibold rounded mr-4 transition"
          >
            + Create Patch Sheet
          </button>
          <button
            onClick={() => navigate('/database')}
            className="px-4 py-2 bg-surface-2 hover:bg-border border border-border rounded mr-4 transition-colors"
          >
            Edit Database
          </button>
          <button
            onClick={handleDeleteShow}
            className="px-4 py-2 bg-brand hover:bg-brand-hi rounded text-white transition-colors"
          >
            Delete Show
          </button>
        </div>
        <ul className="space-y-2 mb-6">
          {patches.length > 0 ? (
            patches.map(p => (
              <li key={p.id} className="flex items-center gap-2">
                <button
                  onClick={() => navigate(`/patch/${showId}/${p.id}`)}
                  className="flex-1 text-left px-3 py-2 bg-surface-2 hover:bg-border rounded transition-colors"
                >
                  {p.name}
                </button>
                <button
                  onClick={(e) => handleDeletePatch(p.id, p.name, e)}
                  className="px-2 py-2 text-text-muted hover:text-brand-hi hover:bg-surface-2 rounded text-sm"
                  title="Delete patch sheet"
                >
                  ✕
                </button>
              </li>
            ))
          ) : (
            <li className="text-text-muted">No patch sheets yet.</li>
          )}
        </ul>

        {showPatchModal && (
          <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50">
            <div className="bg-surface border border-border p-6 rounded-lg w-1/3 shadow-xl">
              <h3 className="text-xl font-semibold mb-4">New Patch Sheet Name</h3>
              <input
                type="text"
                value={newPatchName}
                onChange={e => setNewPatchName(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleCreatePatch()}
                className="w-full mb-4 px-3 py-2 bg-bg border border-border rounded focus:outline-none focus:border-brand"
                placeholder="Enter patch sheet name"
                autoFocus
              />
              <div className="flex justify-end space-x-3">
                <button
                  onClick={() => setShowPatchModal(false)}
                  className="px-4 py-2 bg-surface-2 hover:bg-border rounded"
                >
                  Cancel
                </button>
                <button
                  onClick={handleCreatePatch}
                  className="px-4 py-2 bg-online hover:brightness-110 text-bg rounded font-semibold"
                >
                  OK
                </button>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}