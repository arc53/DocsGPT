'use client';

import { useEffect, useRef } from 'react';

/**
 * The docs home page feature reel. It starts playing only when the reader
 * hasn't asked for reduced motion; otherwise it stays on its poster frame,
 * and the controls still let them play it.
 */
export function HomeReel() {
  const video = useRef(null);

  useEffect(() => {
    const el = video.current;
    const query = window.matchMedia('(prefers-reduced-motion: reduce)');
    const apply = () => {
      if (!el) return;
      if (query.matches) {
        el.pause();
      } else {
        el.play().catch(() => {});
      }
    };
    apply();
    query.addEventListener('change', apply);
    return () => query.removeEventListener('change', apply);
  }, []);

  return (
    <video
      ref={video}
      muted
      loop
      playsInline
      controls
      preload="metadata"
      width={1440}
      height={900}
      poster="https://pub.arc53.com/hero-loop-v2/hero-loop-poster.webp"
      aria-label="DocsGPT feature reel: a question answered with numbered citations and its source open beside it, a knowledge graph, an agent asking for approval before it acts, a workflow running node by node, an HTML report with a chart, and a wall of screens: analytics, traces, guardrails, MCP tools, connectors and admin"
      style={{ width: '100%', height: 'auto', borderRadius: '0.5rem', marginTop: '1.5rem' }}
    >
      <source src="https://pub.arc53.com/hero-loop-v2/hero-loop.webm" type="video/webm" />
      <source src="https://pub.arc53.com/hero-loop-v2/hero-loop.mp4" type="video/mp4" />
    </video>
  );
}
