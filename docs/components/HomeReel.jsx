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
      width={1920}
      height={1080}
      poster="/home-reel-poster.png"
      aria-label="DocsGPT feature reel: uploading docs, syncing GitHub, answers with sources, research mode, workflows, tools, the chat widget, the OpenAI-compatible API, the MCP server and self-hosting"
      style={{ width: '100%', height: 'auto', borderRadius: '0.5rem', marginTop: '1.5rem' }}
    >
      <source src="/home-reel.webm" type="video/webm" />
      <source src="/home-reel.mp4" type="video/mp4" />
    </video>
  );
}
