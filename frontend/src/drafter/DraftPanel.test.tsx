import { Headset } from 'lucide-react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';

import type { DrafterEvent, DrafterRequest } from './drafterApi';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) =>
      options && 'count' in options
        ? `${key}:${options.count}`
        : options && 'model' in options
          ? `${key}:${options.model}`
          : options && 'counts' in options
            ? `${key}:${options.counts}`
            : options && 'limit' in options
              ? `${key}:${options.limit}`
              : key,
    i18n: { language: 'en' },
  }),
}));
vi.mock('react-redux', () => ({
  useSelector: (selector: (state: unknown) => unknown) =>
    selector({ preference: { token: 'tok' } }),
}));
const media = vi.hoisted(() => ({ isMobile: false, isDesktop: true }));
vi.mock('../hooks', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../hooks')>()),
  useMediaQuery: () => ({ ...media }),
}));

// Each turn plays the next script of events; `hold` keeps a turn open.
const stream = vi.hoisted(() => ({
  scripts: [] as DrafterEvent[][],
  requests: [] as DrafterRequest[],
  hold: false,
  signals: [] as AbortSignal[],
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
    stream.signals.push(signal);
    if (stream.hold) return new Promise<void>(() => undefined);
    (stream.scripts.shift() ?? [{ type: 'end' }]).forEach(onEvent);
  },
}));

import { DraftPanel, type DraftPanelProps } from './DraftPanel';
import { ProposalSummary } from './ProposalSummary';
import { useDrafterSession } from './useDrafterSession';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const onProposal = vi.fn();
const onNext = vi.fn();

type Proposal = {
  message: string;
  notes?: string[];
  dropped?: string[];
  note?: string;
};

function Host({
  open = true,
  ...props
}: { open?: boolean } & Partial<
  Pick<
    DraftPanelProps,
    | 'announceProposal'
    | 'progress'
    | 'before'
    | 'placeholder'
    | 'suggestions'
    | 'continueAction'
    | 'after'
    | 'reads'
    | 'modelName'
    | 'onStartOver'
    | 'suggestionGroups'
    | 'notice'
    | 'insightsDays'
    | 'readsAgents'
    | 'onSkipQuestions'
    | 'statusLabel'
    | 'intro'
  >
>) {
  const session = useDrafterSession({
    recipe: 'agent',
    getContext: () => ({ form: { name: 'Now' } }),
    onProposal,
  });
  return (
    <MemoryRouter>
      <DraftPanel
        open={open}
        onOpenChange={() => undefined}
        session={session}
        modelName="Fast model"
        intro="Tell me"
        suggestions={[
          {
            key: 'support',
            icon: <Headset aria-hidden="true" />,
            text: 'Support agent',
          },
        ]}
        renderProposal={(proposal, latest) => {
          const { message, notes, dropped } = proposal as Proposal;
          return (
            <ProposalSummary
              message={message}
              rows={[{ key: 'n', label: 'Name', summary: 'Shipping help' }]}
              notes={notes}
              dropped={dropped}
              actions={
                latest ? (
                  <button type="button" onClick={onNext}>
                    Next
                  </button>
                ) : undefined
              }
            />
          );
        }}
        {...props}
      />
    </MemoryRouter>
  );
}

const setValue = (el: HTMLTextAreaElement, value: string) => {
  Object.getOwnPropertyDescriptor(
    HTMLTextAreaElement.prototype,
    'value',
  )!.set!.call(el, value);
  el.dispatchEvent(new Event('input', { bubbles: true }));
};

describe('DraftPanel', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(async () => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => root.render(<Host />));
  });
  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    stream.scripts = [];
    stream.requests = [];
    stream.signals = [];
    stream.hold = false;
    onProposal.mockReset();
    onNext.mockReset();
    media.isMobile = false;
    media.isDesktop = true;
  });

  const button = (name: string) =>
    Array.from(container.querySelectorAll('button')).find(
      (b) =>
        b.textContent?.trim() === name || b.getAttribute('aria-label') === name,
    );
  it('leaves out an empty intro instead of drawing a blank line', async () => {
    const intros = () =>
      Array.from(document.body.querySelectorAll('p.whitespace-pre-wrap')).map(
        (p) => p.textContent,
      );
    expect(intros()).toContain('Tell me');
    await act(async () => root.render(<Host intro="" />));
    expect(intros()).not.toContain('');
    expect(intros()).not.toContain('Tell me');
  });

  const askBar = () =>
    container.querySelector<HTMLTextAreaElement>(
      'textarea[aria-label="drafter.askLabel"]',
    )!;
  const ask = async (text: string) => {
    await act(async () => setValue(askBar(), text));
    await act(async () => button('drafter.send')!.click());
  };
  const proposalTurn = (proposal: Proposal): DrafterEvent[] => [
    { type: 'proposal', proposal },
    { type: 'end' },
  ];

  it('greets, sends a suggestion row as the first message and names the model', async () => {
    expect(container.textContent).toContain('Tell me');
    expect(container.textContent).toContain('drafter.footer:Fast model');
    expect(
      container.querySelector('a[href="/settings/general"]')?.textContent,
    ).toBe('drafter.changeModel');
    const rows = container.querySelector('ul[aria-label]')!;
    expect(rows.getAttribute('aria-label')).toBe('drafter.suggestionsLabel');
    await act(async () =>
      container
        .querySelector<HTMLButtonElement>('[data-suggestion="support"]')!
        .click(),
    );
    expect(stream.requests[0].messages).toEqual([
      { role: 'user', content: 'Support agent' },
    ]);
    // The greeting goes once something is sent.
    expect(container.textContent).not.toContain('Tell me');
  });

  it('says what the recipe reads in the footer', async () => {
    await act(async () => root.render(<Host reads="prompt" />));
    expect(container.textContent).toContain('drafter.footerPrompt:Fast model');
    expect(container.textContent).not.toContain('drafter.footer:');
    await act(async () =>
      root.render(<Host reads="prompt" modelName={null} />),
    );
    expect(container.textContent).toContain('drafter.footerPromptNoModel');
  });

  it('names the agents a prompt drawer reads, when the prompt has any', async () => {
    await act(async () => root.render(<Host reads="prompt" readsAgents={3} />));
    // The test's t shows the count it was given.
    expect(container.textContent).toContain('drafter.footerPromptAgents:3');
    await act(async () =>
      root.render(<Host reads="prompt" readsAgents={3} modelName={null} />),
    );
    expect(container.textContent).toContain(
      'drafter.footerPromptAgentsNoModel:3',
    );
  });

  it('draws the user message as a chat bubble and the workspace as one muted line', async () => {
    stream.scripts = [
      [
        { type: 'status', step: 'reading', counts: { sources: 6, tools: 11 } },
        { type: 'message', text: 'Two questions first.' },
        { type: 'end' },
      ],
    ];
    await ask('A shipping agent');
    expect(stream.requests[0]).toEqual({
      recipe: 'agent',
      messages: [{ role: 'user', content: 'A shipping agent' }],
      context: { form: { name: 'Now' } },
    });
    const bubble = container.querySelector('[data-item="user"]')!;
    expect(bubble.textContent).toBe('A shipping agent');
    expect(bubble.className).toContain('rounded-3xl');
    expect(bubble.className).toContain('bg-secondary');
    const line = container.querySelector('[data-item="status"]')!;
    expect(line.textContent).toBe(
      'drafter.lookedAtWorkspaceCounts:drafter.counts.sources:6 · drafter.counts.tools:11',
    );
    expect(line.className).toContain('text-muted-foreground');
    expect(container.textContent).toContain('Two questions first.');
  });

  it('says when it reads the agent’s Insights too', async () => {
    await act(async () => root.render(<Host reads="insights" />));
    expect(container.textContent).toContain(
      'drafter.footerInsights:Fast model',
    );
    await act(async () =>
      root.render(<Host reads="insights" modelName={null} />),
    );
    expect(container.textContent).toContain('drafter.footerInsightsNoModel');
  });

  it('groups the first screen’s rows under their headings, with a note under them', async () => {
    const onGap = vi.fn();
    await act(async () =>
      root.render(
        <Host
          suggestionGroups={[
            {
              key: 'insights',
              title: 'From its conversations',
              count: 'last 30 days',
              rows: [
                {
                  key: 'gap-0',
                  icon: <Headset aria-hidden="true" />,
                  text: 'Returns & claims',
                  description: 'Docs gap · 23 of 160 questions',
                  onSelect: onGap,
                },
              ],
            },
            {
              key: 'setup',
              title: 'From its setup',
              rows: [
                {
                  key: 'starters',
                  icon: <Headset aria-hidden="true" />,
                  text: 'Suggest conversation starters',
                },
              ],
            },
          ]}
          notice={<p data-testid="notice">Insights is off</p>}
        />,
      ),
    );
    const headings = Array.from(container.querySelectorAll('h3')).map(
      (h) => h.textContent,
    );
    expect(headings).toEqual([
      'From its conversationslast 30 days',
      'From its setup',
    ]);
    const lists = Array.from(container.querySelectorAll('ul[aria-label]'));
    expect(lists.map((list) => list.getAttribute('aria-label'))).toEqual([
      'From its conversations',
      'From its setup',
    ]);
    // The flat list gives way to the groups.
    expect(container.querySelector('[data-suggestion="support"]')).toBeNull();
    expect(container.textContent).toContain('Docs gap · 23 of 160 questions');
    expect(container.querySelector('[data-testid="notice"]')).not.toBeNull();
    await act(async () =>
      container
        .querySelector<HTMLButtonElement>('[data-suggestion="gap-0"]')!
        .click(),
    );
    expect(onGap).toHaveBeenCalledTimes(1);
    expect(stream.requests).toHaveLength(0);
    await act(async () =>
      container
        .querySelector<HTMLButtonElement>('[data-suggestion="starters"]')!
        .click(),
    );
    expect(stream.requests[0].messages).toEqual([
      { role: 'user', content: 'Suggest conversation starters' },
    ]);
  });

  it('adds a line for the Insights it read, and folds the example questions it read', async () => {
    await act(async () => root.render(<Host insightsDays={28} />));
    stream.scripts = [
      [
        {
          type: 'status',
          step: 'reading',
          counts: { sources: 6, insights_conversations: 412 },
        },
        {
          type: 'read',
          kind: 'questions',
          items: ['How long do I have to file a damage claim?', 'Who pays?'],
        },
        { type: 'end' },
      ],
    ];
    await ask('Fix the docs gap');
    expect(container.querySelector('[data-item="status"]')!.textContent).toBe(
      'drafter.lookedAtWorkspaceCounts:drafter.counts.sources:6',
    );
    expect(container.querySelector('[data-item="insights"]')!.textContent).toBe(
      'drafter.readInsights:412',
    );
    const read = container.querySelector('[data-item="read"]')!;
    const toggle = read.querySelector<HTMLButtonElement>('button')!;
    expect(toggle.textContent).toBe('drafter.readQuestions:2');
    // Closed until opened; each question is a row of its whole text.
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    await act(async () => toggle.click());
    const rows = Array.from(
      read.querySelectorAll('[data-slot="filled-row"] p'),
    );
    expect(rows.map((row) => row.textContent)).toEqual([
      'How long do I have to file a damage claim?',
      'Who pays?',
    ]);
  });

  it('says only that it looked when the server counted nothing', async () => {
    stream.scripts = [[{ type: 'status', step: 'reading' }, { type: 'end' }]];
    await ask('Draft it');
    expect(container.querySelector('[data-item="status"]')!.textContent).toBe(
      'drafter.lookedAtWorkspace',
    );
  });

  it('asks questions, sends the answers as one message, then shows the proposal', async () => {
    const questions: DrafterEvent = {
      type: 'questions',
      questions: [
        {
          id: 'q1',
          text: 'Where should refunds go?',
          note: null,
          multi: false,
          options: [
            { id: 'a', label: 'Email support' },
            { id: 'b', label: 'Stop' },
          ],
        },
      ],
    };
    const proposal = { message: 'Draft is in the form.', fields: {} };
    stream.scripts = [
      [questions, { type: 'end' }],
      [
        { type: 'status', step: 'drafting' },
        { type: 'proposal', proposal },
        { type: 'end' },
      ],
    ];
    await ask('A shipping agent');
    // Skip is the host's to offer (decision 96): none was given here.
    expect(button('drafter.skipQuestions')).toBeUndefined();
    const radio = Array.from(
      container.querySelectorAll<HTMLButtonElement>('[role="radio"]'),
    )[1];
    await act(async () => radio.click());
    await act(async () => button('questions.sendAnswers')!.click());
    expect(stream.requests[1].messages).toEqual([
      { role: 'user', content: 'A shipping agent' },
      { role: 'assistant', content: JSON.stringify(questions) },
      { role: 'user', content: 'Where should refunds go? → Stop' },
    ]);
    expect(onProposal).toHaveBeenCalledWith(proposal);
    expect(container.textContent).toContain('Draft is in the form.');
    // Answered questions can't be sent again.
    expect(button('questions.sendAnswers')).toBeUndefined();
    // The answered card is the record: no bubble repeats the answers.
    expect(
      Array.from(container.querySelectorAll('[data-item="user"]')).map(
        (bubble) => bubble.textContent,
      ),
    ).toEqual(['A shipping agent']);
    expect(
      container.querySelector('[data-question="q1"]')?.textContent,
    ).toContain('Stop');
  });

  // Decision 92: a question left blank reads Skipped, as the chat's record.
  it('marks a question left blank as skipped, and a skipped round too', async () => {
    const twoQuestions: DrafterEvent = {
      type: 'questions',
      questions: [
        {
          id: 'q1',
          text: 'Where should refunds go?',
          note: null,
          multi: false,
          options: [
            { id: 'a', label: 'Email support' },
            { id: 'b', label: 'Stop' },
          ],
        },
        { id: 'q2', text: 'Tone?', note: null, multi: false, options: [] },
      ],
    };
    const onSkipQuestions = vi.fn();
    await act(async () =>
      root.render(<Host onSkipQuestions={onSkipQuestions} />),
    );
    stream.scripts = [
      [twoQuestions, { type: 'end' }],
      [twoQuestions, { type: 'end' }],
    ];
    await ask('A shipping agent');
    await act(async () =>
      container
        .querySelectorAll<HTMLButtonElement>('[role="radio"]')[0]
        .click(),
    );
    await act(async () => button('questions.sendAnswers')!.click());
    const cards = () =>
      Array.from(container.querySelectorAll('[data-question="q2"]'));
    expect(cards()[0].textContent).toContain('questions.skipped');

    // Skip and draft: a ghost pill beside Send answers.
    const skip = button('drafter.skipQuestions')!;
    expect(skip.dataset.variant).toBe('ghost');
    expect(skip.previousElementSibling).toBe(button('questions.sendAnswers'));
    await act(async () => skip.click());
    expect(onSkipQuestions).toHaveBeenCalledTimes(1);
    expect(button('questions.sendAnswers')).toBeUndefined();
    const second = Array.from(
      container.querySelectorAll('[data-question="q1"]'),
    )[1];
    expect(second.textContent).toContain('questions.skipped');
  });

  it('shows a proposal as its message, notes, a Filled row and the turn actions', async () => {
    stream.scripts = [
      proposalTurn({
        message: 'Here is a name.',
        notes: ['No ticketing tool is connected.'],
        dropped: ['Tools: not in your workspace'],
      }),
      proposalTurn({ message: 'Changed it.' }),
    ];
    await ask('Draft it');
    const summary = container.querySelector('[data-slot="proposal-summary"]')!;
    expect(summary.textContent).toContain('Here is a name.');
    // A note is a plain paragraph, not a callout.
    const note = Array.from(summary.querySelectorAll('p')).find(
      (p) => p.textContent === 'No ticketing tool is connected.',
    )!;
    expect(note.closest('[role="note"]')).toBeNull();
    const toggle = button('drafter.filled:1')!;
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(summary.textContent).toContain('Name · Shipping help');
    const leftOut = summary.querySelector('[data-slot="alert"]')!;
    expect(leftOut.textContent).toContain('drafter.droppedTitle');
    expect(leftOut.textContent).toContain('Tools: not in your workspace');
    expect(button('drafter.undoAll')).toBeUndefined();
    await act(async () => button('Next')!.click());
    expect(onNext).toHaveBeenCalledTimes(1);

    // Only the latest turn keeps its actions.
    await ask('Change it');
    expect(
      Array.from(container.querySelectorAll('button')).filter(
        (b) => b.textContent === 'Next',
      ),
    ).toHaveLength(1);
  });

  it('shows an error with Retry, and Retry runs the same turn again', async () => {
    stream.scripts = [
      [{ type: 'error', code: 'model_error' }, { type: 'end' }],
      [{ type: 'message', text: 'Back again' }, { type: 'end' }],
    ];
    await ask('Draft it');
    const alert = container.querySelector('[data-item="error"]')!;
    expect(alert.textContent).toContain('drafter.errors.model_error.title');
    await act(async () => button('drafter.retry')!.click());
    expect(stream.requests[1].messages).toEqual(stream.requests[0].messages);
    expect(container.querySelector('[data-item="error"]')).toBeNull();
    expect(container.textContent).toContain('Back again');
  });

  it('offers no Retry where a setting has to change first', async () => {
    stream.scripts = [[{ type: 'error', code: 'no_model' }, { type: 'end' }]];
    await ask('Draft it');
    expect(container.textContent).toContain('drafter.errors.no_model.title');
    expect(button('drafter.retry')).toBeUndefined();
  });

  // Decision 105: a refused key can't be fixed by trying again.
  it('names a task model whose key was refused and links to changing it', async () => {
    stream.scripts = [
      [
        { type: 'error', code: 'model_auth', message: 'refused' },
        { type: 'end' },
      ],
    ];
    await ask('Draft it');
    const alert = container.querySelector('[data-item="error"]')!;
    expect(alert.textContent).toContain('drafter.errors.model_auth.title');
    expect(alert.textContent).toContain(
      'drafter.errors.model_auth.description:Fast model',
    );
    expect(button('drafter.retry')).toBeUndefined();
    const fix = alert.querySelector('a[href="/settings/general"]')!;
    expect(fix.textContent).toBe('drafter.errors.model_auth.fix');
    expect(fix.getAttribute('data-variant')).toBe('link');
    expect(fix.getAttribute('data-tone')).toBe('current');
  });

  // Decision 104: "Change model" never sits alone at the end of the line.
  it('balances the footer line so its link does not wrap alone', () => {
    const link = container.querySelector('a[href="/settings/general"]')!;
    expect(link.closest('p')!.className).toContain('text-pretty');
  });

  it('says a conversation the server refused needs a fresh start, and offers one', async () => {
    stream.scripts = [
      [{ type: 'error', code: 'bad_request' }, { type: 'end' }],
    ];
    await ask('Draft it');
    const alert = container.querySelector('[data-item="error"]')!;
    expect(alert.textContent).toContain('drafter.errors.bad_request.startOver');
    expect(button('drafter.retry')).toBeUndefined();
    // Start over fixes it: a link in the Alert's text, in its colour.
    const startOver = button('drafter.startOver')!;
    expect(alert.querySelector('p')!.contains(startOver)).toBe(true);
    expect(startOver.dataset.tone).toBe('current');
    await act(async () => startOver.click());
    expect(container.querySelector('[data-item]')).toBeNull();
    expect(container.textContent).toContain('Tell me');
  });

  it.each([
    ['prompt_too_long', 'drafter.errors.prompt_too_long.description:100000'],
    ['empty_message', 'drafter.errors.empty_message.description'],
    ['request_invalid', 'drafter.errors.request_invalid.description'],
  ] as const)(
    'says why a %s request was refused, with no Start over: the conversation is fine',
    async (code, description) => {
      stream.scripts = [[{ type: 'error', code }, { type: 'end' }]];
      await ask('Draft it');
      const alert = container.querySelector('[data-item="error"]')!;
      expect(alert.textContent).toContain(`drafter.errors.${code}.title`);
      expect(alert.textContent).toContain(description);
      expect(alert.textContent).not.toContain(
        'drafter.errors.bad_request.startOver',
      );
      expect(button('drafter.retry')).toBeUndefined();
      expect(alert.querySelector('button')).toBeNull();
    },
  );

  it("caps the ask bar at the server's message length", () => {
    expect(askBar().maxLength).toBe(8000);
  });

  it('offers to start over once the conversation is full, and the host can start over any time', async () => {
    const onStartOver = vi.fn();
    await act(async () => root.render(<Host onStartOver={onStartOver} />));
    // Nothing to start over from yet.
    expect(button('drafter.startOver')).toBeUndefined();
    for (let turn = 0; turn < 12; turn += 1) {
      stream.scripts = [proposalTurn({ message: `Turn ${turn}` })];
      await ask(`Change ${turn}`);
    }
    const full = container.querySelector('[data-slot="drafter-full"]')!;
    expect(full.textContent).toContain('drafter.full.title');
    expect(askBar().disabled).toBe(true);
    // The header's Start over and the notice's both run the host's.
    const startOvers = Array.from(container.querySelectorAll('button')).filter(
      (b) =>
        b.textContent?.trim() === 'drafter.startOver' ||
        b.getAttribute('aria-label') === 'drafter.startOver',
    );
    expect(startOvers).toHaveLength(2);
    expect(full.contains(startOvers[1])).toBe(true);
    await act(async () => startOvers[0].click());
    await act(async () => startOvers[1].click());
    expect(onStartOver).toHaveBeenCalledTimes(2);
  });

  it('shows the running step on the status line and stops the turn', async () => {
    stream.hold = true;
    await ask('Draft it');
    const status = container.querySelector('[role="status"]')!;
    expect(status.textContent).toBe('drafter.steps.thinking');
    expect(status.querySelector('.shimmer-text')).not.toBeNull();
    await act(async () => button('drafter.stop')!.click());
    expect(stream.signals[0].aborted).toBe(true);
    expect(container.textContent).not.toContain('drafter.steps.thinking');
    expect(button('drafter.send')).toBeDefined();
  });

  it('sends with Enter, breaks the line with Shift+Enter, and greys Send while empty', async () => {
    const send = button('drafter.send')!;
    expect(send.disabled).toBe(true);
    expect(send.className).toContain('bg-muted');
    await act(async () => setValue(askBar(), 'Draft it'));
    expect(button('drafter.send')!.className).not.toContain('bg-muted');
    const press = (shiftKey: boolean) =>
      act(async () =>
        askBar().dispatchEvent(
          new KeyboardEvent('keydown', {
            key: 'Enter',
            shiftKey,
            bubbles: true,
            cancelable: true,
          }),
        ),
      );
    await press(true);
    expect(stream.requests).toHaveLength(0);
    await press(false);
    expect(stream.requests[0].messages).toEqual([
      { role: 'user', content: 'Draft it' },
    ]);
    expect(askBar().value).toBe('');
  });

  // Decision 63: after Stop or an error the step can go on (Continue).
  it('offers the way on under the latest error, and after a Stop', async () => {
    await act(async () =>
      root.render(
        <Host continueAction={<button type="button">Continue</button>} />,
      ),
    );
    expect(button('Continue')).toBeUndefined();
    stream.scripts = [[{ type: 'error', code: 'model_auth' }, { type: 'end' }]];
    await ask('Draft it');
    // Continue is a way past the error, on its own row under the Alert.
    const alert = container.querySelector('[data-item="error"]')!;
    const row = container.querySelector('[data-slot="drafter-continue"]')!;
    expect(row.contains(button('Continue')!)).toBe(true);
    expect(alert.contains(button('Continue')!)).toBe(false);
    expect(alert.nextElementSibling).toBe(row);

    stream.hold = true;
    await ask('Again');
    expect(button('Continue')).toBeUndefined();
    await act(async () => button('drafter.stop')!.click());
    // Decision 97: the chat's stopped note, with the way on under it.
    const note = container.querySelector('[data-item="stopped"]')!;
    expect(note.getAttribute('role')).toBe('note');
    expect(note.getAttribute('data-variant')).toBe('info');
    expect(note.textContent).toContain('conversation.stoppedTitle');
    expect(note.textContent).toContain('drafter.stoppedDescription');
    const stopped = container.querySelector('[data-slot="drafter-stopped"]')!;
    expect(stopped.contains(button('Continue')!)).toBe(true);
    expect(note.nextElementSibling).toBe(stopped);
    // A new turn takes the way on away; the note stays as the record.
    await ask('Once more');
    expect(button('Continue')).toBeUndefined();
    expect(container.querySelector('[data-item="stopped"]')).not.toBeNull();
  });

  // Continue would drop the message that failed; Try again sends it again.
  it.each(['model_error', 'rate_limited', 'invalid_output'] as const)(
    'offers only Try again under an error it fixes (%s)',
    async (code) => {
      await act(async () =>
        root.render(
          <Host continueAction={<button type="button">Continue</button>} />,
        ),
      );
      stream.scripts = [[{ type: 'error', code }, { type: 'end' }]];
      await ask('Draft it');
      // Try again fixes the error: a link in the Alert's text.
      const alert = container.querySelector('[data-item="error"]')!;
      const retry = button('drafter.retry')!;
      expect(alert.contains(retry)).toBe(true);
      expect(retry.dataset.variant).toBe('link');
      expect(retry.dataset.tone).toBe('current');
      expect(button('Continue')).toBeUndefined();
      expect(
        container.querySelector('[data-slot="drafter-continue"]'),
      ).toBeNull();
    },
  );

  it('says it is still waiting when a turn goes quiet for 30 s', async () => {
    vi.useFakeTimers();
    try {
      stream.hold = true;
      await ask('Draft it');
      expect(container.textContent).not.toContain('drafter.stillWaiting');
      await act(async () => vi.advanceTimersByTime(30_000));
      const line = container.querySelector('[data-slot="drafter-waiting"]')!;
      expect(line.textContent).toBe('drafter.stillWaiting');
      expect(line.className).toContain('text-xs');
      await act(async () => button('drafter.stop')!.click());
      expect(
        container.querySelector('[data-slot="drafter-waiting"]'),
      ).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('names the turn on the status line in the host’s words when it gives them', async () => {
    await act(async () => root.render(<Host statusLabel="Reviewing…" />));
    stream.hold = true;
    await ask('Review it');
    expect(container.querySelector('[role="status"]')!.textContent).toBe(
      'Reviewing…',
    );
  });

  it('says it looked at the workspace once, and again only when the counts change', async () => {
    const reading = (sources: number): DrafterEvent[] => [
      { type: 'status', step: 'reading', counts: { sources } },
      { type: 'message', text: 'Ok.' },
      { type: 'end' },
    ];
    stream.scripts = [reading(6), reading(6), reading(7)];
    await ask('One');
    await ask('Two');
    expect(container.querySelectorAll('[data-item="status"]')).toHaveLength(1);
    await ask('Three');
    expect(
      Array.from(container.querySelectorAll('[data-item="status"]')).map(
        (line) => line.textContent,
      ),
    ).toEqual([
      'drafter.lookedAtWorkspaceCounts:drafter.counts.sources:6',
      'drafter.lookedAtWorkspaceCounts:drafter.counts.sources:7',
    ]);
  });

  it("shows the host's own turn end after the conversation, not while a turn runs", async () => {
    await act(async () =>
      root.render(<Host after={<p data-testid="after">Saved.</p>} />),
    );
    stream.scripts = [proposalTurn({ message: 'Done.' })];
    await ask('Draft it');
    const after = container.querySelector('[data-testid="after"]')!;
    const proposal = container.querySelector('[data-item="proposal"]')!;
    expect(
      proposal.compareDocumentPosition(after) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    stream.hold = true;
    await ask('More');
    expect(container.querySelector('[data-testid="after"]')).toBeNull();
  });

  it('asks for a change by default and takes the caller placeholder', async () => {
    expect(askBar().placeholder).toBe('drafter.askPlaceholder');
    await act(async () => root.render(<Host placeholder="Describe it…" />));
    expect(askBar().placeholder).toBe('Describe it…');
  });

  it('shows the build progress in the header and the folded steps first', async () => {
    await act(async () =>
      root.render(
        <Host
          progress={{ label: 'Step 2 of 4 · Knowledge and tools', value: 25 }}
          before={<p data-testid="folded">Basics: Shipping help desk</p>}
        />,
      ),
    );
    const header = container.querySelector('[data-slot="panel-header"]')!;
    expect(header.textContent).toContain('Step 2 of 4 · Knowledge and tools');
    const bar = header.querySelector('[role="progressbar"]')!;
    expect(bar.getAttribute('aria-valuenow')).toBe('25');
    expect(bar.getAttribute('aria-valuetext')).toBe(
      'Step 2 of 4 · Knowledge and tools',
    );
    await ask('Draft it');
    const folded = container.querySelector('[data-testid="folded"]')!;
    const bubble = container.querySelector('[data-item="user"]')!;
    expect(
      folded.compareDocumentPosition(bubble) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it('scrolls to the latest item again when the panel reopens', async () => {
    stream.scripts = [proposalTurn({ message: 'Done.' })];
    await ask('Draft it');
    await act(async () => root.render(<Host open={false} />));
    const scroll = vi.fn();
    const original = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = scroll;
    try {
      await act(async () => root.render(<Host open />));
      expect(scroll).toHaveBeenCalled();
      expect(container.textContent).toContain('Done.');
    } finally {
      Element.prototype.scrollIntoView = original;
    }
  });

  // Live check C13: a phone sheet came back at the top of the conversation.
  it('scrolls to the latest item when a phone sheet comes back', async () => {
    media.isMobile = true;
    media.isDesktop = false;
    await act(async () => root.render(<Host />));
    stream.scripts = [proposalTurn({ message: 'Done.' })];
    const ask = document.querySelector<HTMLTextAreaElement>(
      'textarea[aria-label="drafter.askLabel"]',
    )!;
    await act(async () => setValue(ask, 'Draft it'));
    await act(async () =>
      document
        .querySelector<HTMLButtonElement>('button[aria-label="drafter.send"]')!
        .click(),
    );
    await act(async () => root.render(<Host open={false} />));
    await act(() => new Promise((resolve) => setTimeout(resolve, 20)));
    const scroll = vi.fn();
    const original = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = scroll;
    try {
      await act(async () => root.render(<Host open />));
      expect(document.body.textContent).toContain('Done.');
      expect(scroll).toHaveBeenCalledWith({ block: 'end' });
    } finally {
      Element.prototype.scrollIntoView = original;
    }
  });

  it('announces the step and each applied draft, not the whole conversation', async () => {
    const announce = (p: unknown) => (p as Proposal).note ?? null;
    await act(async () => root.render(<Host announceProposal={announce} />));
    stream.hold = true;
    await ask('Draft it');
    const live = Array.from(container.querySelectorAll('[aria-live]'));
    expect(live.some((el) => el.textContent === 'drafter.steps.thinking')).toBe(
      true,
    );
    const bubble = container.querySelector('[data-item="user"]')!;
    expect(live.some((el) => el.contains(bubble))).toBe(false);

    await act(async () => root.unmount());
    root = createRoot(container);
    stream.hold = false;
    stream.scripts = [proposalTurn({ message: 'Done.', note: 'Drafted 2' })];
    await act(async () => root.render(<Host announceProposal={announce} />));
    await ask('Draft it');
    const region = container.querySelector('[data-slot="drafter-live"]')!;
    expect(region.getAttribute('aria-live')).toBe('polite');
    expect(region.textContent).toBe('Drafted 2');
    expect(
      region.contains(container.querySelector('[data-item="proposal"]')),
    ).toBe(false);
  });

  // Live check [#16]: focus dropped to <body> after Send answers and Stop.
  describe('focus', () => {
    const questions: DrafterEvent = {
      type: 'questions',
      questions: [
        {
          id: 'q1',
          text: 'Where should refunds go?',
          note: null,
          multi: false,
          options: [
            { id: 'a', label: 'Email support' },
            { id: 'b', label: 'Stop' },
          ],
        },
      ],
    };
    const radios = () =>
      Array.from(
        container.querySelectorAll<HTMLButtonElement>('[role="radio"]'),
      );

    it('lands on the first new question when a turn ends on them', async () => {
      stream.scripts = [[questions, { type: 'end' }]];
      await ask('A shipping agent');
      expect(document.activeElement).toBe(radios()[0]);
    });

    it('keeps it in the ask bar while the user is typing there', async () => {
      stream.hold = true;
      await ask('A shipping agent');
      askBar().focus();
      await act(async () => setValue(askBar(), 'And returns'));
      expect(document.activeElement).toBe(askBar());
    });

    it('moves it to the ask bar after Send answers and after Stop', async () => {
      stream.scripts = [[questions, { type: 'end' }]];
      await ask('A shipping agent');
      await act(async () => radios()[1].click());
      stream.hold = true;
      const send = button('questions.sendAnswers')!;
      send.focus();
      await act(async () => send.click());
      expect(document.activeElement).toBe(askBar());

      const stop = button('drafter.stop')!;
      stop.focus();
      await act(async () => stop.click());
      expect(document.activeElement).toBe(askBar());
    });

    it('leaves it where the user put it in the page', async () => {
      const outside = document.createElement('input');
      document.body.appendChild(outside);
      try {
        stream.hold = true;
        await ask('A shipping agent');
        outside.dispatchEvent(new Event('pointerdown', { bubbles: true }));
        outside.focus();
        outside.blur();
        await act(async () => button('drafter.stop')!.click());
        expect(document.activeElement).not.toBe(askBar());
      } finally {
        outside.remove();
      }
    });
  });

  // Live check [#18, #19]: what renders after the scroll (review actions, a
  // field opening in a question) keeps the end in view.
  it('keeps the end in view as late content grows the conversation', async () => {
    const callbacks: (() => void)[] = [];
    const original = globalThis.ResizeObserver;
    globalThis.ResizeObserver = class {
      constructor(callback: () => void) {
        callbacks.push(callback);
      }
      observe() {}
      disconnect() {}
      unobserve() {}
    } as unknown as typeof ResizeObserver;
    const scroll = vi.fn();
    const scrollOriginal = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = scroll;
    try {
      await act(async () => root.render(<Host open={false} />));
      await act(async () => root.render(<Host open />));
      scroll.mockClear();
      await act(async () => callbacks.forEach((callback) => callback()));
      expect(scroll).toHaveBeenCalledWith({ block: 'end' });
      // Scrolled up, the user stays where they are.
      const body = container.querySelector<HTMLElement>(
        '[data-slot="panel-body"]',
      )!;
      Object.defineProperty(body, 'scrollHeight', { value: 2000 });
      Object.defineProperty(body, 'clientHeight', { value: 500 });
      body.scrollTop = 100;
      body.dispatchEvent(new Event('scroll'));
      scroll.mockClear();
      await act(async () => callbacks.forEach((callback) => callback()));
      expect(scroll).not.toHaveBeenCalled();
    } finally {
      globalThis.ResizeObserver = original;
      Element.prototype.scrollIntoView = scrollOriginal;
    }
  });

  it('lands a turn that ends on questions on the first of them', async () => {
    const scrolled: Element[] = [];
    const original = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = function (this: Element) {
      scrolled.push(this);
    };
    try {
      stream.scripts = [
        [
          {
            type: 'questions',
            questions: [
              { id: 'q1', text: 'One?', note: null, multi: false, options: [] },
              { id: 'q2', text: 'Two?', note: null, multi: false, options: [] },
            ],
          },
          { type: 'end' },
        ],
      ];
      await ask('Draft it');
      const first = container.querySelector('[data-question="q1"]');
      expect(scrolled.at(-1)).toBe(first);
    } finally {
      Element.prototype.scrollIntoView = original;
    }
  });

  it('focuses the ask bar when the panel opens on a desktop', async () => {
    await act(async () => root.render(<Host open={false} />));
    (document.activeElement as HTMLElement | null)?.blur();
    await act(async () => root.render(<Host open />));
    expect(document.activeElement).toBe(askBar());
  });

  it('leaves focus alone when the panel opens below desktop width', async () => {
    media.isDesktop = false;
    await act(async () => root.render(<Host open={false} />));
    (document.activeElement as HTMLElement | null)?.blur();
    await act(async () => root.render(<Host open />));
    expect(document.activeElement).not.toBe(askBar());
  });
});
