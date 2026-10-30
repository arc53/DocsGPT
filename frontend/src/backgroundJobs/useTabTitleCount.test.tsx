import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

import activityReducer, { loadActivityNow } from '../activity/activitySlice';
import backgroundReducer, {
  markConversationRead,
  markConversationUnread,
} from './backgroundSlice';
import { titleWithCount, useTabTitleCount } from './useTabTitleCount';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('titleWithCount', () => {
  it('prefixes the count, and drops it at zero', () => {
    expect(titleWithCount('DocsGPT', 2)).toBe('(2) DocsGPT');
    expect(titleWithCount('(2) DocsGPT', 3)).toBe('(3) DocsGPT');
    expect(titleWithCount('(3) DocsGPT', 0)).toBe('DocsGPT');
    expect(titleWithCount('DocsGPT', 0)).toBe('DocsGPT');
  });
});

describe('useTabTitleCount', () => {
  let container: HTMLDivElement;
  let root: Root;

  const makeStore = () =>
    configureStore({
      reducer: {
        activity: activityReducer,
        background: backgroundReducer,
        preference: (state: { token: string | null } = { token: 'tok' }) =>
          state,
      },
    });

  function Probe() {
    useTabTitleCount();
    return null;
  }

  beforeEach(() => {
    document.title = 'DocsGPT';
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    document.title = 'DocsGPT';
  });

  const render = async (store: ReturnType<typeof makeStore>) => {
    await act(async () => {
      root.render(
        <Provider store={store}>
          <Probe />
        </Provider>,
      );
    });
  };

  it('counts each chat that needs the user once: unread, failed or waiting for approval', async () => {
    const store = makeStore();
    store.dispatch(markConversationUnread('c1'));
    store.dispatch(markConversationUnread('c2'));
    store.dispatch(
      loadActivityNow.fulfilled(
        {
          running: [],
          needs_you: [],
          up_next: [],
          approval_conversations: ['c3'],
          failed_conversations: ['c2'],
          stats: { next_24h: 0, failed_24h: 1 },
        },
        'req',
      ),
    );
    await render(store);
    expect(document.title).toBe('(3) DocsGPT');
  });

  it('leaves out an unread mark whose chat the sidebar no longer lists', async () => {
    // Deleted in another tab, or never listed: no row the user could open
    // to clear it.
    const store = configureStore({
      reducer: {
        activity: activityReducer,
        background: backgroundReducer,
        preference: (
          state = {
            token: 'tok',
            conversations: {
              data: [{ id: 'c1', name: 'a', agent_id: null }],
              loading: false,
            },
          },
        ) => state,
      },
    });
    store.dispatch(markConversationUnread('c1'));
    store.dispatch(markConversationUnread('gone'));
    await render(store as unknown as ReturnType<typeof makeStore>);
    expect(document.title).toBe('(1) DocsGPT');
  });

  it('follows the marks as chats are read, and is plain with none left', async () => {
    const store = makeStore();
    store.dispatch(markConversationUnread('c1'));
    await render(store);
    expect(document.title).toBe('(1) DocsGPT');

    await act(async () => {
      store.dispatch(markConversationUnread('c2'));
    });
    expect(document.title).toBe('(2) DocsGPT');

    await act(async () => {
      store.dispatch({
        type: markConversationRead.pending.type,
        meta: { arg: 'c1' },
      });
      store.dispatch({
        type: markConversationRead.pending.type,
        meta: { arg: 'c2' },
      });
    });
    expect(document.title).toBe('DocsGPT');
  });

  it('puts the plain title back when unmounted', async () => {
    const store = makeStore();
    store.dispatch(markConversationUnread('c1'));
    await render(store);
    expect(document.title).toBe('(1) DocsGPT');
    await act(async () => root.unmount());
    root = createRoot(container);
    expect(document.title).toBe('DocsGPT');
  });
});
