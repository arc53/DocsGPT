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
          : key,
    i18n: { language: 'en' },
  }),
}));
vi.mock('react-redux', () => ({
  useSelector: (selector: (state: unknown) => unknown) =>
    selector({ preference: { token: 'tok' } }),
}));
vi.mock('../hooks', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../hooks')>()),
  useMediaQuery: () => ({ isMobile: false, isDesktop: true }),
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

import { DraftPanel } from './DraftPanel';
import { ProposalSummary } from './ProposalSummary';
import { useDrafterSession } from './useDrafterSession';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const onProposal = vi.fn();

function Host() {
  const session = useDrafterSession({
    recipe: 'agent',
    getContext: () => ({ form: { name: 'Now' } }),
    onProposal,
  });
  return (
    <MemoryRouter>
      <DraftPanel
        open
        onOpenChange={() => undefined}
        session={session}
        modelName="Fast model"
        intro="Tell me"
        examples={['Support agent']}
        renderProposal={(proposal, latest) => (
          <ProposalSummary
            message={(proposal as { message: string }).message}
            rows={[{ key: 'n', label: 'Name', summary: 'Shipping help' }]}
            onUndoAll={latest ? () => undefined : undefined}
          />
        )}
      />
    </MemoryRouter>
  );
}

const setValue = (
  el: HTMLTextAreaElement | HTMLInputElement,
  value: string,
) => {
  const proto =
    el instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, 'value')!.set!.call(el, value);
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

  it('starts with the intro, puts an example in the ask bar and names the model', async () => {
    expect(container.textContent).toContain('Tell me');
    expect(container.textContent).toContain('drafter.footer:Fast model');
    expect(
      container.querySelector('a[href="/settings/general"]')?.textContent,
    ).toBe('drafter.changeModel');
    await act(async () => button('Support agent')!.click());
    expect(askBar().value).toBe('Support agent');
  });

  it('asks questions, sends the answers as one message, then shows the proposal', async () => {
    const questions: DrafterEvent = {
      type: 'questions',
      questions: [
        {
          id: 'q1',
          text: 'Where should refunds go?',
          note: 'No ticketing tool is connected.',
          multi: false,
          options: [
            { id: 'a', label: 'Email support' },
            { id: 'b', label: 'Stop' },
          ],
        },
        {
          id: 'q2',
          text: 'Which knowledge?',
          note: null,
          multi: true,
          options: [
            { id: 'h', label: 'Help Center' },
            { id: 's', label: 'Shipping' },
          ],
        },
      ],
    };
    const proposal = { message: 'Draft is in the form.', fields: {} };
    stream.scripts = [
      [
        { type: 'status', step: 'reading', counts: { sources: 6, tools: 11 } },
        { type: 'message', text: 'Two questions first.' },
        questions,
        { type: 'end' },
      ],
      [
        { type: 'status', step: 'drafting' },
        { type: 'proposal', proposal },
        { type: 'end' },
      ],
    ];

    await ask('A shipping agent');
    expect(stream.requests[0]).toEqual({
      recipe: 'agent',
      messages: [{ role: 'user', content: 'A shipping agent' }],
      context: { form: { name: 'Now' } },
    });
    expect(container.textContent).toContain('drafter.lookedAtWorkspace');
    expect(container.textContent).toContain('drafter.counts.sources:6');
    expect(container.textContent).toContain('Two questions first.');
    expect(container.textContent).toContain('No ticketing tool is connected.');

    // One pick for q1 (the second chip replaces the first), several for q2,
    // and "Something else" adds free text.
    await act(async () => button('Email support')!.click());
    await act(async () => button('Stop')!.click());
    await act(async () => button('Help Center')!.click());
    await act(async () => button('Shipping')!.click());
    const q2 = container.querySelector('[data-question="q2"]')!;
    const other = Array.from(q2.querySelectorAll('button')).find(
      (b) => b.textContent === 'drafter.somethingElse',
    )!;
    await act(async () => other.click());
    await act(async () =>
      setValue(q2.querySelector('input')!, 'Returns policy'),
    );
    await act(async () => button('drafter.sendAnswers')!.click());

    const second = stream.requests[1];
    expect(second.messages).toEqual([
      { role: 'user', content: 'A shipping agent' },
      { role: 'assistant', content: JSON.stringify(questions) },
      {
        role: 'user',
        content:
          'Where should refunds go? → Stop\n' +
          'Which knowledge? → Help Center, Shipping, Returns policy',
      },
    ]);
    expect(onProposal).toHaveBeenCalledWith(proposal);
    expect(container.textContent).toContain('Draft is in the form.');
    expect(button('drafter.undoAll')).toBeDefined();
    // Answered questions can't be sent again.
    expect(button('drafter.sendAnswers')).toBeUndefined();
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

  it('stops a running turn', async () => {
    stream.hold = true;
    await ask('Draft it');
    expect(container.textContent).toContain('drafter.steps.thinking');
    await act(async () => button('drafter.stop')!.click());
    expect(stream.signals[0].aborted).toBe(true);
    expect(container.textContent).not.toContain('drafter.steps.thinking');
    expect(button('drafter.send')).toBeDefined();
  });
});
