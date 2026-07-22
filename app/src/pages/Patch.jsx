// File: src/pages/Patch.jsx
import React, { useState, useEffect } from 'react';
import ShowSidebar from '../components/ShowSidebar';

export default function Patch() {
  const [shows, setShows] = useState([]);

  useEffect(() => {
    fetch('/api/shows', { credentials: 'include' })
      .then(res => res.json())
      .then(data => setShows(data))
      .catch(err => console.error('Error loading shows:', err));
  }, []);

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

  return (
    <div className="flex min-h-[calc(100vh-4rem)] text-text">
      <ShowSidebar shows={shows} onCreate={handleCreateShow} />
      <main className="flex-1 p-10">
        <p className="text-text-muted">Select or create a show to get started.</p>
      </main>
    </div>
  );
}
