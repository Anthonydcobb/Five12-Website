// File: src/App.jsx
import React from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Header from './components/Header';
import Home from './pages/Home';
import Patch from './pages/Patch';
import ShowDetail from './pages/ShowDetail';
import PatchSheet from './pages/PatchSheet';
import Database from './pages/Database';
import LabelsPage from './pages/LabelsPage';
import NetworkMonitor from './pages/NetworkMonitor';
import IPConfig from './pages/IPConfig';
import Devices from './pages/Devices';

// NOTE: Effects Playground was removed — it duplicated the Console.
// The Console (Hog-style console prototype) is PARKED as of 2026-07-22: its
// route and the Header nav link were removed because it isn't finished. The
// page and its engine are intentionally kept on disk (src/pages/Console.jsx,
// src/engine/*, src/components/LightSimulator.jsx) so it can be resumed later.
// To restore: re-add `import Console from './pages/Console'`, the
// <Route path="/console"> below, and the nav link in components/Header.jsx.

export default function App() {
  return (
    <Router>
      <Header />
      <main>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/patch" element={<Patch />} />
          <Route path="/patch/:showId" element={<ShowDetail />} />
          <Route path="/patch/:showId/:patchId" element={<PatchSheet />} />
          <Route path="/database" element={<Database />} />
          <Route path="/labels" element={<LabelsPage />} />
          <Route path="/network" element={<NetworkMonitor />} />
          <Route path="/devices" element={<Devices />} />
          <Route path="/ip-config" element={<IPConfig />} />
        </Routes>
      </main>
    </Router>
  );
}
