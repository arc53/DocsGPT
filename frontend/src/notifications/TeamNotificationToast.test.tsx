import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts && 'team' in opts ? `${key}:${opts.team}` : key,
  }),
}));

import notificationsReducer, { sseEventReceived } from './notificationsSlice';
import TeamNotificationToast from './TeamNotificationToast';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const makeStore = () =>
  configureStore({ reducer: { notifications: notificationsReducer } });

describe('TeamNotificationToast', () => {
  let container: HTMLDivElement;
  let root: Root;
  let store: ReturnType<typeof makeStore>;

  beforeEach(() => {
    localStorage.clear();
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

  const renderToast = async () => {
    await act(async () => {
      root.render(
        <Provider store={store}>
          <TeamNotificationToast />
        </Provider>,
      );
    });
  };

  const addMember = (id: string) =>
    store.dispatch(
      sseEventReceived({
        id,
        type: 'team.member_added',
        payload: { team_name: 'Ops', role: 'team_member' },
      }),
    );

  it('renders nothing without team events', async () => {
    await renderToast();
    expect(container.innerHTML).toBe('');
  });

  it('renders title and body on the shared toast primitive', async () => {
    addMember('e1');
    await renderToast();
    // Cards only: App.tsx owns the one shared ToastViewport (the live
    // region), so the component renders neither a rail nor a role.
    expect(container.querySelector('[data-slot="toast-viewport"]')).toBeNull();
    expect(container.querySelector('[role="status"]')).toBeNull();
    const toast = container.querySelector('[data-slot="toast"]');
    expect(toast).not.toBeNull();
    expect(toast?.parentElement).toBe(container);
    const title = container.querySelector('[data-slot="toast-title"]');
    expect(title?.textContent).toBe('notifications.memberAddedTitle');
    // A long localized title wraps rather than truncating.
    expect(title?.className).not.toContain('truncate');
    const body = container.querySelector('[data-slot="toast-message"]');
    expect(body?.textContent).toBe('notifications.memberAddedBody:Ops');
    expect(body?.className).toContain('text-sm');
  });

  it('dismisses on the close button', async () => {
    addMember('e1');
    await renderToast();
    const close = container.querySelector(
      'button[aria-label="notifications.dismiss"]',
    ) as HTMLButtonElement;
    expect(close).not.toBeNull();
    await act(async () => close.click());
    expect(container.innerHTML).toBe('');
    expect(
      store
        .getState()
        .notifications.dismissedShareNotifications.map((e) => e.id),
    ).toContain('e1');
  });

  it('auto-dismisses after its own timer', async () => {
    vi.useFakeTimers();
    addMember('e1');
    await renderToast();
    expect(container.querySelector('[data-slot="toast"]')).not.toBeNull();
    await act(async () => {
      vi.advanceTimersByTime(8000);
    });
    expect(container.innerHTML).toBe('');
  });
});
