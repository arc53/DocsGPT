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
  }: {
    message?: string;
    retryBtn?: React.ReactNode;
    errorCode?: string;
    errorAction?: React.ReactNode;
  }) => (
    <div data-error-code={errorCode}>
      {message}
      {retryBtn}
      {errorAction}
    </div>
  ),
}));

vi.mock('./AddToKnowledgeAction', () => ({
  default: ({ files }: { files: { id: string }[] }) => (
    <span data-testid="add-to-knowledge">
      {files.map((f) => f.id).join(',')}
    </span>
  ),
}));

vi.mock('../Hero', () => ({ default: () => null }));

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

  const render = (queries: Query[], canAddToKnowledge = false) =>
    act(() => {
      root.render(
        <ConversationMessages
          handleQuestion={() => undefined}
          handleQuestionSubmission={() => undefined}
          queries={queries}
          status="idle"
          canAddToKnowledge={canAddToKnowledge}
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

  it('renders Retry like the other answer actions: 32px ghost pill, lucide glyph', () => {
    render([{ prompt: 'hi', error: 'boom' }]);
    const retry = container.querySelector<HTMLButtonElement>(
      'button[aria-label="conversation.retry"]',
    )!;
    expect(retry.dataset.variant).toBe('ghost-muted');
    expect(retry.dataset.size).toBe('icon-sm');
    expect(retry.querySelector('svg.lucide-rotate-ccw')).not.toBeNull();
  });
});
