import { useEffect, useState } from 'react';

const isVisible = () =>
  typeof document === 'undefined' || document.visibilityState === 'visible';

/**
 * Whether the user can be looking at the page: it is visible and its window
 * has focus. A window behind another app, or on a second screen while the
 * user types elsewhere, stays `visible`; only focus tells it apart.
 */
export const isPageAttended = () =>
  typeof document === 'undefined' || (isVisible() && document.hasFocus());

/** Whether the page is visible, following `visibilitychange`. */
export function usePageVisible(): boolean {
  const [visible, setVisible] = useState(isVisible);
  useEffect(() => {
    const onChange = () => setVisible(isVisible());
    document.addEventListener('visibilitychange', onChange);
    return () => document.removeEventListener('visibilitychange', onChange);
  }, []);
  return visible;
}

/**
 * Call `onChange` when {@link isPageAttended} may have changed: on a
 * visibility change, and when the window gains or loses focus. A blur is
 * read once focus has settled: focus moving into a frame on the page (an
 * artifact preview) blurs the window before the frame holds it, and no
 * event follows once the page has focus again.
 *
 * @returns A function that stops listening.
 */
export function subscribeAttention(onChange: () => void): () => void {
  let settling: number | undefined;
  const onBlur = () => {
    window.clearTimeout(settling);
    settling = window.setTimeout(onChange, 0);
  };
  document.addEventListener('visibilitychange', onChange);
  window.addEventListener('focus', onChange);
  window.addEventListener('blur', onBlur);
  return () => {
    window.clearTimeout(settling);
    document.removeEventListener('visibilitychange', onChange);
    window.removeEventListener('focus', onChange);
    window.removeEventListener('blur', onBlur);
  };
}

/** {@link isPageAttended}, following visibility and window focus. */
export function usePageAttended(): boolean {
  const [attended, setAttended] = useState(isPageAttended);
  useEffect(() => subscribeAttention(() => setAttended(isPageAttended())), []);
  return attended;
}
