import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import type { DrafterEvent, DrafterRequest } from './drafterApi';

vi.mock('react-redux', () => ({
  useSelector: (selector: (state: unknown) => unknown) =>
    selector({ preference: { token: 'tok' } }),
}));

const stream = vi.hoisted(() => ({
  scripts: [] as DrafterEvent[][],
  requests: [] as DrafterRequest[],
}));
vi.mock('./drafterApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./drafterApi')>()),
  streamDrafter: async (
    request: DrafterRequest,
    _token: string | null,
    onEvent: (event: DrafterEvent) => void,
  ) => {
    stream.requests.push(JSON.parse(JSON.stringify(request)));
    (stream.scripts.shift() ?? [{ type: 'end' }]).forEach(onEvent);
  },
}));

import { type DrafterSession, useDrafterSession } from './useDrafterSession';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('useDrafterSession', () => {
  let container: HTMLDivElement;
  let root: Root;
  let session: DrafterSession;

  function Host() {
    session = useDrafterSession({
      recipe: 'agent',
      getContext: () => ({}),
      onProposal: () => undefined,
    });
    return null;
  }

  beforeEach(async () => {
    container = document.createElement('div');
    root = createRoot(container);
    await act(async () => root.render(<Host />));
  });
  afterEach(async () => {
    await act(async () => root.unmount());
    stream.scripts = [];
    stream.requests = [];
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
