import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('../api/services/backgroundService', () => ({ default: {} }));

import backgroundReducer, {
  markConversationRead,
  markConversationUnread,
} from './backgroundSlice';
import UnreadDot from './UnreadDot';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('UnreadDot', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  it('shows the unread dot only for an unread conversation', async () => {
    const store = configureStore({
      reducer: {
        background: backgroundReducer,
        preference: (state: { token: string | null } = { token: null }) =>
          state,
      },
    });
    await act(async () => {
      root.render(
        <Provider store={store}>
          <UnreadDot conversationId="c1" />
          <UnreadDot conversationId="c2" />
        </Provider>,
      );
    });
    expect(
      container.querySelectorAll('[data-testid="unread-dot"]'),
    ).toHaveLength(0);
    await act(async () => {
      store.dispatch(markConversationUnread('c1'));
    });
    const dots = container.querySelectorAll('[data-testid="unread-dot"]');
    expect(dots).toHaveLength(1);
    expect(dots[0].getAttribute('aria-label')).toBe('backgroundJobs.unread');
  });

  it('goes away when the conversation is read', async () => {
    const store = configureStore({
      reducer: {
        background: backgroundReducer,
        preference: (state: { token: string | null } = { token: null }) =>
          state,
      },
    });
    store.dispatch(markConversationUnread('c1'));
    await act(async () => {
      root.render(
        <Provider store={store}>
          <UnreadDot conversationId="c1" />
        </Provider>,
      );
    });
    expect(
      container.querySelector('[data-testid="unread-dot"]'),
    ).not.toBeNull();
    await act(async () => {
      void store.dispatch(markConversationRead('c1'));
    });
    expect(container.querySelector('[data-testid="unread-dot"]')).toBeNull();
  });
});
