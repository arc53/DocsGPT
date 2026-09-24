import React from 'react';

/** Marks our own history entry, so only an entry we pushed is popped. */
const HISTORY_MARKER = 'dgptOverlay';

const layers: Array<() => void> = [];
let entryPushed = false;
let releaseTimer: ReturnType<typeof setTimeout> | 0 = 0;
let releasing = false;

const ours = () =>
  (window.history.state as Record<string, unknown> | null)?.[HISTORY_MARKER] ===
  true;

const arm = () => {
  if (entryPushed) return;
  entryPushed = true;
  if (!ours()) window.history.pushState({ [HISTORY_MARKER]: true }, '');
  window.addEventListener('popstate', handlePopState);
};

const handlePopState = () => {
  if (releasing) {
    releasing = false;
    entryPushed = ours();
    if (layers.length > 0) arm();
    else if (!entryPushed)
      window.removeEventListener('popstate', handlePopState);
    return;
  }
  // A host entry stacked above ours pops first, leaving ours in place.
  entryPushed = ours();
  const remaining = layers.length > 1;
  layers[layers.length - 1]?.();
  if (remaining) arm();
};

const register = (dismiss: () => void) => {
  layers.push(dismiss);
  if (releaseTimer) {
    clearTimeout(releaseTimer);
    releaseTimer = 0;
  }
  arm();
};

const unregister = (dismiss: () => void) => {
  const index = layers.lastIndexOf(dismiss);
  if (index !== -1) layers.splice(index, 1);
  if (layers.length > 0 || releaseTimer) return;
  // The palette hands over to the chat panel in one commit, every cleanup
  // before any setup, so release only once nothing reclaims it a task later.
  releaseTimer = setTimeout(() => {
    releaseTimer = 0;
    if (layers.length > 0) return;
    entryPushed = false;
    // Closing by button or overlay would otherwise leave the entry behind.
    if (ours()) {
      releasing = true;
      window.history.back();
      return;
    }
    window.removeEventListener('popstate', handlePopState);
  });
};

/**
 * Closes an open layer on the hardware back button instead of leaving the page.
 * All layers share one history entry, and `onDismiss` is read through a ref.
 */
export function useBackDismiss(active: boolean, onDismiss: () => void): void {
  const dismissRef = React.useRef(onDismiss);

  React.useEffect(() => {
    dismissRef.current = onDismiss;
  });

  React.useEffect(() => {
    if (!active || typeof window === 'undefined' || !window.history) return;
    const dismiss = () => dismissRef.current();
    register(dismiss);
    return () => unregister(dismiss);
  }, [active]);
}
