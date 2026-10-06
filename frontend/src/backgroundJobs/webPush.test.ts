import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const service = vi.hoisted(() => ({
  savePushSubscription: vi.fn(async () => undefined),
  forgetPushSubscriptionOnExit: vi.fn(),
}));
vi.mock('../api/services/backgroundService', () => ({ default: service }));

import {
  enablePush,
  ensurePushSubscription,
  forgetPushSubscription,
  FORGET_TIMEOUT_MS,
  loadPushChoice,
  PUSH_CHOICE_STORAGE_KEY,
  safeAppPath,
  savePushChoice,
  shouldOfferPush,
  showLocalNotification,
  urlBase64ToUint8Array,
} from './webPush';

// A P-256 public key: 65 bytes starting with 0x04, raw base64url.
const PUBLIC_KEY =
  'BEl62iUYgUivxIkv69yViEuiBIa-Ib9-SkvMeAtA3LFgDzkrxZJjSgSnfckjBJuBkr3qBUYIHBQFLXYp5Nksh8U';

type FakeSubscription = {
  endpoint: string;
  options: { applicationServerKey: ArrayBuffer | null };
  toJSON: () => unknown;
  unsubscribe: ReturnType<typeof vi.fn>;
};

function fakeSubscription(key: Uint8Array | null): FakeSubscription {
  return {
    endpoint: 'https://fcm.googleapis.com/fcm/send/abc',
    options: {
      applicationServerKey: key ? (key.slice().buffer as ArrayBuffer) : null,
    },
    toJSON: () => ({ endpoint: 'https://fcm.googleapis.com/fcm/send/abc' }),
    unsubscribe: vi.fn(async () => true),
  };
}

function installBrowser({
  permission = 'default' as NotificationPermission,
  existing = null as FakeSubscription | null,
  registered = true,
} = {}) {
  const created = fakeSubscription(urlBase64ToUint8Array(PUBLIC_KEY));
  const pushManager = {
    getSubscription: vi.fn(async () => existing),
    subscribe: vi.fn(async () => created),
  };
  const registration = {
    pushManager,
    showNotification: vi.fn(async () => undefined),
  };
  const serviceWorker = {
    register: vi.fn(async () => registration),
    ready: Promise.resolve(registration),
    getRegistration: vi.fn(async () => (registered ? registration : undefined)),
  };
  const Notification = {
    permission,
    requestPermission: vi.fn(async () => 'granted' as NotificationPermission),
  };
  vi.stubGlobal('Notification', Notification);
  Object.assign(window, { Notification, PushManager: class {} });
  Object.defineProperty(window, 'isSecureContext', {
    value: true,
    configurable: true,
  });
  Object.defineProperty(navigator, 'serviceWorker', {
    value: serviceWorker,
    configurable: true,
  });
  return { serviceWorker, registration, pushManager, Notification, created };
}

function removeBrowser() {
  vi.unstubAllGlobals();
  delete (window as unknown as Record<string, unknown>).Notification;
  delete (window as unknown as Record<string, unknown>).PushManager;
  delete (navigator as unknown as Record<string, unknown>).serviceWorker;
}

describe('webPush helpers', () => {
  beforeEach(() => {
    localStorage.clear();
    service.savePushSubscription.mockClear();
    service.forgetPushSubscriptionOnExit.mockClear();
  });
  afterEach(() => {
    removeBrowser();
    vi.useRealTimers();
  });

  it('decodes a raw base64url VAPID key', () => {
    const bytes = urlBase64ToUint8Array(PUBLIC_KEY);
    expect(bytes).toHaveLength(65);
    expect(bytes[0]).toBe(0x04);
  });

  it('keeps notification links inside the app', () => {
    expect(safeAppPath('/c/abc')).toBe('/c/abc');
    expect(safeAppPath('//evil.example.com/x')).toBeNull();
    expect(safeAppPath('https://evil.example.com')).toBeNull();
    expect(safeAppPath('javascript:alert(1)')).toBeNull();
    expect(safeAppPath(undefined)).toBeNull();
  });

  it('remembers the answer to the prompt', () => {
    expect(loadPushChoice()).toBeNull();
    savePushChoice('dismissed');
    expect(loadPushChoice()).toBe('dismissed');
    localStorage.setItem(PUSH_CHOICE_STORAGE_KEY, 'garbage');
    expect(loadPushChoice()).toBeNull();
  });

  describe('shouldOfferPush', () => {
    it('offers once: push on, supported, never asked', () => {
      installBrowser();
      expect(shouldOfferPush(true)).toBe(true);
    });

    it('not when the server has no push, or the user answered', () => {
      installBrowser();
      expect(shouldOfferPush(false)).toBe(false);
      expect(shouldOfferPush(undefined)).toBe(false);
      savePushChoice('dismissed');
      expect(shouldOfferPush(true)).toBe(false);
    });

    it('not when the browser already has an answer', () => {
      installBrowser({ permission: 'denied' });
      expect(shouldOfferPush(true)).toBe(false);
    });

    it('not when the browser cannot do push', () => {
      expect(shouldOfferPush(true)).toBe(false);
    });
  });

  describe('ensurePushSubscription', () => {
    it('does nothing without permission', async () => {
      const { serviceWorker } = installBrowser({ permission: 'default' });
      expect(await ensurePushSubscription(PUBLIC_KEY, 'tok')).toBe(false);
      expect(serviceWorker.register).not.toHaveBeenCalled();
    });

    it('registers the worker at the root, subscribes and saves', async () => {
      const { serviceWorker, pushManager } = installBrowser({
        permission: 'granted',
      });
      expect(await ensurePushSubscription(PUBLIC_KEY, 'tok')).toBe(true);
      expect(serviceWorker.register).toHaveBeenCalledWith('/sw.js', {
        scope: '/',
      });
      expect(pushManager.subscribe).toHaveBeenCalledWith(
        expect.objectContaining({ userVisibleOnly: true }),
      );
      expect(service.savePushSubscription).toHaveBeenCalledWith(
        { endpoint: 'https://fcm.googleapis.com/fcm/send/abc' },
        'tok',
      );
    });

    it('keeps a subscription made with the current key', async () => {
      const existing = fakeSubscription(urlBase64ToUint8Array(PUBLIC_KEY));
      const { pushManager } = installBrowser({
        permission: 'granted',
        existing,
      });
      await ensurePushSubscription(PUBLIC_KEY, 'tok');
      expect(existing.unsubscribe).not.toHaveBeenCalled();
      expect(pushManager.subscribe).not.toHaveBeenCalled();
      expect(service.savePushSubscription).toHaveBeenCalledTimes(1);
    });

    it('replaces a subscription made with a rotated key', async () => {
      const existing = fakeSubscription(new Uint8Array([4, 1, 2, 3]));
      const { pushManager } = installBrowser({
        permission: 'granted',
        existing,
      });
      await ensurePushSubscription(PUBLIC_KEY, 'tok');
      expect(existing.unsubscribe).toHaveBeenCalled();
      expect(pushManager.subscribe).toHaveBeenCalled();
    });
  });

  it('asks for permission only when enabling, then subscribes', async () => {
    const browser = installBrowser();
    browser.Notification.requestPermission.mockImplementation(async () => {
      browser.Notification.permission = 'granted';
      return 'granted';
    });
    expect(await enablePush(PUBLIC_KEY, 'tok')).toBe('granted');
    expect(browser.pushManager.subscribe).toHaveBeenCalled();
  });

  it('does not subscribe when the user declines', async () => {
    const browser = installBrowser();
    browser.Notification.requestPermission.mockResolvedValue('denied');
    expect(await enablePush(PUBLIC_KEY, 'tok')).toBe('denied');
    expect(browser.pushManager.subscribe).not.toHaveBeenCalled();
  });

  it('shows a local notification through the registration', async () => {
    const { registration } = installBrowser({ permission: 'granted' });
    expect(
      await showLocalNotification({
        title: 'Monitor matched',
        body: 'BTC',
        url: '/c/1',
        tag: 'docsgpt:1',
      }),
    ).toBe(true);
    expect(registration.showNotification).toHaveBeenCalledWith(
      'Monitor matched',
      expect.objectContaining({ tag: 'docsgpt:1', data: { url: '/c/1' } }),
    );
  });

  it('shows nothing without a registration', async () => {
    installBrowser({ permission: 'granted', registered: false });
    expect(
      await showLocalNotification({ title: 'x', url: '/', tag: 't' }),
    ).toBe(false);
  });

  describe('forgetPushSubscription', () => {
    it('tells the server and unsubscribes the browser', async () => {
      const existing = fakeSubscription(urlBase64ToUint8Array(PUBLIC_KEY));
      installBrowser({ permission: 'granted', existing });
      await forgetPushSubscription('tok');
      expect(service.forgetPushSubscriptionOnExit).toHaveBeenCalledWith(
        existing.endpoint,
        'tok',
      );
      expect(existing.unsubscribe).toHaveBeenCalled();
    });

    it('is a no-op without a subscription or push support', async () => {
      installBrowser({ permission: 'granted' });
      await forgetPushSubscription('tok');
      removeBrowser();
      await forgetPushSubscription('tok');
      expect(service.forgetPushSubscriptionOnExit).not.toHaveBeenCalled();
    });

    it('never holds sign-out up for long', async () => {
      vi.useFakeTimers();
      const browser = installBrowser({ permission: 'granted' });
      browser.serviceWorker.getRegistration.mockImplementation(
        () => new Promise(() => undefined),
      );
      const done = vi.fn();
      void forgetPushSubscription('tok').then(done);
      await vi.advanceTimersByTimeAsync(FORGET_TIMEOUT_MS + 10);
      expect(done).toHaveBeenCalled();
    });

    it('swallows failures', async () => {
      const browser = installBrowser({ permission: 'granted' });
      browser.serviceWorker.getRegistration.mockRejectedValue(new Error('x'));
      await expect(forgetPushSubscription('tok')).resolves.toBeUndefined();
    });
  });
});
