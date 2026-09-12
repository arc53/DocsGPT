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

// Public embed token for the docs agent, the same way every documented
// DocsGPT embed carries one. It reaches the browser either way, since
// NEXT_PUBLIC_* is inlined at build time. Abuse is capped by the agent's
// daily request and token limits, so rotate the agent key if it needs
// revoking. NEXT_PUBLIC_DOCSGPT_API_KEY overrides it for staging.
const apiKey =
  process.env.NEXT_PUBLIC_DOCSGPT_API_KEY ||
  '0e714713-1bc6-4aae-a595-aa0b3bf317b3';

export function DocsGPTChatWidget() {
  const { resolvedTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  // Hold off until next-themes has resolved, so the widget does not flash
  // the wrong theme on first paint.
  if (!mounted) return null;

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
