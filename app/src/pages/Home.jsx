import React from 'react';
import logo from '../assets/logo.svg';

export default function Home() {
  return (
    <div className="flex flex-col items-center justify-center h-screen bg-gray-900 text-center px-4">
      <img src={logo} alt="Five12 Logo" className="w-48 mb-4" />
      <h1 className="text-4xl font-bold text-white">Welcome</h1>
    </div>
  );
}