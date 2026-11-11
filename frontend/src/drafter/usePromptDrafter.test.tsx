import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-redux', () => ({
  useSelector: () => 'token',
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const stream = await vi.hoisted(async () =>
  (await import('./testing/fakeDrafterStream')).fakeDrafterStream(),
);
vi.mock('./drafterApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./drafterApi')>()),
  cancelDrafterTurn: stream.cancelDrafterTurn,
  streamDrafter: stream.streamDrafter,
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
  warnings: [],
  checks: [],
};

const current = {
  drafter: null as PromptDrafter | null,
  name: '',
  content: '',
  setName: (() => undefined) as (name: string) => void,
  setContent: (() => undefined) as (content: string) => void,
};

function Host() {
  const [name, setName] = useState('Support');
  const [content, setContent] = useState(ORIGINAL);
  current.name = name;
  current.content = content;
  current.setName = setName;
  current.setContent = setContent;
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
    stream.reset();
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

  const improve = (edits: { id: string; find: string; replace: string }[]) => [
    {
      type: 'proposal' as const,
      proposal: {
        ...IMPROVE,
        edits: edits.map((edit) => ({ ...edit, reason: 'x' })),
      },
    },
    { type: 'end' as const },
  ];

  // The server reads the text with its line ends as \n; its edits do too.
  it('reviews a text with Windows line ends as the server read it', async () => {
    await act(async () => current.setContent('Hello.\r\nBe brief.'));
    stream.scripts = [
      improve([{ id: 'e1', find: 'Hello.\nBe', replace: 'Hi.\nBe' }]),
    ];
    await act(async () => current.drafter!.session.send('Tighten it'));
    expect(current.drafter!.review!.proposal.edits).toHaveLength(1);
    await act(async () => current.drafter!.acceptAll());
    expect(current.drafter!.review).toBeNull();
    expect(current.content).toBe('Hi.\nBe brief.');
  });

  // The server reads it without invisible characters; those outside a
  // change stay.
  it('reviews a text with a zero-width space as the server read it', async () => {
    await act(async () => current.setContent('Hel\u200blo.\nBe brief.\u200b'));
    stream.scripts = [improve([{ id: 'e1', find: 'Hello.', replace: 'Hi.' }])];
    await act(async () => current.drafter!.session.send('Tighten it'));
    expect(current.drafter!.review!.proposal.edits).toHaveLength(1);
    await act(async () => current.drafter!.acceptAll());
    expect(current.content).toBe('Hi.\nBe brief.\u200b');
  });

  it('leaves a text with Windows line ends as it was when nothing is accepted', async () => {
    await act(async () => current.setContent('Hello.\r\nBe brief.'));
    stream.scripts = [
      improve([{ id: 'e1', find: 'Be brief.', replace: 'Be short.' }]),
    ];
    await act(async () => current.drafter!.session.send('Tighten it'));
    await act(async () => current.drafter!.decide('e1', 'rejected'));
    expect(current.content).toBe('Hello.\r\nBe brief.');
    stream.scripts = [
      improve([{ id: 'e2', find: 'Be brief.', replace: 'Be short.' }]),
    ];
    await act(async () => current.drafter!.session.send('Again'));
    await act(async () => current.drafter!.discard());
    expect(current.content).toBe('Hello.\r\nBe brief.');
  });

  // A long prompt is read cut short: a change past the cut can't be shown.
  it('reviews only the changes that fit the text, and says so when none do', async () => {
    stream.scripts = [
      improve([
        { id: 'e1', find: 'Hello.', replace: 'Hi.' },
        { id: 'e2', find: 'Be brief…', replace: 'Be short.' },
      ]),
      improve([{ id: 'e3', find: 'Gone…', replace: 'Here.' }]),
    ];
    await act(async () => current.drafter!.session.send('Tighten it'));
    expect(
      current.drafter!.review!.proposal.edits.map((edit) => edit.id),
    ).toEqual(['e1']);
    await act(async () => current.drafter!.decide('e1', 'accepted'));
    // Every change shown is decided: the review is done.
    expect(current.drafter!.review).toBeNull();
    expect(current.content).toBe('Hi.\nBe brief.');

    await act(async () => current.drafter!.session.send('More'));
    expect(current.drafter!.review).toBeNull();
    expect(current.drafter!.session.items.at(-1)).toMatchObject({
      kind: 'message',
      text: 'drafter.agent.prompt.editsStale',
    });
  });

  it('sends a review in review mode, a Retry too, and the next message in improve', async () => {
    stream.scripts = [
      [{ type: 'error', code: 'model_error' }, { type: 'end' }],
      [
        {
          type: 'proposal',
          proposal: {
            ...IMPROVE,
            mode: 'review',
            findings: [],
            passed: ['tone'],
          },
        },
        { type: 'end' },
      ],
      [{ type: 'end' }],
    ];
    await act(async () => current.drafter!.startReview('Review it'));
    expect(stream.requests[0].context).toMatchObject({
      mode: 'review',
      prompt: { id: 'p1', content: ORIGINAL },
    });
    await act(async () => current.drafter!.session.retry());
    expect(stream.requests[1].context).toMatchObject({ mode: 'review' });
    // A review's edits are reviewed in the editor like an improvement's.
    expect(
      current.drafter!.review!.proposal.edits.map((edit) => edit.id),
    ).toEqual(['e1', 'e2']);
    await act(async () => current.drafter!.goTo('e2'));
    expect(current.drafter!.review!.current).toBe('e2');
    // A change not under review moves nothing.
    await act(async () => current.drafter!.goTo('e9'));
    expect(current.drafter!.review!.current).toBe('e2');
    await act(async () => current.drafter!.session.send('Now be formal'));
    expect(stream.requests[2].context).toMatchObject({ mode: 'improve' });
  });

  it('skips questions for the Skip turn only, a Retry of it too', async () => {
    stream.scripts = [
      [{ type: 'error', code: 'model_error' }, { type: 'end' }],
      [{ type: 'end' }],
      [{ type: 'end' }],
    ];
    await act(async () => current.drafter!.skipQuestions('Just draft it'));
    expect(stream.requests[0].context).toMatchObject({
      mode: 'improve',
      skip_questions: true,
    });
    // The skipped cards are the record: the skip's own text draws no bubble.
    expect(
      current.drafter!.session.items.some((item) => item.kind === 'user'),
    ).toBe(false);
    await act(async () => current.drafter!.session.retry());
    expect(stream.requests[1].context).toMatchObject({ skip_questions: true });
    // The next request may be asked about again.
    await act(async () => current.drafter!.session.send('Add the hours'));
    expect(stream.requests[2].context).not.toHaveProperty('skip_questions');
  });

  const WRITE = {
    mode: 'write',
    message: 'A first draft.',
    name: 'Website chat',
    content: 'You answer visitors.',
    reason: 'A persona.',
    warnings: [],
    checks: [],
    assumptions: [],
    suggestions: [],
  };

  it('fills a written prompt, keeping a typed name, each marked with undo', async () => {
    stream.scripts = [[{ type: 'proposal', proposal: WRITE }, { type: 'end' }]];
    await act(async () => current.drafter!.session.send('Write one'));
    expect(current.drafter!.review).toBeNull();
    expect(current.content).toBe('You answer visitors.');
    expect(current.drafter!.drafted.isDrafted('content')).toBe(true);
    // The name the user typed stays and isn't marked.
    expect(current.name).toBe('Support');
    expect(current.drafter!.drafted.isDrafted('name')).toBe(false);
    await act(async () => current.drafter!.drafted.undo('content'));
    expect(current.content).toBe(ORIGINAL);
    expect(current.drafter!.drafted.isDrafted('content')).toBe(false);
  });

  it('names an unnamed prompt it writes, and undo empties the name again', async () => {
    await act(async () => current.setName(''));
    stream.scripts = [[{ type: 'proposal', proposal: WRITE }, { type: 'end' }]];
    await act(async () => current.drafter!.session.send('Write one'));
    expect(current.name).toBe('Website chat');
    expect(current.drafter!.drafted.isDrafted('name')).toBe(true);
    await act(async () => current.drafter!.drafted.undo('name'));
    expect(current.name).toBe('');
    expect(current.drafter!.drafted.isDrafted('name')).toBe(false);
    expect(current.drafter!.drafted.isDrafted('content')).toBe(true);
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

  const reviewTwice = async () => {
    await act(async () => current.setContent('A B C'));
    stream.scripts = [improve([{ id: 'e1', find: 'A', replace: 'a' }])];
    await act(async () => current.drafter!.session.send('First'));
    await act(async () => current.drafter!.acceptAll());
    expect(current.content).toBe('a B C');
    stream.scripts = [
      improve([
        { id: 'e2', find: 'B', replace: 'b' },
        { id: 'e3', find: 'C', replace: 'c' },
      ]),
    ];
    await act(async () => current.drafter!.session.send('Second'));
    await act(async () => current.drafter!.reviewOneByOne());
    await act(async () => current.drafter!.decide('e2', 'accepted'));
    expect(current.content).toBe('a b C');
  };

  it('undoes to before the first draft after a second review decided one by one', async () => {
    await reviewTwice();
    await act(async () => current.drafter!.decide('e3', 'accepted'));
    expect(current.drafter!.review).toBeNull();
    expect(current.content).toBe('a b c');
    expect(current.drafter!.drafted.isDrafted('content')).toBe(true);
    await act(async () => current.drafter!.drafted.undo('content'));
    expect(current.content).toBe('A B C');
  });

  it('keeps the first draft marked when a partly decided second review is discarded', async () => {
    await reviewTwice();
    await act(async () => current.drafter!.discard());
    expect(current.content).toBe('a B C');
    expect(current.drafter!.drafted.isDrafted('content')).toBe(true);
    await act(async () => current.drafter!.drafted.undo('content'));
    expect(current.content).toBe('A B C');
  });

  it('keeps the first draft marked when a second review ends on a new request', async () => {
    await reviewTwice();
    await act(async () => current.drafter!.session.send('Third'));
    expect(current.content).toBe('a b C');
    await act(async () => current.drafter!.drafted.undo('content'));
    expect(current.content).toBe('A B C');
  });
});
