import { createRoot } from 'react-dom/client';
import React from 'react';
import { DocsGPTWidget } from './components/DocsGPTWidget.tsx';

const root = createRoot(document.getElementById('app') as HTMLElement);

root.render(<DocsGPTWidget/>);
