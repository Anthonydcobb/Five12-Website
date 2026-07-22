// File: src/components/ShowSidebar.jsx
import React, { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';

export default function ShowSidebar({ shows, onCreate }) {
  const [showModal, setShowModal] = useState(false);
  const [newShowName, setNewShowName] = useState('');
  const [width, setWidth] = useState(300);
  const sidebarRef = useRef(null);
  const isResizingRef = useRef(false);

  useEffect(() => {
    const handleMouseMove = (e) => {
      if (isResizingRef.current) {
        const rect = sidebarRef.current.getBoundingClientRect();
        const newWidth = e.clientX - rect.left;
        setWidth(Math.max(200, Math.min(newWidth, 600)));
      }
    };
    const handleMouseUp = () => { isResizingRef.current = false; };
    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, []);

  const handleMouseDown = () => { isResizingRef.current = true; };
  const handleSubmit = () => {
    const name = newShowName.trim();
    if (!name) return;
    onCreate(name);
    setNewShowName('');
    setShowModal(false);
  };

  return (
    <>
      <aside
        ref={sidebarRef}
        style={{ width }}
        className="bg-surface border-r border-border p-6 flex-shrink-0 relative"
      >
        <h2 className="text-2xl font-bold mb-4">My Shows</h2>
        <button
          onClick={() => setShowModal(true)}
          className="w-full mb-6 px-4 py-2 bg-brand hover:bg-brand-hi text-white rounded text-lg font-medium transition-colors"
        >
          + Create New Show
        </button>
        <ul className="space-y-2">
          {shows.length > 0 ? (
            shows.map(show => (
              <li key={show.id}>
                <Link
                  to={`/patch/${show.id}`}
                  className="block px-3 py-2 bg-surface-2 hover:bg-border rounded transition-colors"
                >
                  {show.name}
                </Link>
              </li>
            ))
          ) : (
            <li className="text-text-muted">No shows created yet.</li>
          )}
        </ul>
        <div
          onMouseDown={handleMouseDown}
          className="absolute top-0 right-0 h-full w-1 cursor-ew-resize hover:bg-brand/40"
        />
      </aside>

      {showModal && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50">
          <div className="bg-surface border border-border p-6 rounded-lg w-1/3 shadow-xl">
            <h3 className="text-xl font-semibold mb-4">New Show Name</h3>
            <input
              type="text"
              value={newShowName}
              onChange={e => setNewShowName(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSubmit()}
              className="w-full mb-4 px-3 py-2 bg-bg border border-border rounded focus:outline-none focus:border-brand"
              placeholder="Enter show name"
              autoFocus
            />
            <div className="flex justify-end space-x-3">
              <button
                onClick={() => setShowModal(false)}
                className="px-4 py-2 bg-surface-2 hover:bg-border rounded"
              >
                Cancel
              </button>
              <button
                onClick={handleSubmit}
                className="px-4 py-2 bg-brand hover:bg-brand-hi rounded text-white font-medium"
              >
                OK
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}