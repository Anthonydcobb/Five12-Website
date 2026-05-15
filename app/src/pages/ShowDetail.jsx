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
    <div className="flex h-screen bg-gray-900 text-white">
      <ShowSidebar shows={shows} onCreate={handleCreateShow} />
      <main className="flex-1 p-6 flex flex-col">
        <div className="flex items-center mb-6">
          <h1 className="text-2xl font-bold flex-1">
            Show: {shows.find(s => s.id === parseInt(showId))?.name || showId}
          </h1>
          <button
            onClick={() => setShowPatchModal(true)}
            className="px-4 py-2 bg-green-600 hover:bg-green-700 rounded mr-4"
          >
            + Create Patch Sheet
          </button>
          <button
            onClick={() => navigate('/database')}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded mr-4"
          >
            Edit Database
          </button>
          <button
            onClick={handleDeleteShow}
            className="px-4 py-2 bg-red-700 hover:bg-red-600 rounded text-white"
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
                  className="flex-1 text-left px-3 py-2 bg-gray-700 hover:bg-gray-600 rounded"
                >
                  {p.name}
                </button>
                <button
                  onClick={(e) => handleDeletePatch(p.id, p.name, e)}
                  className="px-2 py-2 text-gray-400 hover:text-red-400 hover:bg-gray-700 rounded text-sm"
                  title="Delete patch sheet"
                >
                  ✕
                </button>
              </li>
            ))
          ) : (
            <li className="text-gray-500">No patch sheets yet.</li>
          )}
        </ul>

        {showPatchModal && (
          <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center">
            <div className="bg-gray-800 p-6 rounded-lg w-1/3">
              <h3 className="text-xl font-semibold mb-4 text-white">New Patch Sheet Name</h3>
              <input
                type="text"
                value={newPatchName}
                onChange={e => setNewPatchName(e.target.value)}
                className="w-full mb-4 px-3 py-2 bg-gray-700 text-white rounded"
                placeholder="Enter patch sheet name"
              />
              <div className="flex justify-end space-x-3">
                <button
                  onClick={() => setShowPatchModal(false)}
                  className="px-4 py-2 bg-gray-600 hover:bg-gray-500 rounded"
                >
                  Cancel
                </button>
                <button
                  onClick={handleCreatePatch}
                  className="px-4 py-2 bg-green-600 hover:bg-green-700 rounded text-white font-medium"
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