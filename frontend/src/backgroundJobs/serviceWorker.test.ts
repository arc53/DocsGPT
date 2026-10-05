/**
 * `public/sw.js` run against a fake service-worker global: what a push
 * shows, and where a click goes.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

import SOURCE from '../../public/sw.js?raw';

const ORIGIN = 'https://app.example.com';

type Handler = (event: Record<string, unknown>) => void;
type Client = {
  url: string;
  focused: boolean;
  postMessage: ReturnType<typeof vi.fn>;
  focus: ReturnType<typeof vi.fn>;
};

function loadWorker(windows: Client[] = []) {
  const handlers: Record<string, Handler> = {};
  const self = {
    location: { origin: ORIGIN },
    addEventListener: (type: string, handler: Handler) => {
      handlers[type] = handler;
    },
    skipWaiting: vi.fn(),
    registration: { showNotification: vi.fn(async () => undefined) },
    clients: {
      claim: vi.fn(async () => undefined),
      matchAll: vi.fn(async () => windows),
      openWindow: vi.fn(async () => null),
    },
  };
  new Function('self', SOURCE)(self);
  return { handlers, self };
}

async function dispatch(handler: Handler, event: Record<string, unknown>) {
  let waited: Promise<unknown> = Promise.resolve();
  handler({
    ...event,
    waitUntil: (promise: Promise<unknown>) => {
      waited = promise;
    },
  });
  await waited;
}

const pushEvent = (data: unknown) => ({
  data: {
    json: () => (typeof data === 'string' ? JSON.parse(data) : data),
    text: () => String(data),
  },
});

const client = (url: string, focused = false): Client => ({
  url,
  focused,
  postMessage: vi.fn(),
  focus: vi.fn(async () => undefined),
});

describe('service worker', () => {
  beforeEach(() => vi.clearAllMocks());

  it('has no fetch handler: it never caches or intercepts', () => {
    const { handlers } = loadWorker();
    expect(Object.keys(handlers).sort()).toEqual([
      'activate',
      'install',
      'notificationclick',
      'push',
    ]);
  });

  it('shows the pushed notification', async () => {
    const { handlers, self } = loadWorker();
    await dispatch(
      handlers.push,
      pushEvent({
        title: 'Monitor matched',
        body: 'BTC below $50k: It is $49,800.',
        url: '/c/c1',
        tag: 'docsgpt:c1',
      }),
    );
    expect(self.registration.showNotification).toHaveBeenCalledWith(
      'Monitor matched',
      expect.objectContaining({
        body: 'BTC below $50k: It is $49,800.',
        tag: 'docsgpt:c1',
        data: { url: `${ORIGIN}/c/c1` },
      }),
    );
  });

  it('keeps a pushed link inside the app', async () => {
    const { handlers, self } = loadWorker();
    for (const url of ['https://evil.example.com/x', '//evil.example.com', 7]) {
      await dispatch(handlers.push, pushEvent({ title: 't', url }));
    }
    for (const call of self.registration.showNotification.mock.calls) {
      expect((call as unknown[])[1]).toMatchObject({
        data: { url: `${ORIGIN}/` },
      });
    }
  });

  it('copes with a payload that is not JSON', async () => {
    const { handlers, self } = loadWorker();
    await dispatch(handlers.push, {
      data: {
        json: () => {
          throw new Error('not json');
        },
        text: () => 'plain words',
      },
    });
    expect(self.registration.showNotification).toHaveBeenCalledWith(
      'DocsGPT',
      expect.objectContaining({ body: 'plain words' }),
    );
  });

  it('a click routes an open tab in place and focuses it', async () => {
    const other = client(`${ORIGIN}/settings`);
    const focused = client(`${ORIGIN}/c/x`, true);
    const { handlers, self } = loadWorker([
      client('https://elsewhere.example.com/'),
      other,
      focused,
    ]);
    const close = vi.fn();
    await dispatch(handlers.notificationclick, {
      notification: { close, data: { url: `${ORIGIN}/c/c1` } },
    });
    expect(close).toHaveBeenCalled();
    expect(focused.postMessage).toHaveBeenCalledWith({
      type: 'docsgpt:navigate',
      url: '/c/c1',
    });
    expect(focused.focus).toHaveBeenCalled();
    expect(other.postMessage).not.toHaveBeenCalled();
    expect(self.clients.openWindow).not.toHaveBeenCalled();
  });

  it('a click with no tab of the app opens one', async () => {
    const { handlers, self } = loadWorker([
      client('https://elsewhere.example.com/'),
    ]);
    await dispatch(handlers.notificationclick, {
      notification: { close: vi.fn(), data: { url: `${ORIGIN}/c/c1` } },
    });
    expect(self.clients.openWindow).toHaveBeenCalledWith(`${ORIGIN}/c/c1`);
  });

  it('a click on a notification without data opens the app root', async () => {
    const { handlers, self } = loadWorker();
    await dispatch(handlers.notificationclick, {
      notification: { close: vi.fn(), data: null },
    });
    expect(self.clients.openWindow).toHaveBeenCalledWith(`${ORIGIN}/`);
  });
});
