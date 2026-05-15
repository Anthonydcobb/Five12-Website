// File: src/App.jsx
import React from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Header from './components/Header';
import Home from './pages/Home';
import Patch from './pages/Patch';
import ShowDetail from './pages/ShowDetail';
import PatchSheet from './pages/PatchSheet';
import Database from './pages/Database';
import EffectPlayground from './pages/EffectPlayground';
import LabelsPage from './pages/LabelsPage';
import NetworkMonitor from './pages/NetworkMonitor';
import IPConfig from './pages/IPConfig';
import NodesPage from './pages/NodesPage';


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
          <Route path="/effects-playground" element={<EffectPlayground />} />
          <Route path="/network" element={<NetworkMonitor />} />
          <Route path="/ip-config" element={<IPConfig />} />
          <Route path="/nodes" element={<NodesPage />} />
        </Routes>
      </main>
    </Router>
  );
}
