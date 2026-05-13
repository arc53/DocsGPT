import { baseURL } from '../api/client';
import type { SSEEvent } from '../notifications/notificationsSlice';

/**
 * Connection state surfaced to the consumer. Maps directly to the
 * ``PushHealth`` machine in ``notificationsSlice``.
 */
export type EventStreamHealth = 'connecting' | 'healthy' | 'unhealthy';

export interface EventStreamOptions {
  /** Bearer token; ``null`` short-circuits to ``unhealthy`` (auth required). */
  token: string | null;
  /**
   * Lazy getter for the current ``Last-Event-ID``. Called once at the
   * top of each connect attempt so token rotations / remounts read
   * the freshest cursor from Redux instead of a stale mount-time
   * snapshot. Return ``null`` for a fresh connect.
   */
  getLastEventId: () => string | null;
  onEvent: (event: SSEEvent) => void;
  onHealthChange: (health: EventStreamHealth) => void;
  /** Called with the most recently received id so the caller can persist it. */
  onLastEventId?: (id: string) => void;
  /**
   * Called when the server emitted an ``id:`` line with an empty value
   * (WHATWG SSE cursor reset). Distinct from ``onLastEventId('')`` so
   * callers can dispatch ``sseLastEventIdReset`` without overloading
   * the normal advance path.
   */
  onLastEventIdReset?: () => void;
  /**
   * Invoked once after ``MAX_CONSECUTIVE_401`` back-to-back 401s. The
   * reconnect loop then bails out, so the caller is responsible for
   * refreshing the token / signalling logout. Without this, an expired
   * token spins forever at the 30s backoff cap.
   */
  onAuthFailure?: () => void;
  /**
   * Invoked once when the reconnect loop bails out after
   * ``MAX_CONSECUTIVE_ERRORS`` non-401 failures. Lets the caller surface
   * a warning instead of the connection silently going dark.
   */
  onPermanentFailure?: () => void;
}

export interface EventStreamConnection {
  close(): void;
}

/**
 * Backoff schedule (ms) for reconnect attempts. Capped at 30s so a long
 * outage doesn't push retries past Cloudflare's typical 100s idle-close
 * envelope. The schedule resets to 0 after a stream stays healthy for
 * ``HEALTHY_DEBOUNCE_MS``.
 */
const BACKOFF_SCHEDULE_MS = [0, 1_000, 2_000, 4_000, 8_000, 16_000, 30_000];
const HEALTHY_DEBOUNCE_MS = 2_000;
/**
 * Reconnect ceilings. Without these, the ``while (!closed)`` loop spins
 * forever on a persistently-failing endpoint — expired token (401s) or
 * sustained server outage (5xx). Both counters reset on a successful
 * stream open. Untested (no frontend test harness); behaviour verified
 * by manual trace of the loop in ``connectEventStream``.
 */
const MAX_CONSECUTIVE_401 = 3;
const MAX_CONSECUTIVE_ERRORS = 20;

/** Up-to-±20% random jitter so N tabs reconnecting in lockstep stagger. */
function withJitter(delayMs: number): number {
  if (delayMs <= 0) return 0;
  const span = delayMs * 0.2;
  return Math.max(0, Math.round(delayMs + (Math.random() * 2 - 1) * span));
}

/**
 * Open a long-lived SSE connection to ``GET /api/events`` with
 * fetch-streaming semantics that mirror ``conversationHandlers.ts``.
 *
 * Returns immediately with an opaque handle; the connection lives in a
 * background async loop until ``close()`` is called or the underlying
 * ``AbortController`` fires.
 *
 * The ``Last-Event-ID`` cursor rides on the URL (``?last_event_id=...``)
 * rather than as a header so the request stays a CORS-simple GET — a
 * custom header would force a preflight OPTIONS that the production
 * cross-origin deployment isn't allowlisted for.
 */
export function connectEventStream(
  opts: EventStreamOptions,
): EventStreamConnection {
  const controller = new AbortController();
  let closed = false;
  let attempt = 0;
  let consecutive401 = 0;
  let consecutiveErrors = 0;
  // Closure cursor. Seeded from the store on each connect attempt so
  // mid-session reconnects use the freshest id, but kept here too so
  // an in-flight stream's reconnect doesn't lose progress between ids
  // that the store hasn't seen yet (e.g. id-only frames).
  let lastEventId: string | null = opts.getLastEventId();

  const notifyHealth = (h: EventStreamHealth) => {
    if (closed) return;
    opts.onHealthChange(h);
  };

  void (async () => {
    while (!closed) {
      const baseDelay =
        BACKOFF_SCHEDULE_MS[Math.min(attempt, BACKOFF_SCHEDULE_MS.length - 1)];
      const delay = withJitter(baseDelay);
      if (delay > 0) {
        try {
          await sleep(delay, controller.signal);
        } catch {
          return; // aborted while waiting
        }
        if (closed) return;
      }

      notifyHealth('connecting');

      // Always re-read the store cursor before reconnecting and copy
      // it verbatim — including null. A null cursor isn't "leave
      // alone": ``backlog.truncated`` events fire ``sseLastEventIdReset``
      // to clear the slice, and the client must respect that on the
      // next attempt by sending no cursor (full-backlog replay) instead
      // of resending the stale one and re-tripping the same truncation.
      lastEventId = opts.getLastEventId();

      const url = new URL(`${baseURL}/api/events`);
      if (lastEventId) url.searchParams.set('last_event_id', lastEventId);

      // Auth header is omitted when token is null. Self-hosted dev
      // installs run with ``AUTH_TYPE`` unset; the backend maps those
      // requests to ``{"sub": "local"}`` so the SSE connection works
      // tokenless. When auth IS required, a missing header surfaces
      // as a 401 and the response.ok check below flips the health
      // back to unhealthy.
      const headers: Record<string, string> = {
        Accept: 'text/event-stream',
      };
      if (opts.token) {
        headers.Authorization = `Bearer ${opts.token}`;
      }

      try {
        const response = await fetch(url.toString(), {
          method: 'GET',
          headers,
          signal: controller.signal,
          // SSE must not be cached.
          cache: 'no-store',
        });

        if (!response.ok || !response.body) {
          notifyHealth('unhealthy');
          // 401 typically means token expired. Bail out after N
          // consecutive 401s so the loop doesn't spin forever at the
          // 30s backoff cap with a stale token; the caller is
          // responsible for refreshing auth via ``onAuthFailure``.
          if (response.status === 401) {
            consecutive401 += 1;
            consecutiveErrors += 1;
            if (consecutive401 >= MAX_CONSECUTIVE_401) {
              opts.onAuthFailure?.();
              return;
            }
          } else {
            consecutive401 = 0;
            consecutiveErrors += 1;
          }
          if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
            opts.onPermanentFailure?.();
            return;
          }
          // 429: server-side per-user concurrency cap; backoff harder.
          if (response.status === 429) attempt = Math.max(attempt, 4);
          else attempt = Math.min(attempt + 1, BACKOFF_SCHEDULE_MS.length - 1);
          continue;
        }
        consecutive401 = 0;

        // Connection is open. Mark healthy after either:
        // - 2s of open response body (covers servers that go silent), or
        // - first record received past the 2s mark.
        // The setTimeout path means a backend that never emits a single
        // record after sending the 200 still flips us out of `connecting`.
        let healthyMarked = false;
        const markHealthy = () => {
          if (healthyMarked) return;
          healthyMarked = true;
          notifyHealth('healthy');
          attempt = 0;
          consecutiveErrors = 0;
        };
        const debounceTimer = setTimeout(markHealthy, HEALTHY_DEBOUNCE_MS);

        try {
          await readSSEStream(response.body, controller.signal, (record) => {
            if (record.id !== undefined) {
              lastEventId = record.id || null;
              if (record.id) opts.onLastEventId?.(record.id);
              else opts.onLastEventIdReset?.();
            }
            if (record.data === undefined) {
              // Keepalive comment, id-only frame, or comment line.
              // The cursor was already advanced via ``onLastEventId``
              // above so the slice tracks ids even on frames we don't
              // dispatch as events.
              return;
            }
            // Empty data line is technically valid SSE but useless; skip.
            if (record.data.trim().length === 0) return;
            let envelope: SSEEvent | null = null;
            try {
              envelope = JSON.parse(record.data) as SSEEvent;
            } catch {
              // Malformed payload; skip.
              return;
            }
            // Defensive shape validation — the cast above lies if the
            // server (or a man-in-the-middle) sends garbage.
            if (
              !envelope ||
              typeof envelope !== 'object' ||
              typeof envelope.type !== 'string'
            ) {
              return;
            }
            if (record.id && !envelope.id) envelope.id = record.id;
            // Receiving a real envelope post-debounce-window flips
            // healthy if the timer hasn't already.
            markHealthy();
            // Every tab dispatches every envelope it receives into its
            // own Redux store. With N tabs open this means N copies of
            // the same toast — accepted as a v1 limitation; cross-tab
            // dedup via BroadcastChannel + navigator.locks is future
            // work. Toast-level suppression can be handled per surface.
            opts.onEvent(envelope);
          });
        } finally {
          clearTimeout(debounceTimer);
        }

        // The reader returned without abort — server closed the stream.
        // Fall through to reconnect.
        notifyHealth('unhealthy');
        consecutiveErrors += 1;
        if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
          opts.onPermanentFailure?.();
          return;
        }
        attempt = Math.min(attempt + 1, BACKOFF_SCHEDULE_MS.length - 1);
      } catch (err) {
        if (
          closed ||
          (err instanceof DOMException && err.name === 'AbortError')
        ) {
          return;
        }
        notifyHealth('unhealthy');
        consecutiveErrors += 1;
        if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
          opts.onPermanentFailure?.();
          return;
        }
        attempt = Math.min(attempt + 1, BACKOFF_SCHEDULE_MS.length - 1);
      }
    }
  })();

  return {
    close() {
      if (closed) return;
      closed = true;
      controller.abort();
    },
  };
}

interface ParsedSSERecord {
  /**
   * ``undefined`` when the record had no ``id`` field at all. An empty
   * string means the server explicitly reset the cursor (an ``id:``
   * line with no value, per WHATWG SSE).
   */
  id?: string;
  /** ``undefined`` for keepalive comments / id-only frames. */
  data?: string;
}

/**
 * Drain a ``ReadableStream<Uint8Array>`` of ``\n\n``-delimited SSE records,
 * forwarding each parsed record to ``onRecord``. Honours the WHATWG SSE
 * spec's mixed line-terminator handling and SSE comment lines.
 */
async function readSSEStream(
  body: ReadableStream<Uint8Array>,
  signal: AbortSignal,
  onRecord: (record: ParsedSSERecord) => void,
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  try {
    while (true) {
      if (signal.aborted) return;
      const { done, value } = await reader.read();
      if (done) return;
      buffer += decoder.decode(value, { stream: true });

      // SSE records are separated by a blank line. WHATWG spec accepts
      // CRLF, CR, or LF — normalise so a stray CR can't smuggle a
      // boundary mid-record.
      buffer = buffer.replace(/\r\n/g, '\n').replace(/\r/g, '\n');

      let boundary = buffer.indexOf('\n\n');
      while (boundary !== -1) {
        const raw = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const record = parseSSERecord(raw);
        if (record) onRecord(record);
        boundary = buffer.indexOf('\n\n');
      }
    }
  } finally {
    try {
      reader.releaseLock();
    } catch {
      // Already released.
    }
  }
}

function parseSSERecord(raw: string): ParsedSSERecord | null {
  if (raw.length === 0) return null;
  const lines = raw.split('\n');
  let id: string | undefined;
  const dataParts: string[] = [];
  let sawDataField = false;

  for (const line of lines) {
    if (line.length === 0) continue;
    if (line.startsWith(':')) continue; // SSE comment / keepalive
    const colonIdx = line.indexOf(':');
    const field = colonIdx === -1 ? line : line.slice(0, colonIdx);
    let value = colonIdx === -1 ? '' : line.slice(colonIdx + 1);
    // SSE: value may be prefixed by exactly one optional space.
    if (value.startsWith(' ')) value = value.slice(1);

    if (field === 'id') {
      id = value;
    } else if (field === 'data') {
      sawDataField = true;
      dataParts.push(value);
    }
    // Other field names ('event', 'retry') are ignored for now.
  }

  if (!sawDataField && id === undefined) return null;
  return {
    id,
    data: sawDataField ? dataParts.join('\n') : undefined,
  };
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException('Aborted', 'AbortError'));
      return;
    }
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      signal.removeEventListener('abort', onAbort);
      reject(new DOMException('Aborted', 'AbortError'));
    };
    signal.addEventListener('abort', onAbort, { once: true });
  });
}
