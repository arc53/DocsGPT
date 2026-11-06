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
  held: [] as { emit: (event: DrafterEvent) => void; done: () => void }[],
}));
vi.mock('./drafterApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./drafterApi')>()),
  streamDrafter: async (
    request: DrafterRequest,
    _token: string | null,
    onEvent: (event: DrafterEvent) => void,
    signal: AbortSignal,
  ) => {
    stream.requests.push(JSON.parse(JSON.stringify(request)));
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

import { type DrafterSession, useDrafterSession } from './useDrafterSession';

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
    stream.held = [];
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

  it('stops a turn, keeping what arrived, and leaves it out of the history', async () => {
    stream.scripts = ['hold'];
    await act(async () => session.send('Draft it'));
    expect(session.streaming).toBe(true);
    await act(async () =>
      stream.held[0].emit({ type: 'status', step: 'reading', counts: {} }),
    );
    await act(async () => session.stop());
    expect(session.streaming).toBe(false);
    expect(session.items.map((item) => item.kind)).toEqual(['user', 'status']);
    // Events after the Stop are dropped.
    await act(async () =>
      stream.held[0].emit({ type: 'proposal', proposal: {} }),
    );
    expect(session.items.map((item) => item.kind)).toEqual(['user', 'status']);
    await act(async () => session.send('Try again, shorter'));
    expect(sent(1)).toEqual([{ role: 'user', content: 'Try again, shorter' }]);
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
});
