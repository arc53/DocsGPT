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
    const radio = Array.from(
      container.querySelectorAll<HTMLButtonElement>('[role="radio"]'),
    )[1];
    await act(async () => radio.click());
    await act(async () => button('drafter.sendAnswers')!.click());
    expect(stream.requests[1].messages).toEqual([
      { role: 'user', content: 'A shipping agent' },
      { role: 'assistant', content: JSON.stringify(questions) },
      { role: 'user', content: 'Where should refunds go? → Stop' },
    ]);
    expect(onProposal).toHaveBeenCalledWith(proposal);
    expect(container.textContent).toContain('Draft is in the form.');
    // Answered questions can't be sent again.
    expect(button('drafter.sendAnswers')).toBeUndefined();
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
  it('offers the way on beside Retry in the latest error, and after a Stop', async () => {
    await act(async () =>
      root.render(
        <Host continueAction={<button type="button">Continue</button>} />,
      ),
    );
    expect(button('Continue')).toBeUndefined();
    stream.scripts = [
      [{ type: 'error', code: 'model_error' }, { type: 'end' }],
    ];
    await ask('Draft it');
    const alert = container.querySelector('[data-item="error"]')!;
    const row = button('drafter.retry')!.parentElement!;
    expect(row.contains(button('Continue')!)).toBe(true);
    expect(alert.contains(row)).toBe(true);

    stream.hold = true;
    await ask('Again');
    expect(button('Continue')).toBeUndefined();
    await act(async () => button('drafter.stop')!.click());
    const stopped = container.querySelector('[data-slot="drafter-stopped"]')!;
    expect(stopped.contains(button('Continue')!)).toBe(true);
    // A new turn takes it away.
    await ask('Once more');
    expect(button('Continue')).toBeUndefined();
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
