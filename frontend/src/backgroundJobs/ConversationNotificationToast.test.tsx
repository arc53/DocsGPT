import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const service = vi.hoisted(() => ({
  markConversationRead: vi.fn(async () => undefined),
}));
vi.mock('../api/services/backgroundService', () => ({ default: service }));

import notificationsReducer, {
  sseEventReceived,
  type SSEEvent,
} from '../notifications/notificationsSlice';
import backgroundReducer, {
  markConversationUnread,
  selectIsUnread,
} from './backgroundSlice';
import ConversationNotificationToast, {
  NOTIFICATION_DISMISS_MS,
  NOTIFICATION_MAX_AGE_MS,
} from './ConversationNotificationToast';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

function Location() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

const notification = (
  id: string,
  payload: Record<string, unknown> = {},
  ts = new Date().toISOString(),
): SSEEvent => ({
  id,
  ts,
  type: 'notification.created',
  payload: {
    kind: 'job',
    title: 'run_code finished',
    body: 'It printed 42.',
    url: '/c/c1',
    conversation_id: 'c1',
    ...payload,
  },
});

describe('ConversationNotificationToast', () => {
  let container: HTMLDivElement;
  let root: Root;

  const makeStore = () =>
    configureStore({
      reducer: {
        background: backgroundReducer,
        notifications: notificationsReducer,
        preference: (state: { token: string | null } = { token: 'tok' }) =>
          state,
      },
    });
  let store: ReturnType<typeof makeStore>;

  beforeEach(() => {
    localStorage.clear();
    service.markConversationRead.mockClear();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    store = makeStore();
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.useRealTimers();
  });

  const renderAt = async (path: string) => {
    await act(async () => {
      root.render(
        <Provider store={store}>
          <MemoryRouter initialEntries={[path]}>
            <Routes>
              <Route
                path="*"
                element={
                  <>
                    <ConversationNotificationToast />
                    <Location />
                  </>
                }
              />
            </Routes>
          </MemoryRouter>
        </Provider>,
      );
    });
  };

  const cards = () =>
    container.querySelectorAll('[data-testid="conversation-notification"]');
  const buttonByText = (text: string) =>
    Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === text,
    ) as HTMLButtonElement | undefined;

  it('shows the kind heading, the title, the preview and Open', async () => {
    store.dispatch(sseEventReceived(notification('n1')));
    await renderAt('/');
    expect(cards()).toHaveLength(1);
    expect(
      container.querySelector('[data-slot="toast-title"]')?.textContent,
    ).toBe('backgroundJobs.notify.title.job');
    expect(container.textContent).toContain('run_code finished');
    expect(container.textContent).toContain('It printed 42.');
    expect(buttonByText('backgroundJobs.notify.open')).toBeDefined();
  });

  it('drops the job id from the title', async () => {
    store.dispatch(
      sseEventReceived(
        notification('n1', {
          title: 'run_code finished (job 5f0c2a8e-1b7d-4e6a-9c3f-2d8b7a6e5f41)',
        }),
      ),
    );
    await renderAt('/');
    expect(container.textContent).toContain('run_code finished');
    expect(container.textContent).not.toContain('5f0c2a8e');
  });

  it('reads an unknown kind generically', async () => {
    store.dispatch(sseEventReceived(notification('n1', { kind: 'custom' })));
    await renderAt('/');
    expect(
      container.querySelector('[data-slot="toast-title"]')?.textContent,
    ).toBe('backgroundJobs.notify.title.default');
  });

  it('Open goes to the conversation and clears its unread mark', async () => {
    store.dispatch(markConversationUnread('c1'));
    store.dispatch(sseEventReceived(notification('n1')));
    await renderAt('/');
    await act(async () => buttonByText('backgroundJobs.notify.open')!.click());
    expect(
      container.querySelector('[data-testid="location"]')?.textContent,
    ).toBe('/c/c1');
    expect(selectIsUnread('c1')(store.getState())).toBe(false);
    expect(service.markConversationRead).toHaveBeenCalledWith('c1', 'tok');
    expect(cards()).toHaveLength(0);
  });

  it('Open never leaves the app: an outside url falls back to the conversation', async () => {
    store.dispatch(
      sseEventReceived(notification('n1', { url: 'https://evil.example.com' })),
    );
    await renderAt('/');
    await act(async () => buttonByText('backgroundJobs.notify.open')!.click());
    expect(
      container.querySelector('[data-testid="location"]')?.textContent,
    ).toBe('/c/c1');
  });

  it('is skipped for the conversation on screen', async () => {
    store.dispatch(sseEventReceived(notification('n1')));
    await renderAt('/c/c1');
    expect(cards()).toHaveLength(0);
  });

  it('a dismissed card stays dismissed after a reload replays it', async () => {
    store.dispatch(sseEventReceived(notification('n1')));
    await renderAt('/');
    await act(async () =>
      (
        container.querySelector(
          'button[aria-label="notifications.dismiss"]',
        ) as HTMLButtonElement
      ).click(),
    );
    expect(cards()).toHaveLength(0);

    await act(async () => root.unmount());
    root = createRoot(container);
    store = makeStore();
    store.dispatch(sseEventReceived(notification('n1')));
    await renderAt('/');
    expect(cards()).toHaveLength(0);
  });

  it('closes itself after a while, and skips old replayed ones', async () => {
    vi.useFakeTimers();
    store.dispatch(
      sseEventReceived(
        notification(
          'old',
          {},
          new Date(Date.now() - NOTIFICATION_MAX_AGE_MS - 1000).toISOString(),
        ),
      ),
    );
    store.dispatch(sseEventReceived(notification('n1')));
    await renderAt('/');
    expect(cards()).toHaveLength(1);
    await act(async () => {
      vi.advanceTimersByTime(NOTIFICATION_DISMISS_MS + 10);
    });
    expect(cards()).toHaveLength(0);
  });

  it('shows at most three at once', async () => {
    for (const id of ['a', 'b', 'c', 'd']) {
      store.dispatch(
        sseEventReceived(notification(id, { conversation_id: `c-${id}` })),
      );
    }
    await renderAt('/');
    expect(cards()).toHaveLength(3);
  });
});
