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
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded"
          >
            Edit Database
          </button>
        </div>
        <ul className="space-y-2 mb-6">
          {patches.length > 0 ? (
            patches.map(p => (
              <li key={p.id}>
                <button
                  onClick={() => navigate(`/patch/${showId}/${p.id}`)}
                  className="block px-3 py-2 bg-gray-700 hover:bg-gray-600 rounded"
                >
                  {p.name}
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