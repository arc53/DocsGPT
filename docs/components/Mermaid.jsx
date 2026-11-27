'use client';

import { use, useId, useSyncExternalStore } from 'react';

// Renders a ```mermaid code block (remarkMdxMermaid turns each one into
// <Mermaid chart="..." />) in the browser, in the current colour theme.
export function Mermaid({ chart }) {
  // false on the server and during hydration
  const isClient = useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  );
  if (!isClient) return null;
  return <MermaidContent chart={chart} />;
}

const cache = new Map();

function cachePromise(key, create) {
  if (!cache.has(key)) cache.set(key, create());
  return cache.get(key);
}

function subscribeTheme(onChange) {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributeFilter: ['class'] });
  return () => observer.disconnect();
}

function MermaidContent({ chart }) {
  const id = useId();
  const theme = useSyncExternalStore(
    subscribeTheme,
    () => (document.documentElement.classList.contains('dark') ? 'dark' : 'default'),
    () => 'default',
  );
  const { default: mermaid } = use(cachePromise('mermaid', () => import('mermaid')));
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: 'strict',
    fontFamily: 'inherit',
    themeCSS: 'margin: 1.5rem auto 0;',
    theme,
  });
  const { svg, bindFunctions } = use(
    cachePromise(`${chart}-${theme}`, () => mermaid.render(id.replace(/:/g, ''), chart.replaceAll('\\n', '\n'))),
  );
  return (
    <div
      ref={(container) => {
        if (container) bindFunctions?.(container);
      }}
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
