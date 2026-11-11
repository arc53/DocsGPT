import type { DrafterEvent, DrafterRequest } from '../drafterApi';

/**
 * One scripted turn: its events, sent at once; a promise of them, sent once
 * it settles; or `'hold'`, a turn that stays open until a test emits on it
 * and calls `done` (or the turn is aborted).
 */
export type FakeDrafterTurn = DrafterEvent[] | Promise<DrafterEvent[]> | 'hold';

export type FakeDrafterStream = {
  /** The turns to come, in order; a turn with none left just ends. */
  scripts: FakeDrafterTurn[];
  /** Each request sent, as JSON would carry it. */
  requests: DrafterRequest[];
  signals: AbortSignal[];
  turnIds: (string | undefined)[];
  /** The `'hold'` turns still open: emit on one, then `done` ends it. */
  held: { emit: (event: DrafterEvent) => void; done: () => void }[];
  /** `[turnId, token]` for each cancelled turn. */
  cancelled: [string, string | null][];
  /** Every turn sends nothing and never ends. */
  hold: boolean;
  /** Every turn stays open after its events, as while the model works. */
  hang: boolean;
  /** Back to no scripts, no records and neither `hold` nor `hang`. */
  reset: () => void;
  /** Stands in for drafterApi's `streamDrafter`. */
  streamDrafter: (
    request: DrafterRequest,
    token: string | null,
    onEvent: (event: DrafterEvent) => void,
    signal?: AbortSignal,
    turnId?: string,
  ) => Promise<void>;
  /** Stands in for drafterApi's `cancelDrafterTurn`. */
  cancelDrafterTurn: (turnId: string, token: string | null) => Promise<void>;
};

const never = () => new Promise<void>(() => undefined);

/**
 * A scripted stand-in for the drafter's stream, for a test's
 * `vi.mock` of drafterApi:
 *
 *   const stream = await vi.hoisted(async () =>
 *     (await import('./testing/fakeDrafterStream')).fakeDrafterStream(),
 *   );
 *   vi.mock('./drafterApi', async (importOriginal) => ({
 *     ...(await importOriginal<typeof import('./drafterApi')>()),
 *     streamDrafter: stream.streamDrafter,
 *   }));
 *
 * Returns:
 *   The fake, whose fields a test sets and reads.
 */
export function fakeDrafterStream(): FakeDrafterStream {
  const fake: FakeDrafterStream = {
    scripts: [],
    requests: [],
    signals: [],
    turnIds: [],
    held: [],
    cancelled: [],
    hold: false,
    hang: false,
    reset() {
      fake.scripts = [];
      fake.requests = [];
      fake.signals = [];
      fake.turnIds = [];
      fake.held = [];
      fake.cancelled = [];
      fake.hold = false;
      fake.hang = false;
    },
    async streamDrafter(request, _token, onEvent, signal, turnId) {
      fake.requests.push(JSON.parse(JSON.stringify(request)));
      if (signal) fake.signals.push(signal);
      fake.turnIds.push(turnId);
      if (fake.hold) return never();
      const next = fake.scripts.shift() ?? [{ type: 'end' }];
      if (next === 'hold') {
        await new Promise<void>((done) => {
          fake.held.push({ emit: onEvent, done });
          signal?.addEventListener('abort', () => done());
        });
        return;
      }
      // A plain script goes out at once, as a stream's first read would.
      (next instanceof Promise ? await next : next).forEach(onEvent);
      if (fake.hang) await never();
    },
    async cancelDrafterTurn(turnId, token) {
      fake.cancelled.push([turnId, token]);
    },
  };
  return fake;
}
