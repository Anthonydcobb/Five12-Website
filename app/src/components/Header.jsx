// File: src/components/Header.jsx
import React from 'react';
import { Link } from 'react-router-dom';
import logo from '../assets/logo.svg';

export default function Header() {
  return (
    <header className="bg-gray-800 text-white p-4">
      <div className="max-w-screen-xl mx-auto flex items-center justify-between">
        <Link to="/">
          <img src={logo} alt="Five12 Logo" className="h-12" />
        </Link>
        <nav>
          <ul className="flex space-x-6">
            <li>
              <Link to="/" className="hover:underline">
                Home
              </Link>
            </li>
            <li>
              <Link to="/patch" className="hover:underline">
                Patch
              </Link>
            </li>
            <li>
              <Link to="/labels" className="hover:underline">
                Labels
              </Link>
            </li>
            <li>
              <Link to="/effects-playground" className="hover:underline">
                Effects Playground
              </Link>
            </li>
            <li>
              <Link to="/network" className="hover:underline">
                Network
              </Link>
            </li>
            <li>
              <Link to="/ip-config" className="hover:underline">
                IP Config
              </Link>
            </li>
            <li>
              <Link to="/nodes" className="hover:underline">
                Nodes
              </Link>
            </li>
          </ul>
        </nav>
      </div>
    </header>
  );
}
