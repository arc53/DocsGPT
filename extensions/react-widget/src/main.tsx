import { createRoot } from 'react-dom/client';
import App from './App.tsx';
import React from 'react';
const root = createRoot(document.getElementById('app') as HTMLElement);

root.render(<App />);
