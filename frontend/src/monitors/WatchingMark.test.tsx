import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import { sseEventReceived } from '../notifications/notificationsSlice';
import reducer from './monitorsSlice';
import WatchingMark from './WatchingMark';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('WatchingMark', () => {
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

  it('marks a conversation while it has an active monitor', () => {
    const store = configureStore({ reducer: { monitors: reducer } });
    act(() => {
      root.render(
        <Provider store={store}>
          <WatchingMark conversationId="c-1" />
        </Provider>,
      );
    });
    expect(container.querySelector('[data-testid="watching-mark"]')).toBeNull();
    act(() => {
      store.dispatch(
        sseEventReceived({
          type: 'monitor.updated',
          payload: {
            monitor_id: 'm',
            status: 'active',
            wakes_left: 1,
            last_checked_at: null,
            conversation_id: 'c-1',
          },
        }),
      );
    });
    const mark = container.querySelector('[data-testid="watching-mark"]');
    expect(mark?.getAttribute('aria-label')).toBe('monitors.watching');
  });
});
