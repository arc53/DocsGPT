import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import type { DrafterEvent, DrafterRequest } from './drafterApi';

vi.mock('react-redux', () => ({
  useSelector: () => 'token',
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

import { type PromptDrafter, usePromptDrafter } from './usePromptDrafter';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const ORIGINAL = 'Hello.\nBe brief.';
const IMPROVE = {
  mode: 'improve',
  message: 'Two changes.',
  edits: [
    { id: 'e1', find: 'Hello.', replace: 'Hi.', reason: 'Shorter.' },
    { id: 'e2', find: 'Be brief.', replace: 'Be short.', reason: 'Plain.' },
  ],
  result: 'Hi.\nBe short.',
  template_mode: { before: false, after: false },
  warnings: [],
  checks: [],
};

const current = { drafter: null as PromptDrafter | null, content: '' };

function Host() {
  const [name, setName] = useState('Support');
  const [content, setContent] = useState(ORIGINAL);
  current.content = content;
  current.drafter = usePromptDrafter({
    mode: 'improve',
    promptId: 'p1',
    name,
    content,
    setName,
    setContent,
  });
  return null;
}

describe('usePromptDrafter', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(async () => {
    stream.scripts = [];
    stream.requests = [];
    container = document.createElement('div');
    root = createRoot(container);
    await act(async () => root.render(<Host />));
  });

  afterEach(() => act(() => root.unmount()));

  it('starts over with the text as it stands and its Drafted marks kept', async () => {
    stream.scripts = [
      [{ type: 'proposal', proposal: IMPROVE }, { type: 'end' }],
    ];
    await act(async () => current.drafter!.session.send('Tighten it'));
    await act(async () => current.drafter!.decide('e1', 'accepted'));
    await act(async () => current.drafter!.startOver());
    expect(current.drafter!.session.items).toEqual([]);
    expect(current.drafter!.review).toBeNull();
    expect(current.content).toBe('Hi.\nBe brief.');
    expect(current.drafter!.drafted.isDrafted('content')).toBe(true);
    await act(async () => current.drafter!.session.send('Be formal'));
    expect(stream.requests[1].messages).toEqual([
      { role: 'user', content: 'Be formal' },
    ]);
  });

  // The drawer's ask bar stays open during a review.
  it('ends an open review with the choices so far on a new request', async () => {
    stream.scripts = [
      [{ type: 'proposal', proposal: IMPROVE }, { type: 'end' }],
    ];
    await act(async () => current.drafter!.session.send('Tighten it'));
    expect(current.drafter!.review).not.toBeNull();
    await act(async () => current.drafter!.decide('e1', 'accepted'));
    expect(current.content).toBe('Hi.\nBe brief.');

    await act(async () => current.drafter!.session.send('Now be formal'));
    expect(current.drafter!.review).toBeNull();
    // The chosen change stays, the one not chosen stays as it was, and the
    // text goes out as it now is.
    expect(current.content).toBe('Hi.\nBe brief.');
    expect(current.drafter!.drafted.isDrafted('content')).toBe(true);
    expect(stream.requests[1].context).toMatchObject({
      prompt: { content: 'Hi.\nBe brief.' },
    });
  });
});
