import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter, useNavigate } from 'react-router-dom';

const service = vi.hoisted(() => ({ reportPresence: vi.fn() }));
vi.mock('../api/services/backgroundService', () => ({ default: service }));

import {
  PRESENCE_HEARTBEAT_MS,
  shownConversationId,
  TAB_ID,
  usePresence,
} from './usePresence';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

function setVisibility(state: 'visible' | 'hidden') {
  Object.defineProperty(document, 'visibilityState', {
    value: state,
    configurable: true,
  });
}

let navigateTo: (path: string) => void = () => undefined;
function Probe() {
  usePresence();
  navigateTo = useNavigate();
  return null;
}

describe('shownConversationId', () => {
  it('reads the route, and the streaming chat on a new-chat route', () => {
    expect(shownConversationId('/c/abc', null, false)).toBe('abc');
    expect(shownConversationId('/', 'c9', true)).toBe('c9');
    expect(shownConversationId('/c/new', 'c9', true)).toBe('c9');
    expect(shownConversationId('/agents/a1/c/new', 'c9', true)).toBe('c9');
    expect(shownConversationId('/', 'c9', false)).toBeNull();
    expect(shownConversationId('/settings', 'c9', true)).toBeNull();
  });
});

describe('usePresence', () => {
  let container: HTMLDivElement;
  let root: Root;

  const makeStore = (token: string | null = 'tok') =>
    configureStore({
      reducer: {
        preference: (state = { token }) => state,
        conversation: (state = { conversationId: null, status: 'idle' }) =>
          state,
      },
    });

  beforeEach(() => {
    vi.useFakeTimers();
    service.reportPresence.mockReset();
    setVisibility('visible');
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.useRealTimers();
    setVisibility('visible');
  });

  const render = async (path = '/c/c1', store = makeStore()) => {
    await act(async () => {
      root.render(
        <Provider store={store}>
          <MemoryRouter initialEntries={[path]}>
            <Probe />
          </MemoryRouter>
        </Provider>,
      );
    });
  };

  const last = () => service.reportPresence.mock.calls.at(-1);

  it('reports the shown conversation at once', async () => {
    await render();
    expect(last()).toEqual([
      { tab_id: TAB_ID, conversation_id: 'c1', visible: true },
      'tok',
    ]);
  });

  it('reports again when the route changes', async () => {
    await render();
    await act(async () => navigateTo('/settings'));
    expect(last()?.[0]).toMatchObject({ conversation_id: null, visible: true });
  });

  it('reports on a visibility change', async () => {
    await render();
    setVisibility('hidden');
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'));
    });
    expect(last()?.[0]).toMatchObject({
      conversation_id: 'c1',
      visible: false,
    });
  });

  it('heartbeats while visible, not while hidden', async () => {
    await render();
    const before = service.reportPresence.mock.calls.length;
    await act(async () => {
      vi.advanceTimersByTime(PRESENCE_HEARTBEAT_MS * 2 + 10);
    });
    expect(service.reportPresence.mock.calls.length).toBe(before + 2);

    setVisibility('hidden');
    const hidden = service.reportPresence.mock.calls.length;
    await act(async () => {
      vi.advanceTimersByTime(PRESENCE_HEARTBEAT_MS * 3);
    });
    expect(service.reportPresence.mock.calls.length).toBe(hidden);
  });

  it('says closing when the page goes away, and is back after a bfcache restore', async () => {
    await render();
    await act(async () => {
      window.dispatchEvent(new Event('pagehide'));
    });
    expect(last()?.[0]).toMatchObject({ closing: true });
    const restored = new Event('pageshow') as PageTransitionEvent;
    Object.defineProperty(restored, 'persisted', { value: true });
    await act(async () => {
      window.dispatchEvent(restored);
    });
    expect(last()?.[0]).not.toHaveProperty('closing');
  });

  it('stops reporting when unmounted', async () => {
    await render();
    await act(async () => root.unmount());
    root = createRoot(container);
    const count = service.reportPresence.mock.calls.length;
    await act(async () => {
      vi.advanceTimersByTime(PRESENCE_HEARTBEAT_MS * 3);
      document.dispatchEvent(new Event('visibilitychange'));
    });
    expect(service.reportPresence.mock.calls.length).toBe(count);
  });
});
