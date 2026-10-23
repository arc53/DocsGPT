import { useCallback, useEffect, useRef } from 'react';
import { useStore } from 'react-redux';

import type { SSEEvent } from '../../notifications/notificationsSlice';
import type { RootState } from '../../store';

const MAX_WAIT_MS = 5 * 60_000;
/**
 * How far behind this browser the server's clock may run. An event's own
 * `ts` older than the operation by more than this is a replayed old one.
 */
const CLOCK_SKEW_MS = 5 * 60_000;

export type ReingestTerminal = 'completed' | 'failed' | 'timeout' | 'unmounted';

/**
 * How a wait ended, with the terminal event's `reason` when it gave one: a
 * queued change that didn't run fails with `busy` (another change held the
 * source too long), `wiki` (the source became a wiki) or `gone` (deleted).
 * A finished Website page add lists the pages it couldn't fetch in
 * `failedPages` (their addresses; empty when every page came in).
 */
export interface ReingestOutcome {
  terminal: ReingestTerminal;
  reason: string | null;
  failedPages: string[];
}

/** An outcome that carries no event: an unmount or a timeout. */
const bare = (terminal: ReingestTerminal): ReingestOutcome => ({
  terminal,
  reason: null,
  failedPages: [],
});

/** The addresses in an event's `failed_pages`, when it lists any. */
function failedPagesOf(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((url): url is string => typeof url === 'string' && !!url)
    : [];
}

export interface WaitForTerminalOptions {
  /** The task the mutation queued; matched when the event carries one. */
  taskId?: string | null;
}

/** When this tab first held each event in the ring, by its own clock. */
type SeenEvents = {
  ring: SSEEvent[] | null;
  byId: Map<string, number>;
  byObject: WeakMap<SSEEvent, number>;
};

/**
 * Waits for a terminal source.ingest.{completed,failed} event tagged with
 * sourceId in the bounded notifications.recentEvents ring.
 *
 * An event counts when this tab received it at or after `opStartedAt`, both
 * read from this browser's clock, so a server clock that runs behind or
 * ahead doesn't matter, and a terminal from an earlier operation on the same
 * source (already in the ring) can't finish the current wait. When the event
 * carries a `task_id` and the caller passes the task it queued, the ids
 * decide instead.
 *
 * Each wait keeps its own timer; waits that overlap settle independently.
 * Unmounting settles every pending wait with 'unmounted'.
 *
 * @returns `waitForTerminal(sourceId, opStartedAt, options?)`, called after
 *   kicking off the backend mutation; `waitForChange`, the same wait
 *   resolving to a {@link ReingestOutcome}; and `mountedRef`.
 */
export function useReingestSseWaiter() {
  const store = useStore<RootState>();
  const mountedRef = useRef(true);
  const pendingRef = useRef(new Set<() => void>());
  const settleAllRef = useRef(new Set<(value: ReingestOutcome) => void>());
  const seenRef = useRef<SeenEvents | null>(null);

  const ringOf = useCallback(
    (): SSEEvent[] => store.getState().notifications?.recentEvents ?? [],
    [store],
  );

  // Events the ring already holds when the view mounts predate any
  // operation it starts.
  if (!seenRef.current) {
    const byId = new Map<string, number>();
    const byObject = new WeakMap<SSEEvent, number>();
    const ring = ringOf();
    for (const event of ring) {
      if (event.id) byId.set(event.id, -Infinity);
      else byObject.set(event, -Infinity);
    }
    seenRef.current = { ring, byId, byObject };
  }

  /** Stamps the events new to the ring with now. */
  const recordSeen = useCallback(() => {
    const seen = seenRef.current!;
    const ring = ringOf();
    if (seen.ring === ring) return;
    seen.ring = ring;
    const now = Date.now();
    const byId = new Map<string, number>();
    for (const event of ring) {
      if (event.id) byId.set(event.id, seen.byId.get(event.id) ?? now);
      else if (!seen.byObject.has(event)) seen.byObject.set(event, now);
    }
    seen.byId = byId;
  }, [ringOf]);

  useEffect(() => {
    recordSeen();
    return store.subscribe(() => {
      recordSeen();
      for (const check of Array.from(pendingRef.current)) check();
    });
  }, [store, recordSeen]);

  // Set on every mount: StrictMode unmounts and mounts again, and a flag
  // that only ever turned false answered every later wait with 'unmounted'.
  useEffect(() => {
    mountedRef.current = true;
    const settleAll = settleAllRef.current;
    return () => {
      mountedRef.current = false;
      for (const settle of Array.from(settleAll)) settle(bare('unmounted'));
    };
  }, []);

  const waitForChange = useCallback(
    (
      sourceId: string | undefined,
      opStartedAt: number,
      options: WaitForTerminalOptions = {},
    ) =>
      new Promise<ReingestOutcome>((resolve) => {
        if (!mountedRef.current) {
          resolve(bare('unmounted'));
          return;
        }
        const taskId = options.taskId || null;

        const matches = (event: SSEEvent): boolean => {
          if (event.scope?.id !== sourceId) return false;
          const eventTask = event.payload?.task_id;
          if (taskId && typeof eventTask === 'string')
            return eventTask === taskId;
          const ts = event.ts ? Date.parse(event.ts) : NaN;
          if (Number.isFinite(ts) && ts < opStartedAt - CLOCK_SKEW_MS)
            return false;
          const seen = seenRef.current!;
          const seenAt = event.id
            ? seen.byId.get(event.id)
            : seen.byObject.get(event);
          if (seenAt !== undefined) return seenAt >= opStartedAt;
          return Number.isFinite(ts) && ts >= opStartedAt;
        };

        const terminalFromSse = (): ReingestOutcome | null => {
          if (!sourceId) return null;
          for (const event of ringOf()) {
            if (
              event.type !== 'source.ingest.completed' &&
              event.type !== 'source.ingest.failed'
            )
              continue;
            if (!matches(event)) continue;
            const reason = event.payload?.reason;
            return {
              terminal:
                event.type === 'source.ingest.completed'
                  ? 'completed'
                  : 'failed',
              reason: typeof reason === 'string' ? reason : null,
              failedPages: failedPagesOf(event.payload?.failed_pages),
            };
          }
          return null;
        };

        // Cover the race where the event landed between the POST
        // returning and this call.
        recordSeen();
        const initial = terminalFromSse();
        if (initial) {
          resolve(initial);
          return;
        }

        let timer: number | null = null;
        const check = () => {
          const next = terminalFromSse();
          if (next) finish(next);
        };
        const finish = (value: ReingestOutcome) => {
          if (timer !== null) window.clearTimeout(timer);
          timer = null;
          pendingRef.current.delete(check);
          settleAllRef.current.delete(finish);
          resolve(value);
        };
        timer = window.setTimeout(() => finish(bare('timeout')), MAX_WAIT_MS);
        pendingRef.current.add(check);
        settleAllRef.current.add(finish);
      }),
    [ringOf, recordSeen],
  );

  const waitForTerminal = useCallback(
    (
      sourceId: string | undefined,
      opStartedAt: number,
      options: WaitForTerminalOptions = {},
    ): Promise<ReingestTerminal> =>
      waitForChange(sourceId, opStartedAt, options).then(
        (outcome) => outcome.terminal,
      ),
    [waitForChange],
  );

  return { waitForTerminal, waitForChange, mountedRef };
}
