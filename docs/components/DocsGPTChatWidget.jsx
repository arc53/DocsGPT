'use client';

import dynamic from 'next/dynamic';
import { useTheme } from 'next-themes';
import { useEffect, useState } from 'react';

// The widget reads window/navigator on mount and ships its own styled-components
// trees, so it must never be prerendered.
const DocsGPTWidget = dynamic(
  () => import('docsgpt-react').then((mod) => mod.DocsGPTWidget),
  { ssr: false },
);

const apiHost =
  process.env.NEXT_PUBLIC_DOCSGPT_API_HOST || 'https://gptcloud.arc53.com';
const apiKey = process.env.NEXT_PUBLIC_DOCSGPT_API_KEY;

export function DocsGPTChatWidget() {
  const { resolvedTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  // No key means no widget. Falling through would silently use the demo key
  // baked into the package default.
  if (!apiKey || !mounted) return null;

  return (
    <DocsGPTWidget
      apiHost={apiHost}
      apiKey={apiKey}
      theme={resolvedTheme === 'light' ? 'light' : 'dark'}
      buttonText="Ask the docs"
      title="Ask DocsGPT"
      description="Answers drawn from these docs"
      heroTitle="Ask anything about DocsGPT"
      heroDescription="Answers are generated from this documentation. Check the sources for anything you plan to rely on."
    />
  );
}
