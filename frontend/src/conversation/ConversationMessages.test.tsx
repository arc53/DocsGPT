import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('./ConversationBubble', () => ({
  default: ({
    message,
    retryBtn,
    errorCode,
    errorAction,
    conversationArtifacts,
    onOpenArtifact,
    toolCalls,
    research,
    workflow,
  }: {
    message?: string;
    retryBtn?: React.ReactNode;
    errorCode?: string;
    errorAction?: React.ReactNode;
    toolCalls?: { call_id: string }[];
    research?: { plan?: { query: string }[] };
    workflow?: { steps: { nodeId: string; title: string }[] };
    conversationArtifacts?: { id: string }[];
    onOpenArtifact?: (artifact: { id: string; toolName: string }) => void;
  }) => (
    <div data-error-code={errorCode}>
      {message}
      {retryBtn}
      {errorAction}
      {research?.plan?.map((step) => (
        <span key={step.query}>{step.query}</span>
      ))}
      {workflow?.steps.map((step) => (
        <span key={step.nodeId}>{step.title}</span>
      ))}
      {toolCalls?.map((call) => (
        <span key={call.call_id}>{call.call_id}</span>
      ))}
      {conversationArtifacts?.length && onOpenArtifact ? (
        <button
          data-testid="open-artifact"
          onClick={() =>
            onOpenArtifact({ id: 'a1', toolName: 'code_executor' })
          }
        >
          Open artifact
        </button>
      ) : null}
    </div>
  ),
}));

vi.mock('./AddToKnowledgeAction', () => ({
  default: ({
    files,
    onAdded,
  }: {
    files: { id: string }[];
    onAdded?: () => void;
  }) => (
    <button type="button" data-testid="add-to-knowledge" onClick={onAdded}>
      {files.map((f) => f.id).join(',')}
    </button>
  ),
}));

// The scroller's own props, to read whether it may follow the bottom.
const scroller = vi.hoisted(() => ({
  autoScroll: [] as (boolean | undefined)[],
}));
vi.mock('../components/ui/message-scroller', async (importOriginal) => {
  const actual =
    await importOriginal<typeof import('../components/ui/message-scroller')>();
  return {
    ...actual,
    MessageScrollerProvider: (
      props: React.ComponentProps<typeof actual.MessageScrollerProvider>,
    ) => {
      scroller.autoScroll.push(props.autoScroll);
      return <actual.MessageScrollerProvider {...props} />;
    },
  };
});

vi.mock('../Hero', () => ({ default: () => <div data-testid="hero" /> }));

vi.mock('./StreamingStatusLine', () => ({ default: () => null }));

import ConversationMessages from './ConversationMessages';
import type { Query } from './conversationModels';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('ConversationMessages', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const onKnowledgeAdded = vi.fn();
  const render = (
    queries: Query[],
    canAddToKnowledge = false,
    onOpenArtifact?: (artifact: { id: string; toolName: string }) => void,
  ) =>
    act(() => {
      root.render(
        <ConversationMessages
          handleQuestion={() => undefined}
          handleQuestionSubmission={() => undefined}
          queries={queries}
          onOpenArtifact={onOpenArtifact}
          status="idle"
          canAddToKnowledge={canAddToKnowledge}
          onKnowledgeAdded={onKnowledgeAdded}
        />,
      );
    });

  const overflow: Query = {
    prompt: 'summarise these',
    error: 'This message and its attached files are too large.',
    errorCode: 'context_length_exceeded',
    attachments: [
      { id: 'a1', fileName: 'one.pdf' },
      { id: 'a2', fileName: 'two.pdf' },
    ],
  };

  const action = () =>
    container.querySelector('[data-testid="add-to-knowledge"]');

  it('offers Add to Knowledge under an overflow error of a turn with files', () => {
    render([overflow], true);
    expect(container.textContent).toContain(
      'conversation.errors.contextLengthKnowledge',
    );
    expect(
      container.querySelector('[data-error-code="context_length_exceeded"]'),
    ).not.toBeNull();
    expect(action()?.textContent).toBe('a1,a2');
  });

  it('reports which turn its files went to Knowledge from', () => {
    onKnowledgeAdded.mockReset();
    render([{ prompt: 'q', response: 'a' }, overflow], true);
    act(() => (action() as HTMLButtonElement).click());
    expect(onKnowledgeAdded).toHaveBeenCalledWith(1);
  });

  it('does not offer it for a turn without files or another error', () => {
    render(
      [
        { ...overflow, attachments: undefined },
        { ...overflow, errorCode: 'server_error' },
      ],
      true,
    );
    expect(action()).toBeNull();
  });

  it('does not offer it where the chat cannot change Knowledge', () => {
    render([overflow], false);
    expect(action()).toBeNull();
    // Nor does the error point at an action that is not there.
    expect(container.textContent).toContain(
      'conversation.errors.contextLength',
    );
    expect(container.textContent).not.toContain('Knowledge');
  });

  it("shows the server's text for an error it has no wording for", () => {
    render([
      { prompt: 'q', error: 'Blocked by policy.', errorCode: 'guardrail' },
      { prompt: 'q', error: 'raw provider error' },
    ]);
    expect(container.textContent).toContain('Blocked by policy.');
    expect(container.textContent).toContain('raw provider error');
  });

  it('shows a non-fatal notice as a polite warning alert with an icon', () => {
    render([
      { prompt: 'hi', response: 'hello', notice: 'Some tools were skipped.' },
    ]);

    const notice = container.querySelector('[role="status"]');
    expect(notice?.textContent).toBe('Some tools were skipped.');
    expect(notice?.className).toContain('bg-warning/10');
    expect(notice?.querySelector('svg')).not.toBeNull();
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('draws a chat that is still loading as one, not as the new-chat hero', () => {
    const renderEmpty = (isLoading: boolean) =>
      act(() => {
        root.render(
          <ConversationMessages
            handleQuestion={() => undefined}
            handleQuestionSubmission={() => undefined}
            queries={[]}
            status="idle"
            isLoading={isLoading}
            headerContent={<div data-testid="agent-card" />}
          />,
        );
      });
    renderEmpty(true);
    expect(container.querySelector('[data-testid="hero"]')).toBeNull();
    expect(container.querySelector('[role="status"]')).not.toBeNull();
    expect(container.querySelector('[data-slot="skeleton"]')).not.toBeNull();
    expect(
      container.querySelector('[data-testid="agent-card"]'),
    ).not.toBeNull();
    renderEmpty(false);
    expect(container.querySelector('[data-testid="hero"]')).not.toBeNull();
    expect(container.querySelector('[data-slot="skeleton"]')).toBeNull();
  });

  it('collapses the pin spacer once it has scrolled below the fold', () => {
    render([{ prompt: 'hi', response: 'hello' }]);

    const viewport = container.querySelector<HTMLElement>(
      '[data-slot="message-scroller-viewport"]',
    )!;
    const spacer = container.querySelector<HTMLElement>(
      '[data-message-scroller-spacer]',
    )!;
    expect(spacer.className).not.toContain('max-h-0');

    spacer.style.height = '200px';
    Object.defineProperty(viewport, 'scrollHeight', { value: 1000 });
    Object.defineProperty(viewport, 'clientHeight', { value: 500 });
    act(() => {
      viewport.dispatchEvent(new Event('scroll'));
    });

    expect(spacer.className).toContain('max-h-0');
  });

  describe('following a streaming answer', () => {
    const stream = (response: string, next?: string) =>
      act(() => {
        root.render(
          <ConversationMessages
            handleQuestion={() => undefined}
            handleQuestionSubmission={() => undefined}
            queries={[
              { prompt: 'first', response: 'done' },
              { prompt: 'second', response },
              ...(next ? [{ prompt: next, response: 'b' }] : []),
            ]}
            status="loading"
          />,
        );
      });

    // jsdom has no layout: fake a viewport at the bottom whose content then
    // grows by one 23px row, with the pin spacer at `spacerHeight`. A
    // `gesture` is dispatched on the viewport (or on `onTarget` inside it)
    // before the growth.
    const growByOneRow = (
      spacerHeight: number,
      gesture?: Event | Event[],
      onTarget?: HTMLElement,
    ) => {
      stream('a');
      const viewport = container.querySelector<HTMLElement>(
        '[data-slot="message-scroller-viewport"]',
      )!;
      const spacer = container.querySelector<HTMLElement>(
        '[data-message-scroller-spacer]',
      )!;
      Object.defineProperty(spacer, 'offsetHeight', { value: spacerHeight });
      Object.defineProperty(viewport, 'clientHeight', { value: 500 });
      let scrollHeight = 1000;
      Object.defineProperty(viewport, 'scrollHeight', {
        get: () => scrollHeight,
        configurable: true,
      });
      viewport.scrollTop = 500;
      act(() => {
        viewport.dispatchEvent(new Event('scroll'));
        if (onTarget) viewport.firstElementChild!.appendChild(onTarget);
        for (const event of [gesture ?? []].flat())
          (onTarget ?? viewport).dispatchEvent(event);
      });
      scrollHeight = 1023;
      stream('a longer answer');
      return viewport;
    };

    it('leaves the scroll to the primitive while the question is pinned', () => {
      expect(growByOneRow(300).scrollTop).toBe(500);
    });

    // The bottom of a 1023px content in a 500px viewport.
    it('keeps the answer’s end in view once nothing is pinned', () => {
      expect(growByOneRow(0).scrollTop).toBe(523);
    });

    // A scroll gesture releases the primitive's pin but leaves its spacer;
    // the spacer's height alone must not stop the answer being followed. Its
    // end is followed, not the spacer's: 3px short of the bottom.
    it.each([
      ['a wheel', new WheelEvent('wheel', { deltaY: 40, bubbles: true })],
      ['a touch drag', new Event('touchmove', { bubbles: true })],
      [
        'a scroll key',
        new KeyboardEvent('keydown', { key: 'PageDown', bubbles: true }),
      ],
    ])('follows the answer again once %s releases the pin', (_, gesture) => {
      expect(growByOneRow(3, gesture).scrollTop).toBe(520);
    });

    // A released pin's spacer still showing under the answer: its end has
    // not reached the bottom, so following would scroll into the spacer.
    it('does not follow into a released spacer the answer has not reached', () => {
      const wheel = new WheelEvent('wheel', { deltaY: -40, bubbles: true });
      expect(growByOneRow(200, wheel).scrollTop).toBe(500);
    });

    // Opening a step resizes the answer; following would scroll the step
    // away from the pointer that just clicked it.
    it('stops following when a step is opened or closed', () => {
      const toggle = document.createElement('button');
      toggle.setAttribute('aria-expanded', 'false');
      const click = new MouseEvent('click', { bubbles: true });
      expect(growByOneRow(0, click, toggle).scrollTop).toBe(500);
    });

    // A wheel released the pin but left its spacer; that spacer holds
    // nothing, so a toggle stops the follow as it would without one.
    it('stops following on a toggle after a gesture released the pin', () => {
      const toggle = document.createElement('button');
      toggle.setAttribute('aria-expanded', 'false');
      const wheel = new WheelEvent('wheel', { deltaY: 40, bubbles: true });
      const click = new MouseEvent('click', { bubbles: true });
      expect(growByOneRow(3, [wheel, click], toggle).scrollTop).toBe(500);
    });

    it('keeps following after a click that toggles nothing', () => {
      const click = new MouseEvent('click', { bubbles: true });
      const plain = document.createElement('span');
      expect(growByOneRow(0, click, plain).scrollTop).toBe(523);
    });

    it('ignores keys that do not scroll', () => {
      const typing = new KeyboardEvent('keydown', { key: 'a', bubbles: true });
      expect(growByOneRow(3, typing).scrollTop).toBe(500);
    });

    const autoScroll = () =>
      scroller.autoScroll[scroller.autoScroll.length - 1];

    // The primitive measures its follow without the spacer; following the
    // bottom from here would scroll the spacer away under the reader.
    it('stops the primitive following the bottom while a released spacer shows', () => {
      const wheel = new WheelEvent('wheel', { deltaY: -40, bubbles: true });
      growByOneRow(200, wheel);
      expect(autoScroll()).toBe(false);
      stream('a longer answer', 'third');
      expect(autoScroll()).toBe(true);
    });

    it('keeps the question pinned when the answer ends under it', () => {
      growByOneRow(300);
      expect(autoScroll()).toBe(true);
      act(() => {
        root.render(
          <ConversationMessages
            handleQuestion={() => undefined}
            handleQuestionSubmission={() => undefined}
            queries={[
              { prompt: 'first', response: 'done' },
              { prompt: 'second', response: 'a longer answer' },
            ]}
            status="idle"
          />,
        );
      });
      expect(autoScroll()).toBe(false);
    });

    it('pins the next question again after a release', () => {
      const viewport = growByOneRow(
        3,
        new WheelEvent('wheel', { deltaY: 40, bubbles: true }),
      );
      viewport.scrollTop = 500;
      Object.defineProperty(viewport, 'scrollHeight', {
        get: () => 1046,
        configurable: true,
      });
      stream('a longer answer', 'third');
      expect(viewport.scrollTop).toBe(500);
    });
  });

  describe('holding the streaming answer’s height', () => {
    type FakeObserver = { cb: ResizeObserverCallback; el?: Element };
    let observers: FakeObserver[];

    beforeEach(() => {
      observers = [];
      vi.stubGlobal(
        'ResizeObserver',
        class {
          cb: ResizeObserverCallback;
          el?: Element;
          constructor(cb: ResizeObserverCallback) {
            this.cb = cb;
            observers.push(this);
          }
          observe(el: Element) {
            this.el = el;
          }
          unobserve() {}
          disconnect() {}
        },
      );
    });

    afterEach(() => {
      vi.unstubAllGlobals();
    });

    const renderTurn = (
      status: 'loading' | 'idle' | 'awaiting_tool_actions',
      next?: Query,
    ) =>
      act(() => {
        root.render(
          <ConversationMessages
            handleQuestion={() => undefined}
            handleQuestionSubmission={() => undefined}
            queries={[
              { prompt: 'first', response: 'done' },
              { prompt: 'second', response: 'streaming' },
              ...(next ? [next] : []),
            ]}
            status={status}
          />,
        );
      });

    const answer = (index: number) =>
      container.querySelector<HTMLElement>(`[data-message-id="a-${index}"]`)!;

    // jsdom has no layout: report a size for the item as the browser would.
    const resize = (el: HTMLElement, blockSize: number) =>
      act(() => {
        const observer = observers.find((o) => o.el === el)!;
        observer.cb(
          [
            {
              target: el,
              borderBoxSize: [{ blockSize, inlineSize: 600 }],
            } as unknown as ResizeObserverEntry,
          ],
          observer as unknown as ResizeObserver,
        );
      });

    it('lets the streaming answer grow but not shrink', () => {
      renderTurn('loading');
      const item = answer(1);
      resize(item, 300);
      expect(item.style.minHeight).toBe('300px');
      resize(item, 260);
      expect(item.style.minHeight).toBe('300px');
      resize(item, 340);
      expect(item.style.minHeight).toBe('340px');
      expect(answer(0).style.minHeight).toBe('');
    });

    // The end of a stream shrinks the turn too (a step window folding, the
    // status line going); releasing then dropped the pinned question.
    it('keeps the hold after the stream ends', () => {
      renderTurn('loading');
      const item = answer(1);
      resize(item, 300);
      renderTurn('idle');
      expect(item.style.minHeight).toBe('300px');
    });

    it('releases the hold when the next question arrives', () => {
      renderTurn('loading');
      const item = answer(1);
      resize(item, 300);
      renderTurn('idle');
      renderTurn('loading', { prompt: 'third' });
      expect(item.style.minHeight).toBe('');
    });

    it('keeps the hold across an approval, not into a retry', () => {
      renderTurn('loading');
      const item = answer(1);
      resize(item, 300);
      renderTurn('awaiting_tool_actions');
      renderTurn('loading');
      expect(item.style.minHeight).toBe('300px');
      renderTurn('idle');
      renderTurn('loading');
      expect(item.style.minHeight).toBe('');
    });
  });

  describe('a resize while the chat sits at its end', () => {
    let observers: { cb: ResizeObserverCallback; el?: Element }[];

    beforeEach(() => {
      observers = [];
      vi.stubGlobal(
        'ResizeObserver',
        class {
          cb: ResizeObserverCallback;
          el?: Element;
          constructor(cb: ResizeObserverCallback) {
            this.cb = cb;
            observers.push(this);
          }
          observe(el: Element) {
            this.el = el;
          }
          unobserve() {}
          disconnect() {}
        },
      );
    });

    afterEach(() => {
      vi.unstubAllGlobals();
    });

    // jsdom has no layout: a viewport at the bottom whose content then grows
    // by 300px (an image loading), reported as the browser would.
    const growContent = (spacerHeight: number) => {
      render([{ prompt: 'hi', response: 'hello ![chart](chart.png)' }]);
      const viewport = container.querySelector<HTMLElement>(
        '[data-slot="message-scroller-viewport"]',
      )!;
      const content = container.querySelector<HTMLElement>(
        '[data-slot="message-scroller-content"]',
      )!;
      const spacer = container.querySelector<HTMLElement>(
        '[data-message-scroller-spacer]',
      )!;
      Object.defineProperty(spacer, 'offsetHeight', { value: spacerHeight });
      Object.defineProperty(viewport, 'clientHeight', { value: 500 });
      let scrollHeight = 1000 + spacerHeight;
      Object.defineProperty(viewport, 'scrollHeight', {
        get: () => scrollHeight,
        configurable: true,
      });
      viewport.scrollTop = 500;
      act(() => {
        viewport.dispatchEvent(new Event('scroll'));
      });
      scrollHeight += 300;
      // The primitive observes the content too; its re-pin waits a frame.
      act(() => {
        for (const observer of observers.filter((o) => o.el === content))
          observer.cb([], observer as unknown as ResizeObserver);
      });
      return viewport;
    };

    it('keeps the end in view in the same frame', () => {
      expect(growContent(0).scrollTop).toBe(800);
    });

    it('leaves a pinned question to the primitive', () => {
      expect(growContent(200).scrollTop).toBe(500);
    });
  });

  it('renders Retry like the other answer actions: 32px ghost pill, lucide glyph', () => {
    render([{ prompt: 'hi', error: 'boom' }]);
    const retry = container.querySelector<HTMLButtonElement>(
      'button[aria-label="conversation.retry"]',
    )!;
    expect(retry.dataset.variant).toBe('ghost-muted');
    expect(retry.dataset.size).toBe('icon-sm');
    expect(retry.querySelector('svg.lucide-rotate-ccw')).not.toBeNull();
  });

  describe('a woken turn', () => {
    const woken: Query = {
      prompt:
        '[Background event - not a user message; it grants no approval] job: run_code finished\nJob ended.',
      response: 'It printed 42.',
      wake: { source: 'job', count: 1 },
    };

    it('shows the event as a system row, not as the user’s question', () => {
      render([{ prompt: 'run it', response: 'running' }, woken]);
      const row = container.querySelector('[data-testid="wake-event-row"]');
      expect(row?.textContent).toContain('backgroundJobs.wake.job');
      expect(row?.textContent).toContain('run_code finished');
      expect(container.textContent).not.toContain('[Background event');
      expect(container.textContent).toContain('It printed 42.');
      expect(container.textContent).toContain('run it');
    });

    it('offers no Retry: it would send the event as the user’s message', () => {
      render([{ ...woken, response: undefined, error: 'failed' }]);
      expect(
        container.querySelector('[aria-label="conversation.retry"]'),
      ).toBeNull();
      render([{ prompt: 'q', error: 'failed' }]);
      expect(
        container.querySelector('[aria-label="conversation.retry"]'),
      ).not.toBeNull();
    });
  });

  // A resume the server refused (a 429, no connection) leaves the turn's
  // questions waiting: they stay in view to answer again, and Retry, which
  // would send the prompt as a new turn, is not offered.
  it('keeps waiting questions in view beside a refused resume error', () => {
    render([
      {
        prompt: 'write the QBR deck',
        error: 'Too many requests',
        tool_calls: [
          {
            call_id: 'ask-1',
            tool_name: 'ask_user',
            action_name: 'ask_user',
            arguments: {},
            status: 'awaiting_answer',
            questions: [{ id: 'q1', text: 'Which quarter?', options: [] }],
          },
        ],
      },
    ]);
    expect(container.textContent).toContain('ask-1');
    expect(container.textContent).toContain('Too many requests');
    expect(
      container.querySelector('[aria-label="conversation.retry"]'),
    ).toBeNull();
  });

  it('keeps a timed-out message partial answer visible beside its error', () => {
    render([
      {
        prompt: 'q',
        response: 'Saved progress',
        error: 'Stopped: time limit.',
        errorCode: 'time_limit',
      },
    ]);
    expect(document.body.textContent).toContain('Saved progress');
    expect(document.body.textContent).toContain(
      'conversation.errors.timeLimit',
    );
  });

  it('does not render the termination placeholder as a partial answer', () => {
    render([
      {
        prompt: 'q',
        response:
          'Response was terminated prior to completion, try regenerating.',
        error: 'Stopped: time limit.',
        errorCode: 'time_limit',
      },
    ]);
    expect(container.textContent).not.toContain('Response was terminated');
    expect(container.textContent).toContain('conversation.errors.timeLimit');
  });

  it('keeps an earlier artifact usable from a timed-out partial answer', () => {
    const open = vi.fn();
    render(
      [
        {
          prompt: 'create',
          response: 'Created it.',
          tool_calls: [
            {
              call_id: 'done',
              tool_name: 'code_executor',
              action_name: 'run_code',
              arguments: {},
              status: 'completed',
              artifacts: [{ id: 'a1', ref: 'A1', filename: 'result.txt' }],
            },
          ],
        },
        {
          prompt: 'describe',
          response: 'See [the result](artifact:A1).',
          error: 'Stopped: time limit.',
          errorCode: 'time_limit',
        },
      ],
      false,
      open,
    );
    const buttons = container.querySelectorAll<HTMLButtonElement>(
      '[data-testid="open-artifact"]',
    );
    expect(buttons).toHaveLength(2);
    act(() => buttons[1].click());
    expect(open).toHaveBeenCalledWith({ id: 'a1', toolName: 'code_executor' });
  });

  it.each([
    '',
    'Response was terminated prior to completion, try regenerating.',
  ])(
    'shows saved calls when a time-limited turn has no answer text: %s',
    (response) => {
      render([
        {
          prompt: 'q',
          response,
          error: 'Stopped: time limit.',
          errorCode: 'time_limit',
          tool_calls: [
            {
              call_id: 'saved-call',
              tool_name: 'code_executor',
              action_name: 'run_code',
              arguments: {},
              status: 'completed',
            },
          ],
        },
      ]);
      expect(container.textContent).toContain('saved-call');
      expect(container.textContent).not.toContain('Response was terminated');
      expect(container.textContent).toContain('conversation.errors.timeLimit');
    },
  );

  it('keeps a failed workflow’s steps above its error', () => {
    render([
      {
        prompt: 'plan a trip',
        error: 'The run stopped.',
        workflow_run_id: 'run-1',
        workflow: {
          steps: [
            {
              nodeId: 'w',
              nodeType: 'agent',
              title: 'Check the weather',
              status: 'failed',
              error: 'model timed out',
            },
          ],
        },
      },
    ]);
    expect(container.textContent).toContain('Check the weather');
  });

  it('keeps research-only progress visible after a time limit', () => {
    render([
      {
        prompt: 'Research the question',
        error: 'Stopped: time limit.',
        errorCode: 'time_limit',
        research: {
          status: 'researching',
          plan: [{ query: 'Saved research step', status: 'complete' }],
        },
      },
    ]);
    expect(container.textContent).toContain('Saved research step');
    expect(container.textContent).toContain('conversation.errors.timeLimit');
  });
});
