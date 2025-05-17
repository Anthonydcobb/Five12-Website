// File: src/main.jsx
// Entry point for the React application. Mounts the App component into the root DOM node.
import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './styles/global.css';  // Tailwind imports + any global overrides

const container = document.getElementById('root');
const root = createRoot(container);
root.render(<App />);

