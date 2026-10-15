import { useEffect, useState } from 'react';

/**
 * The current time in ms, ticking so stopwatches move.
 *
 * Args:
 *   active: Tick only while something shows a stopwatch.
 *   every: How often it ticks, in ms (default once a second).
 */
export function useClock(active = true, every = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), every);
    return () => window.clearInterval(timer);
  }, [active, every]);
  return now;
}
