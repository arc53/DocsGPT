import { configureStore } from '@reduxjs/toolkit';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const push = vi.hoisted(() => ({
  offer: true,
  showLocalNotification: vi.fn(async () => true),
}));
vi.mock('./webPush', async () => {
  const actual = await vi.importActual<typeof import('./webPush')>('./webPush');
  return {
    ...actual,
    shouldOfferPush: (enabled: boolean | undefined) =>
      Boolean(enabled) && push.offer,
    showLocalNotification: push.showLocalNotification,
  };
});
vi.mock('../api/services/backgroundService', () => ({ default: {} }));

import {
  sseEventReceived,
  type SSEEvent,
} from '../notifications/notificationsSlice';
import {
  backgroundListenerMiddleware,
  conversationIdFromPath,
  FRESH_EVENT_MS,
  isFreshEvent,
} from './backgroundListener';
import backgroundReducer, {
  fetchPushConfig,
  selectIsUnread,
  selectPushPromptOpen,
} from './backgroundSlice';

const flush = () => new Promise((r) => setTimeout(r, 0));

const makeStore = (pushEnabled = true) => {
  const store = configureStore({
    reducer: { background: backgroundReducer },
    middleware: (getDefault) =>
      getDefault().concat(backgroundListenerMiddleware.middleware),
  });
  store.dispatch({
    type: fetchPushConfig.fulfilled.type,
    payload: { enabled: pushEnabled, public_key: pushEnabled ? 'K' : null },
  });
  return store;
};

const now = () => new Date().toISOString();

const notification = (overrides: Partial<SSEEvent> = {}): SSEEvent => ({
  id: 'n1',
  ts: now(),
  type: 'notification.created',
  payload: {
    kind: 'monitor',
    title: 'BTC below $50k',
    body: 'It is $49,800.',
    url: '/c/c1',
    conversation_id: 'c1',
  },
  ...overrides,
});

function setVisibility(state: 'visible' | 'hidden') {
  Object.defineProperty(document, 'visibilityState', {
    value: state,
    configurable: true,
  });
}

describe('conversationIdFromPath', () => {
  it('reads the conversation of a chat route', () => {
    expect(conversationIdFromPath('/c/abc')).toBe('abc');
    expect(conversationIdFromPath('/c/abc/')).toBe('abc');
    expect(conversationIdFromPath('/agents/a1/c/abc')).toBe('abc');
  });

  it('is null elsewhere and for a new chat', () => {
    expect(conversationIdFromPath('/')).toBeNull();
    expect(conversationIdFromPath('/c/new')).toBeNull();
    expect(conversationIdFromPath('/settings')).toBeNull();
    expect(conversationIdFromPath('/c/abc/extra')).toBeNull();
  });
});

describe('isFreshEvent', () => {
  it('a replayed backlog event is not fresh', () => {
    const at = Date.parse('2026-10-06T10:00:00Z');
    expect(
      isFreshEvent({ type: 'x', ts: '2026-10-06T10:00:00Z' }, at + 1000),
    ).toBe(true);
    expect(
      isFreshEvent(
        { type: 'x', ts: '2026-10-06T10:00:00Z' },
        at + FRESH_EVENT_MS + 1,
      ),
    ).toBe(false);
    expect(isFreshEvent({ type: 'x' })).toBe(true);
  });
});

describe('background listener', () => {
  beforeEach(() => {
    push.offer = true;
    push.showLocalNotification.mockClear();
    setVisibility('visible');
    window.history.replaceState({}, '', '/');
  });
  afterEach(() => {
    setVisibility('visible');
    window.history.replaceState({}, '', '/');
  });

  it('marks the conversation of a notification unread', async () => {
    const store = makeStore();
    store.dispatch(sseEventReceived(notification()));
    await flush();
    expect(selectIsUnread('c1')(store.getState())).toBe(true);
  });

  it('not the conversation this visible tab shows', async () => {
    window.history.replaceState({}, '', '/c/c1');
    const store = makeStore();
    store.dispatch(sseEventReceived(notification()));
    await flush();
    expect(selectIsUnread('c1')(store.getState())).toBe(false);
  });

  it('falls back to the event scope for the conversation', async () => {
    const store = makeStore();
    store.dispatch(
      sseEventReceived(
        notification({
          payload: { kind: 'job', title: 't' },
          scope: { kind: 'conversation', id: 'c9' },
        }),
      ),
    );
    await flush();
    expect(selectIsUnread('c9')(store.getState())).toBe(true);
  });

  it('a hidden tab shows a system notification, worded by kind', async () => {
    setVisibility('hidden');
    const store = makeStore();
    store.dispatch(sseEventReceived(notification()));
    await flush();
    expect(push.showLocalNotification).toHaveBeenCalledWith({
      title: 'backgroundJobs.notify.title.monitor',
      body: 'BTC below $50k: It is $49,800.',
      url: '/c/c1',
      tag: 'docsgpt:c1',
    });
  });

  it('a visible tab leaves it to the toast; a stale event shows nothing', async () => {
    const store = makeStore();
    store.dispatch(sseEventReceived(notification()));
    setVisibility('hidden');
    store.dispatch(
      sseEventReceived(notification({ id: 'n2', ts: '2020-01-01T00:00:00Z' })),
    );
    await flush();
    expect(push.showLocalNotification).not.toHaveBeenCalled();
  });

  it('never routes a system notification off the app', async () => {
    setVisibility('hidden');
    const store = makeStore();
    store.dispatch(
      sseEventReceived(
        notification({
          payload: { kind: 'job', title: 't', url: 'https://evil.example.com' },
        }),
      ),
    );
    await flush();
    expect(push.showLocalNotification).toHaveBeenCalledWith(
      expect.objectContaining({ url: '/' }),
    );
  });

  describe('the push prompt', () => {
    it('opens when a job goes to the background', async () => {
      const store = makeStore();
      store.dispatch(
        sseEventReceived({
          id: 'e1',
          ts: now(),
          type: 'job.updated',
          payload: { job_id: 'j1', status: 'working' },
        }),
      );
      await flush();
      expect(selectPushPromptOpen(store.getState())).toBe(true);
    });

    it('opens on a monitor update and on a notification', async () => {
      const a = makeStore();
      a.dispatch(
        sseEventReceived({ id: 'm', ts: now(), type: 'monitor.updated' }),
      );
      await flush();
      expect(selectPushPromptOpen(a.getState())).toBe(true);
      const b = makeStore();
      b.dispatch(sseEventReceived(notification()));
      await flush();
      expect(selectPushPromptOpen(b.getState())).toBe(true);
    });

    it('not for a finished job, replayed backlog, or other events', async () => {
      const store = makeStore();
      store.dispatch(
        sseEventReceived({
          id: 'e1',
          ts: now(),
          type: 'job.updated',
          payload: { job_id: 'j1', status: 'completed' },
        }),
      );
      store.dispatch(
        sseEventReceived({
          id: 'e2',
          ts: '2020-01-01T00:00:00Z',
          type: 'job.updated',
          payload: { job_id: 'j2', status: 'working' },
        }),
      );
      store.dispatch(sseEventReceived({ id: 'e3', ts: now(), type: 'other' }));
      await flush();
      expect(selectPushPromptOpen(store.getState())).toBe(false);
    });

    it('not when push is off on the server or the user already answered', async () => {
      const off = makeStore(false);
      off.dispatch(sseEventReceived(notification()));
      await flush();
      expect(selectPushPromptOpen(off.getState())).toBe(false);
      push.offer = false;
      const answered = makeStore();
      answered.dispatch(sseEventReceived(notification()));
      await flush();
      expect(selectPushPromptOpen(answered.getState())).toBe(false);
    });
  });
});
