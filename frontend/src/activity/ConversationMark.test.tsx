import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import ConversationMark from './ConversationMark';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

type Marks = {
  failed?: boolean;
  approval?: boolean;
  working?: boolean;
  unread?: boolean;
  watching?: boolean;
};

const store = (marks: Marks) =>
  configureStore({
    reducer: {
      activity: () => ({
        now: {
          running: marks.working
            ? [{ kind: 'chat', id: 'm', title: null, conversation_id: 'c1' }]
            : [],
          needs_you: [],
          up_next: [],
          approval_conversations: marks.approval ? ['c1'] : [],
          failed_conversations: marks.failed ? ['c1'] : [],
          stats: { next_24h: 0, failed_24h: 0 },
        },
        loading: false,
        error: false,
        live: {},
      }),
      background: () => ({ unread: marks.unread ? { c1: true } : {} }),
      monitors: () =>
        marks.watching
          ? {
              order: ['m1'],
              byId: { m1: { conversation_id: 'c1', status: 'active' } },
            }
          : { order: [], byId: {} },
    },
  });

describe('ConversationMark', () => {
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

  const render = (marks: Marks) => {
    act(() =>
      root.render(
        <Provider store={store(marks)}>
          <ConversationMark conversationId="c1" />
        </Provider>,
      ),
    );
    return container.querySelector<HTMLElement>(
      '[data-testid="conversation-mark"]',
    );
  };

  it('shows nothing for a quiet chat', () => {
    expect(render({})).toBeNull();
  });

  it.each([
    [{ failed: true, approval: true, working: true, watching: true }, 'failed'],
    [{ approval: true, working: true, unread: true }, 'needsYou'],
    [{ working: true, unread: true, watching: true }, 'working'],
    [{ unread: true, watching: true }, 'unread'],
    [{ watching: true }, 'watching'],
  ] as const)('shows the most urgent state (%o → %s)', (marks, expected) => {
    expect(render(marks)?.dataset.state).toBe(expected);
  });

  it('names every state in its label', () => {
    expect(
      render({ working: true, watching: true })?.getAttribute('aria-label'),
    ).toBe('activity.marks.working · activity.marks.watching');
  });

  it('folds unread into failed: the failed mark already says there is news', () => {
    expect(
      render({ failed: true, unread: true })?.getAttribute('aria-label'),
    ).toBe('activity.marks.failed');
  });

  it('draws watching as a hollow ring', () => {
    const dot = render({ watching: true })?.querySelector('span');
    expect(dot?.className).toContain('border-[1.5px]');
  });
});
