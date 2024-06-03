import React from 'react';
import { createRoot } from 'react-dom/client';
import { DocsGPTWidget } from './components/DocsGPTWidget';

const renderWidget = (elementId: string, props = {}) => {
  const root = createRoot(document.getElementById(elementId) as HTMLElement);
  root.render(<DocsGPTWidget {...props} />);
};

(window as any).renderDocsGPTWidget = renderWidget;
export { DocsGPTWidget };