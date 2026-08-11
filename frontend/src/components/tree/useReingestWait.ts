import { useCallback, useEffect, useRef } from 'react';
import { useStore } from 'react-redux';
import type { RootState } from '../../store';

const MAX_WAIT_MS = 5 * 60_000;

export type ReingestTerminal = 'completed' | 'failed' | 'timeout' | 'unmounted';

/**
 * Waits for a terminal source.ingest.{completed,failed} event tagged with
 * sourceId in the bounded notifications.recentEvents ring. Resolves on
 * the first terminal whose timestamp is >= opStartedAt (so a stale
 * terminal from a prior op on the same source can't short-circuit the
 * current wait).
 *
 * Returns a function `waitForTerminal(sourceId, opStartedAt)` that callers
 * invoke after kicking off the backend mutation. Cleans up its subscribe
 * and timer on unmount.
 */
export function useReingestSseWaiter() {
  const store = useStore<RootState>();
  const mountedRef = useRef(true);
  const unsubscribeRef = useRef<(() => void) | null>(null);
  const timerRef = useRef<number | null>(null);

  useEffect(
    () => () => {
      mountedRef.current = false;
      unsubscribeRef.current?.();
      unsubscribeRef.current = null;
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    },
    [],
  );

  const waitForTerminal = useCallback(
    (sourceId: string | undefined, opStartedAt: number) =>
      new Promise<ReingestTerminal>((resolve) => {
        if (!mountedRef.current) {
          resolve('unmounted');
          return;
        }

        const terminalFromSse = (): 'completed' | 'failed' | null => {
          if (!sourceId) return null;
          const events = store.getState().notifications.recentEvents;
          for (const event of events) {
            if (event.scope?.id !== sourceId) continue;
            const ts = event.ts ? Date.parse(event.ts) : NaN;
            if (!Number.isFinite(ts) || ts < opStartedAt) continue;
            if (event.type === 'source.ingest.completed') return 'completed';
            if (event.type === 'source.ingest.failed') return 'failed';
          }
          return null;
        };

        // Cover the race where the event landed between the POST
        // returning and the subscribe call.
        const initial = terminalFromSse();
        if (initial) {
          resolve(initial);
          return;
        }

        let settled = false;
        const finish = (value: ReingestTerminal) => {
          if (settled) return;
          settled = true;
          if (timerRef.current !== null) {
            window.clearTimeout(timerRef.current);
            timerRef.current = null;
          }
          if (unsubscribeRef.current) {
            unsubscribeRef.current();
            unsubscribeRef.current = null;
          }
          resolve(value);
        };

        timerRef.current = window.setTimeout(
          () => finish('timeout'),
          MAX_WAIT_MS,
        );
        unsubscribeRef.current = store.subscribe(() => {
          if (!mountedRef.current) {
            finish('unmounted');
            return;
          }
          const next = terminalFromSse();
          if (next) finish(next);
        });
      }),
    [store],
  );

  return { waitForTerminal, mountedRef };
}
