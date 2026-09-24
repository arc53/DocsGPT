import React from 'react';

/** Below this the gap is the browser's own chrome, not a keyboard. */
const KEYBOARD_MIN_INSET_PX = 120;

/**
 * Publishes the visual viewport as `--dgpt-vv-top`, `--dgpt-vv-bottom` and
 * `--dgpt-vv-height` on the node while a keyboard covers it. Neither
 * `position: fixed` nor `100dvh` notices one, so a full-screen panel keeps its
 * height and slides its header off the display, close button and all. Written
 * straight to the node, since these events fire every frame while the keyboard
 * animates.
 */
export function useVisualViewportBounds(
  active: boolean,
  ref: React.RefObject<HTMLElement | null>,
): void {
  React.useEffect(() => {
    const viewport =
      typeof window === 'undefined' ? null : window.visualViewport;
    const node = ref.current;
    if (!active || !viewport || !node) return;

    let frame = 0;
    let written = '';

    const clear = () => {
      if (!written) return;
      written = '';
      node.style.removeProperty('--dgpt-vv-top');
      node.style.removeProperty('--dgpt-vv-height');
      node.style.removeProperty('--dgpt-vv-bottom');
    };

    const apply = () => {
      frame = 0;
      // Pinch-zoom shrinks the viewport the same way but covers nothing.
      if (viewport.scale > 1.01) {
        clear();
        return;
      }
      // A quirks-mode host reports its content height from `clientHeight`.
      const layoutHeight = Math.min(
        document.documentElement.clientHeight,
        window.innerHeight,
      );
      const top = viewport.offsetTop;
      const bottom = Math.max(0, layoutHeight - top - viewport.height);
      if (top + bottom < KEYBOARD_MIN_INSET_PX) {
        clear();
        return;
      }
      const next = `${top}|${viewport.height}|${bottom}`;
      if (next === written) return;
      written = next;
      node.style.setProperty('--dgpt-vv-top', `${top}px`);
      node.style.setProperty('--dgpt-vv-height', `${viewport.height}px`);
      node.style.setProperty('--dgpt-vv-bottom', `${bottom}px`);
    };

    const schedule = () => {
      if (!frame) frame = window.requestAnimationFrame(apply);
    };

    apply();
    viewport.addEventListener('resize', schedule);
    viewport.addEventListener('scroll', schedule);

    return () => {
      if (frame) window.cancelAnimationFrame(frame);
      viewport.removeEventListener('resize', schedule);
      viewport.removeEventListener('scroll', schedule);
      clear();
    };
  }, [active, ref]);
}
