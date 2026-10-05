import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const service = vi.hoisted(() => ({
  getPushConfig: vi.fn(),
  markConversationRead: vi.fn(async () => undefined),
  reportPresence: vi.fn(),
}));
vi.mock('../api/services/backgroundService', () => ({ default: service }));

const push = vi.hoisted(() => ({
  supported: true,
  permission: 'granted' as NotificationPermission | null,
  ensurePushSubscription: vi.fn(async () => true),
}));
vi.mock('./webPush', async () => {
  const actual = await vi.importActual<typeof import('./webPush')>('./webPush');
  return {
    ...actual,
    isPushSupported: () => push.supported,
    notificationPermission: () => push.permission,
    ensurePushSubscription: push.ensurePushSubscription,
  };
});

import notificationsReducer from '../notifications/notificationsSlice';
import BackgroundNotifications from './BackgroundNotifications';
import backgroundReducer, {
  markConversationUnread,
  selectIsUnread,
} from './backgroundSlice';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

function Location() {
  return <div data-testid="location">{useLocation().pathname}</div>;
}

describe('BackgroundNotifications', () => {
  let container: HTMLDivElement;
  let root: Root;
  let swTarget: EventTarget;

  const makeStore = () =>
    configureStore({
      reducer: {
        background: backgroundReducer,
        notifications: notificationsReducer,
        actionToast: (state = { current: null, nextId: 1 }) => state,
        preference: (state = { token: 'tok' }) => state,
        conversation: (state = { conversationId: null, status: 'idle' }) =>
          state,
      },
    });

  beforeEach(() => {
    Object.values(service).forEach((fn) => fn.mockReset());
    push.ensurePushSubscription.mockClear();
    push.supported = true;
    push.permission = 'granted';
    service.getPushConfig.mockResolvedValue({ enabled: true, public_key: 'K' });
    swTarget = new EventTarget();
    Object.defineProperty(navigator, 'serviceWorker', {
      value: swTarget,
      configurable: true,
    });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    delete (navigator as unknown as Record<string, unknown>).serviceWorker;
  });

  const renderAt = async (path: string, store = makeStore()) => {
    await act(async () => {
      root.render(
        <Provider store={store}>
          <MemoryRouter initialEntries={[path]}>
            <Routes>
              <Route
                path="*"
                element={
                  <>
                    <BackgroundNotifications />
                    <Location />
                  </>
                }
              />
            </Routes>
          </MemoryRouter>
        </Provider>,
      );
    });
    return store;
  };

  it('reports presence and reads the push config, never asking for permission', async () => {
    await renderAt('/c/c1');
    expect(service.reportPresence).toHaveBeenCalled();
    expect(service.getPushConfig).toHaveBeenCalledWith('tok');
    expect(
      container.querySelector('[data-testid="push-permission-prompt"]'),
    ).toBeNull();
  });

  it('keeps an allowed browser subscribed', async () => {
    await renderAt('/');
    expect(push.ensurePushSubscription).toHaveBeenCalledWith('K', 'tok');
  });

  it('does not subscribe a browser that has not allowed it', async () => {
    push.permission = 'default';
    await renderAt('/');
    expect(push.ensurePushSubscription).not.toHaveBeenCalled();
  });

  it('clears the unread mark of the conversation on screen', async () => {
    const store = makeStore();
    store.dispatch(markConversationUnread('c1'));
    store.dispatch(markConversationUnread('c2'));
    await renderAt('/c/c1', store);
    expect(selectIsUnread('c1')(store.getState())).toBe(false);
    expect(selectIsUnread('c2')(store.getState())).toBe(true);
    expect(service.markConversationRead).toHaveBeenCalledWith('c1', 'tok');
  });

  it('routes in place when a clicked notification asks', async () => {
    await renderAt('/');
    await act(async () => {
      swTarget.dispatchEvent(
        new MessageEvent('message', {
          data: { type: 'docsgpt:navigate', url: '/c/c7' },
        }),
      );
    });
    expect(
      container.querySelector('[data-testid="location"]')?.textContent,
    ).toBe('/c/c7');
  });

  it('ignores a navigate message to outside the app', async () => {
    await renderAt('/');
    await act(async () => {
      swTarget.dispatchEvent(
        new MessageEvent('message', {
          data: { type: 'docsgpt:navigate', url: 'https://evil.example.com' },
        }),
      );
    });
    expect(
      container.querySelector('[data-testid="location"]')?.textContent,
    ).toBe('/');
  });
});
