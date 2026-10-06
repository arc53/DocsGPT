import { useEffect, useState } from 'react';

const isVisible = () =>
  typeof document === 'undefined' || document.visibilityState === 'visible';

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
