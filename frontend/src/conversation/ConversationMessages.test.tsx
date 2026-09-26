import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('./ConversationBubble', () => ({
  default: ({
    message,
    retryBtn,
  }: {
    message?: string;
    retryBtn?: React.ReactNode;
  }) => (
    <div>
      {message}
      {retryBtn}
    </div>
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

  const render = (queries: Query[]) =>
    act(() => {
      root.render(
        <ConversationMessages
          handleQuestion={() => undefined}
          handleQuestionSubmission={() => undefined}
          queries={queries}
          status="idle"
        />,
      );
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
