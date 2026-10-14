import { useEffect, useState } from 'react';

/**
 * The current time in ms, ticking once a second so stopwatches move.
 *
 * Args:
 *   active: Tick only while something shows a stopwatch.
 */
export function useClock(active = true): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [active]);
  return now;
}
