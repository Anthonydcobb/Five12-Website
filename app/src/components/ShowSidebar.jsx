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
        className="bg-gray-800 p-6 flex-shrink-0 relative"
      >
        <h2 className="text-2xl font-bold mb-4">My Shows</h2>
        <button
          onClick={() => setShowModal(true)}
          className="w-full mb-6 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 rounded text-lg font-medium"
        >
          + Create New Show
        </button>
        <ul className="space-y-2">
          {shows.length > 0 ? (
            shows.map(show => (
              <li key={show.id}>
                <Link
                  to={`/patch/${show.id}`}
                  className="block px-3 py-2 bg-gray-700 hover:bg-gray-600 rounded"
                >
                  {show.name}
                </Link>
              </li>
            ))
          ) : (
            <li className="text-gray-500">No shows created yet.</li>
          )}
        </ul>
        <div
          onMouseDown={handleMouseDown}
          className="absolute top-0 right-0 h-full w-1 cursor-ew-resize"
        />
      </aside>

      {showModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center">
          <div className="bg-gray-800 p-6 rounded-lg w-1/3">
            <h3 className="text-xl font-semibold mb-4 text-white">New Show Name</h3>
            <input
              type="text"
              value={newShowName}
              onChange={e => setNewShowName(e.target.value)}
              className="w-full mb-4 px-3 py-2 bg-gray-700 text-white rounded"
              placeholder="Enter show name"
            />
            <div className="flex justify-end space-x-3">
              <button
                onClick={() => setShowModal(false)}
                className="px-4 py-2 bg-gray-600 hover:bg-gray-500 rounded"
              >
                Cancel
              </button>
              <button
                onClick={handleSubmit}
                className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 rounded text-white font-medium"
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