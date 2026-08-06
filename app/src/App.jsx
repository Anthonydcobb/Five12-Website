// File: src/App.jsx
import React from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { BootProvider } from './components/BootLogo';
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
import NodesPage from './pages/NodesPage';

// NOTE: Effects Playground was removed — it duplicated the Console.
// The Console (Hog-style console prototype) is PARKED as of 2026-07-22: its
// route and the Header nav link were removed because it isn't finished. The
// page and its engine are intentionally kept on disk (src/pages/Console.jsx,
// src/engine/*, src/components/LightSimulator.jsx) so it can be resumed later.
// To restore: re-add `import Console from './pages/Console'`, the
// <Route path="/console"> below, and the nav link in components/Header.jsx.

// BootProvider owns the home-screen boot clock. It sits above the Router so
// the Header can light up with the rig; it holds the settled frame until Home
// mounts and starts a boot, and costs nothing the rest of the time.
export default function App() {
  return (
    <BootProvider intensity={0.7}>
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
            {/* Restored 2026-08-06. NodesPage.jsx existed on disk but was
                never imported or routed, so its Swisson XND port-config UI
                was unreachable even though the backend behind it
                (/api/nodes/scan and /api/nodes/<ip>/config) was live and
                working. Found while removing the dead GigaCore config path
                from the same page. */}
            <Route path="/nodes" element={<NodesPage />} />
            <Route path="/ip-config" element={<IPConfig />} />
          </Routes>
        </main>
      </Router>
    </BootProvider>
  );
}
