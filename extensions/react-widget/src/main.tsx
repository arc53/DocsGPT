import React from 'react';
import { createRoot } from 'react-dom/client';
import { DocsGPTWidget } from './components/DocsGPTWidget';
import { ThemeProvider } from 'styled-components';
import { THEME } from './types';

const themes = {
  dark: {
    bg: '#222327',
    text: '#fff',
    primary: {
      text: "#FAFAFA",
      bg: '#222327'
    },
    secondary: {
      text: "#A1A1AA",
      bg: "#38383b"
    }
  },

  light: {
    bg: '#fff',
    text: '#000',
    primary: {
      text: "#222327",
      bg: "#fff"
    },
    secondary: {
      text: "#A1A1AA",
      bg: "#F6F6F6"
    }
  }
}

if (typeof window !== 'undefined') {
  const renderWidget = (elementId: string, props={
    theme: "dark" as THEME
  }) => {
    const root = createRoot(document.getElementById(elementId) as HTMLElement);
    root.render(
      <ThemeProvider theme={themes[props.theme]}>
        <DocsGPTWidget {...props} />
      </ThemeProvider>
    );
  };
  (window as any).renderDocsGPTWidget = renderWidget;
}
export { DocsGPTWidget };