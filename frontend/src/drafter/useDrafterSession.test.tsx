import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import type { DrafterEvent, DrafterRequest } from './drafterApi';

vi.mock('react-redux', () => ({
  useSelector: (selector: (state: unknown) => unknown) =>
    selector({ preference: { token: 'tok' } }),
}));

// A script is the turn's events, or 'hold': the turn stays open and the
// test sends its events through `held` (an abort ends it, as a Stop does).
const stream = vi.hoisted(() => ({
  scripts: [] as (DrafterEvent[] | 'hold')[],
  requests: [] as DrafterRequest[],
  turnIds: [] as (string | undefined)[],
  held: [] as { emit: (event: DrafterEvent) => void; done: () => void }[],
  cancelled: [] as [string, string | null][],
}));
vi.mock('./drafterApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./drafterApi')>()),
  cancelDrafterTurn: async (turnId: string, token: string | null) => {
    stream.cancelled.push([turnId, token]);
  },
  streamDrafter: async (
    request: DrafterRequest,
    _token: string | null,
    onEvent: (event: DrafterEvent) => void,
    signal: AbortSignal,
    turnId?: string,
  ) => {
    stream.requests.push(JSON.parse(JSON.stringify(request)));
    stream.turnIds.push(turnId);
    const script = stream.scripts.shift() ?? [{ type: 'end' }];
    if (script !== 'hold') {
      script.forEach(onEvent);
      return;
    }
    await new Promise<void>((done) => {
      stream.held.push({ emit: onEvent, done });
      signal.addEventListener('abort', () => done());
    });
  },
}));

import {
  type DrafterSession,
  useDrafterSession,
  WAIT_FOR_MODEL_MS,
} from './useDrafterSession';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('useDrafterSession', () => {
  let container: HTMLDivElement;
  let root: Root;
  let session: DrafterSession;

  let onProposal: (proposal: unknown) => void = () => undefined;

  function Host() {
    session = useDrafterSession({
      recipe: 'agent',
      getContext: () => ({}),
      onProposal: (proposal) => onProposal(proposal),
    });
    return null;
  }

  beforeEach(async () => {
    onProposal = () => undefined;
    container = document.createElement('div');
    root = createRoot(container);
    await act(async () => root.render(<Host />));
  });
  afterEach(async () => {
    await act(async () => root.unmount());
    stream.scripts = [];
    stream.requests = [];
    stream.turnIds = [];
    stream.held = [];
    stream.cancelled = [];
  });

  const QUESTIONS: DrafterEvent = {
    type: 'questions',
    questions: [
      { id: 'q1', text: 'Who uses it?', note: null, multi: false, options: [] },
    ],
  };
  const sent = (index: number) => stream.requests[index].messages;

  it('keeps a plain reply in the history the next turn sends', async () => {
    stream.scripts = [
      [{ type: 'message', text: "I can't write that." }, { type: 'end' }],
    ];
    await act(async () => session.send('Write malware'));
    await act(async () => session.send('Then a support prompt'));
    expect(sent(1)).toEqual([
      { role: 'user', content: 'Write malware' },
      { role: 'assistant', content: "I can't write that." },
      { role: 'user', content: 'Then a support prompt' },
    ]);
  });

  it('keeps the line before questions with them, as one turn', async () => {
    stream.scripts = [
      [
        { type: 'message', text: 'A couple of things first.' },
        QUESTIONS,
        { type: 'end' },
      ],
    ];
    await act(async () => session.send('Draft it'));
    await act(async () => session.send('Who uses it? → Support'));
    expect(sent(1)).toHaveLength(3);
    expect(JSON.parse(sent(1)[1].content)).toEqual({
      ...QUESTIONS,
      message: 'A couple of things first.',
    });
  });

  it("keeps a refusal's limit on its error", async () => {
    stream.scripts = [
      [
        { type: 'error', code: 'prompt_too_long', limit: 12000 },
        { type: 'end' },
      ],
    ];
    await act(async () => session.send('Draft it'));
    expect(session.items.at(-1)).toMatchObject({
      kind: 'error',
      code: 'prompt_too_long',
      limit: 12000,
    });
  });

  it('runs a failed turn again on Retry, and sends no unanswered message after it', async () => {
    stream.scripts = [
      [{ type: 'error', code: 'model_error' }, { type: 'end' }],
      [{ type: 'error', code: 'model_error' }, { type: 'end' }],
      [{ type: 'proposal', proposal: {} }, { type: 'end' }],
    ];
    await act(async () => session.send('First'));
    expect(session.items.at(-1)).toMatchObject({ kind: 'error' });
    await act(async () => session.retry());
    expect(sent(1)).toEqual([{ role: 'user', content: 'First' }]);
    // Retry takes the error away; the second failure shows its own.
    expect(session.items.filter((item) => item.kind === 'error')).toHaveLength(
      1,
    );
    // A new message instead: the failed one stays on screen, not in the
    // history, so the server never gets two user messages in a row.
    await act(async () => session.send('Second'));
    expect(sent(2)).toEqual([{ role: 'user', content: 'Second' }]);
    expect(
      session.items.filter((item) => item.kind === 'user').map((i) => i.id),
    ).toHaveLength(2);
  });

  it('runs a turn again on Retry after its stream broke off past a message', async () => {
    stream.scripts = [
      [
        { type: 'message', text: 'Working on it.' },
        { type: 'error', code: 'model_error' },
        { type: 'end' },
      ],
      [{ type: 'proposal', proposal: { n: 1 } }, { type: 'end' }],
    ];
    await act(async () => session.send('First'));
    expect(session.items.at(-1)).toMatchObject({ kind: 'error' });
    await act(async () => session.retry());
    // The failed attempt's words are not an answer: the turn is sent again.
    expect(sent(1)).toEqual([{ role: 'user', content: 'First' }]);
    expect(session.items.some((item) => item.kind === 'error')).toBe(false);
    await act(async () => session.send('Shorter'));
    expect(sent(2)).toEqual([
      { role: 'user', content: 'First' },
      { role: 'assistant', content: '{"type":"proposal","proposal":{"n":1}}' },
      { role: 'user', content: 'Shorter' },
    ]);
  });

  it('cancels the server turn it gives up on, and none that ended', async () => {
    stream.scripts = ['hold', 'hold', 'hold', 'hold'];
    // Stop.
    await act(async () => session.send('One'));
    await act(async () => stream.held[0].emit({ type: 'turn', id: 't1' }));
    await act(async () => session.stop());
    expect(stream.cancelled).toEqual([['t1', 'tok']]);
    // A new message replacing a running turn.
    await act(async () => session.send('Two'));
    await act(async () => stream.held[1].emit({ type: 'turn', id: 't2' }));
    await act(async () => session.send('Three'));
    expect(stream.cancelled.at(-1)).toEqual(['t2', 'tok']);
    // A turn that ended has nothing to cancel.
    await act(async () => {
      stream.held[2].emit({ type: 'turn', id: 't3' });
      stream.held[2].emit({ type: 'proposal', proposal: {} });
      stream.held[2].emit({ type: 'end' });
      stream.held[2].done();
    });
    await act(async () => session.reset());
    expect(stream.cancelled).toHaveLength(2);
    // Start over, and leaving the page.
    await act(async () => session.send('Four'));
    await act(async () => stream.held[3].emit({ type: 'turn', id: 't4' }));
    await act(async () => root.unmount());
    expect(stream.cancelled.at(-1)).toEqual(['t4', 'tok']);
    root = createRoot(container);
  });

  it('names each turn, so a Stop before its first event still cancels it', async () => {
    stream.scripts = ['hold', 'hold'];
    await act(async () => session.send('One'));
    const first = stream.turnIds[0];
    expect(first).toMatch(/^[0-9a-f]{32}$/);
    // Stopped before the server's `turn` event arrived.
    await act(async () => session.stop());
    expect(stream.cancelled).toEqual([[first, 'tok']]);
    // Each attempt gets its own id; a server that picked another one is followed.
    await act(async () => session.send('Two'));
    expect(stream.turnIds[1]).not.toBe(first);
    await act(async () => stream.held[1].emit({ type: 'turn', id: 'srv' }));
    await act(async () => session.stop());
    expect(stream.cancelled.at(-1)).toEqual(['srv', 'tok']);
  });

  it('cancels a turn whose stream broke off, as it may still be running', async () => {
    stream.scripts = [
      [
        { type: 'turn', id: 't1' },
        { type: 'message', text: 'Working on it.' },
        { type: 'error', code: 'model_error' },
        { type: 'end' },
      ],
    ];
    await act(async () => session.send('First'));
    expect(stream.cancelled).toEqual([['t1', 'tok']]);
  });

  it('shows reading while the workspace is read, and its line once counted', async () => {
    stream.scripts = ['hold'];
    await act(async () => session.send('Draft it'));
    await act(async () =>
      stream.held[0].emit({ type: 'status', step: 'reading' }),
    );
    expect(session.step).toBe('reading');
    expect(session.items.map((item) => item.kind)).toEqual(['user']);
    await act(async () =>
      stream.held[0].emit({
        type: 'status',
        step: 'reading',
        counts: { sources: 2 },
      }),
    );
    expect(session.items.map((item) => item.kind)).toEqual(['user', 'status']);
  });

  it('stops a turn, keeping what arrived, and leaves it out of the history', async () => {
    stream.scripts = ['hold'];
    await act(async () => session.send('Draft it'));
    expect(session.streaming).toBe(true);
    await act(async () =>
      stream.held[0].emit({ type: 'status', step: 'reading', counts: {} }),
    );
    await act(async () => session.stop());
    expect(session.streaming).toBe(false);
    // The Stop is part of the record (decision 97).
    const kinds = ['user', 'status', 'stopped'];
    expect(session.items.map((item) => item.kind)).toEqual(kinds);
    // Events after the Stop are dropped.
    await act(async () =>
      stream.held[0].emit({ type: 'proposal', proposal: {} }),
    );
    expect(session.items.map((item) => item.kind)).toEqual(kinds);
    // A Stop with no turn running leaves nothing.
    await act(async () => session.stop());
    expect(session.items.map((item) => item.kind)).toEqual(kinds);
    await act(async () => session.send('Try again, shorter'));
    expect(sent(1)).toEqual([{ role: 'user', content: 'Try again, shorter' }]);
  });

  // Decision 97: a turn that goes quiet says it is still waiting.
  it('is waiting once a running turn has had no event for 30 s', async () => {
    vi.useFakeTimers();
    try {
      stream.scripts = ['hold'];
      await act(async () => session.send('Draft it'));
      await act(async () => vi.advanceTimersByTime(WAIT_FOR_MODEL_MS - 1));
      expect(session.waiting).toBe(false);
      // Any event starts the wait over.
      await act(async () =>
        stream.held[0].emit({ type: 'status', step: 'drafting' }),
      );
      await act(async () => vi.advanceTimersByTime(WAIT_FOR_MODEL_MS - 1));
      expect(session.waiting).toBe(false);
      await act(async () => vi.advanceTimersByTime(1));
      expect(session.waiting).toBe(true);
      await act(async () =>
        stream.held[0].emit({ type: 'message', text: 'Almost.' }),
      );
      expect(session.waiting).toBe(false);
      await act(async () => vi.advanceTimersByTime(WAIT_FOR_MODEL_MS));
      expect(session.waiting).toBe(true);
      await act(async () => session.stop());
      expect(session.waiting).toBe(false);
      await act(async () => vi.advanceTimersByTime(WAIT_FOR_MODEL_MS));
      expect(session.waiting).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });

  it('replaces a running turn with a new one, dropping the first one’s events', async () => {
    const proposals: unknown[] = [];
    onProposal = (proposal) => proposals.push(proposal);
    stream.scripts = ['hold', 'hold'];
    await act(async () => session.send('One'));
    await act(async () => session.send('Two'));
    expect(sent(1)).toEqual([{ role: 'user', content: 'Two' }]);
    await act(async () =>
      stream.held[0].emit({ type: 'proposal', proposal: { n: 1 } }),
    );
    expect(proposals).toEqual([]);
    expect(session.streaming).toBe(true);
    await act(async () => {
      stream.held[1].emit({ type: 'proposal', proposal: { n: 2 } });
      stream.held[1].emit({ type: 'end' });
      stream.held[1].done();
    });
    expect(proposals).toEqual([{ n: 2 }]);
    expect(session.streaming).toBe(false);
  });

  it('offers to start over before the history outgrows what the server takes', async () => {
    for (let turn = 0; turn < 12; turn += 1) {
      expect(session.full).toBe(false);
      stream.scripts = [[{ type: 'proposal', proposal: {} }, { type: 'end' }]];
      await act(async () => session.send(`Change ${turn}`));
    }
    expect(sent(11)).toHaveLength(23);
    expect(session.full).toBe(true);
    // Full: a send goes nowhere until a fresh start.
    await act(async () => session.send('One more'));
    expect(stream.requests).toHaveLength(12);
    await act(async () => session.reset());
    expect(session.full).toBe(false);
    await act(async () => session.send('One more'));
    expect(sent(12)).toEqual([{ role: 'user', content: 'One more' }]);
  });

  it('adds a local message that the server never sees', async () => {
    await act(async () => session.addMessage('Prompt saved and set.'));
    expect(session.items).toEqual([
      { id: 1, kind: 'message', text: 'Prompt saved and set.' },
    ]);
    await act(async () => session.send('Next'));
    expect(stream.requests[0].messages).toEqual([
      { role: 'user', content: 'Next' },
    ]);
  });

  it("lists the user's own messages, not a hidden one, until reset", async () => {
    await act(async () =>
      session.send('Continue with Knowledge and tools.', { hidden: true }),
    );
    // A hidden message runs the turn but draws no bubble.
    expect(stream.requests[0].messages).toEqual([
      { role: 'user', content: 'Continue with Knowledge and tools.' },
    ]);
    expect(session.items.some((item) => item.kind === 'user')).toBe(false);

    await act(async () => session.send('  Only the help center  '));
    await act(async () => session.send('Which? → Help Center'));
    expect(session.userTexts()).toEqual([
      'Only the help center',
      'Which? → Help Center',
    ]);

    await act(async () => session.reset());
    expect(session.userTexts()).toEqual([]);
    expect(session.items).toEqual([]);
  });

  // Decision 92: the answered cards are the record, so answers draw no bubble.
  it('sends answers without a bubble, keeps them on the questions, and closes the rest', async () => {
    stream.scripts = [
      [QUESTIONS, { type: 'end' }],
      [QUESTIONS, { type: 'end' }],
    ];
    await act(async () => session.send('Draft it'));
    await act(async () =>
      session.send('Who uses it? → Staff', { answers: { q1: 'Staff' } }),
    );
    expect(sent(1).at(-1)).toEqual({
      role: 'user',
      content: 'Who uses it? → Staff',
    });
    expect(session.items.filter((item) => item.kind === 'user')).toHaveLength(
      1,
    );
    // The user's words all the same, for a build's later steps.
    expect(session.userTexts()).toEqual(['Draft it', 'Who uses it? → Staff']);
    const questions = () =>
      session.items.filter((item) => item.kind === 'questions');
    expect(questions()[0]).toMatchObject({
      state: 'answered',
      answers: { q1: 'Staff' },
    });
    // The second round is open until a message passes it, or a skip.
    expect(questions()[1]).not.toHaveProperty('state');
    await act(async () => session.closeQuestions('skipped'));
    expect(questions()[1]).toMatchObject({ state: 'skipped' });

    stream.scripts = [[QUESTIONS, { type: 'end' }]];
    await act(async () => session.send('Something else'));
    await act(async () => session.send('Never mind'));
    expect(questions()[2]).toMatchObject({ state: 'passed' });
  });

  it('gathers a turn’s reads into one item, and gives the next turn its own', async () => {
    stream.scripts = [
      [
        { type: 'status', step: 'reading', counts: {} },
        { type: 'read', kind: 'questions', items: ['A?', 'B?'] },
        { type: 'read', kind: 'questions', items: ['B?', 'C?'] },
        { type: 'end' },
      ],
      [{ type: 'read', kind: 'questions', items: ['D?'] }, { type: 'end' }],
    ];
    await act(async () => session.send('Fix the docs gap'));
    const reads = () => session.items.filter((item) => item.kind === 'read');
    expect(reads()).toEqual([
      expect.objectContaining({ kind: 'read', items: ['A?', 'B?', 'C?'] }),
    ]);
    await act(async () => session.send('And the rest'));
    expect(reads().map((item) => item.kind === 'read' && item.items)).toEqual([
      ['A?', 'B?', 'C?'],
      ['D?'],
    ]);
    // A read is no answer: a turn that only read sends nothing back.
    expect(sent(1)).toEqual([{ role: 'user', content: 'And the rest' }]);
  });
});
