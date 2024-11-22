//exports browser ready methods

import { createRoot } from "react-dom/client";

import { DocsGPTWidget } from './components/DocsGPTWidget';
import { SearchBar } from './components/SearchBar';
import React from "react";
if (typeof window !== 'undefined') {
  const renderWidget = (elementId: string, props = {}) => {
    const root = createRoot(document.getElementById(elementId) as HTMLElement);
    root.render(<DocsGPTWidget {...props} />);
  };
  const renderSearchBar = (elementId: string, props = {}) => {
    const root = createRoot(document.getElementById(elementId) as HTMLElement);
    root.render(<SearchBar {...props} />);
  };
  (window as any).renderDocsGPTWidget = renderWidget;

  (window as any).renderSearchBar = renderSearchBar;
}

export { DocsGPTWidget, SearchBar };
