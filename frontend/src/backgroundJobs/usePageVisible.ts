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

/** {@link isPageAttended}, following visibility and window focus. */
export function usePageAttended(): boolean {
  const [attended, setAttended] = useState(isPageAttended);
  useEffect(() => {
    const onChange = () => setAttended(isPageAttended());
    document.addEventListener('visibilitychange', onChange);
    window.addEventListener('focus', onChange);
    window.addEventListener('blur', onChange);
    return () => {
      document.removeEventListener('visibilitychange', onChange);
      window.removeEventListener('focus', onChange);
      window.removeEventListener('blur', onChange);
    };
  }, []);
  return attended;
}
