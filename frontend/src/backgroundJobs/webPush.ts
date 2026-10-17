import backgroundService from '../api/services/backgroundService';

/**
 * Browser side of Web Push: the service worker (`public/sw.js`, served at
 * `/sw.js` by Vite and by the API's static UI), the push subscription, and
 * the user's answer to the in-context prompt.
 *
 * Permission is never asked on page load: only from the prompt's Enable
 * button, which a background job (or a monitor) opens the first time.
 */

export const SERVICE_WORKER_URL = '/sw.js';

/** The user's answer to the prompt, kept per browser. */
export const PUSH_CHOICE_STORAGE_KEY = 'docsgpt:pushPromptChoice';

export type PushChoice = 'enabled' | 'dismissed';

/** Message the service worker posts to a tab when a notification is clicked. */
export const NAVIGATE_MESSAGE = 'docsgpt:navigate';

export function isPushSupported(): boolean {
  return (
    typeof window !== 'undefined' &&
    'Notification' in window &&
    'PushManager' in window &&
    typeof navigator !== 'undefined' &&
    'serviceWorker' in navigator &&
    window.isSecureContext !== false
  );
}

export function notificationPermission(): NotificationPermission | null {
  if (typeof window === 'undefined' || !('Notification' in window)) return null;
  return window.Notification.permission;
}

export function loadPushChoice(): PushChoice | null {
  try {
    const value = localStorage.getItem(PUSH_CHOICE_STORAGE_KEY);
    return value === 'enabled' || value === 'dismissed' ? value : null;
  } catch {
    return null;
  }
}

export function savePushChoice(choice: PushChoice): void {
  try {
    localStorage.setItem(PUSH_CHOICE_STORAGE_KEY, choice);
  } catch {
    // Private mode: the prompt may come back next session; nothing breaks.
  }
}

/**
 * Whether to offer the prompt: the server has push, the browser can do it,
 * the user has neither answered here nor been asked by the browser.
 */
export function shouldOfferPush(pushEnabled: boolean | undefined): boolean {
  return (
    Boolean(pushEnabled) &&
    isPushSupported() &&
    notificationPermission() === 'default' &&
    loadPushChoice() === null
  );
}

/** A raw base64url key as the `applicationServerKey` byte array. */
export function urlBase64ToUint8Array(value: string): Uint8Array {
  const padded = value + '='.repeat((4 - (value.length % 4)) % 4);
  const base64 = padded.replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(base64);
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i);
  return bytes;
}

function sameKey(a: ArrayBuffer | null | undefined, b: Uint8Array): boolean {
  if (!a) return false;
  const left = new Uint8Array(a);
  return left.length === b.length && left.every((byte, i) => byte === b[i]);
}

export async function registerServiceWorker(): Promise<ServiceWorkerRegistration> {
  await navigator.serviceWorker.register(SERVICE_WORKER_URL, { scope: '/' });
  return navigator.serviceWorker.ready;
}

/**
 * Make sure this browser is subscribed with the server's current key and the
 * server knows it for the signed-in user. A subscription made with an old
 * key (the operator rotated it) is replaced. Saving it again on every visit
 * also moves a shared browser's subscription to whoever is signed in.
 *
 * @returns false when push can't be set up here.
 */
export async function ensurePushSubscription(
  publicKey: string,
  token: string | null,
): Promise<boolean> {
  if (!isPushSupported() || notificationPermission() !== 'granted') {
    return false;
  }
  const registration = await registerServiceWorker();
  const key = urlBase64ToUint8Array(publicKey);
  let subscription = await registration.pushManager.getSubscription();
  if (
    subscription &&
    !sameKey(subscription.options?.applicationServerKey, key)
  ) {
    await subscription.unsubscribe();
    subscription = null;
  }
  if (!subscription) {
    subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: key as BufferSource,
    });
  }
  await backgroundService.savePushSubscription(subscription.toJSON(), token);
  return true;
}

/**
 * Ask for permission (from a click) and subscribe.
 *
 * @returns the permission the user gave.
 */
export async function enablePush(
  publicKey: string,
  token: string | null,
): Promise<NotificationPermission> {
  const permission = await window.Notification.requestPermission();
  if (permission === 'granted') {
    await ensurePushSubscription(publicKey, token);
  }
  return permission;
}

/**
 * Show a notification from this tab (it is open but hidden, so the server
 * sent a toast rather than a push). The tag replaces an earlier one for the
 * same conversation, so several hidden tabs show it once.
 */
export async function showLocalNotification(notification: {
  title: string;
  body?: string;
  url: string;
  tag: string;
}): Promise<boolean> {
  if (!isPushSupported() || notificationPermission() !== 'granted') {
    return false;
  }
  const registration = await navigator.serviceWorker.getRegistration('/');
  if (!registration) return false;
  await registration.showNotification(notification.title, {
    body: notification.body,
    tag: notification.tag,
    data: { url: notification.url },
    icon: '/favicon-96x96.png',
  });
  return true;
}

/** The longest sign-out waits for the subscription to be forgotten. */
export const FORGET_TIMEOUT_MS = 1_500;

/**
 * Forget this browser's push subscription when the user signs out, so a
 * shared browser stops getting their notifications: the server forgets the
 * endpoint (a `keepalive` request that outlives the page) and the browser
 * unsubscribes, which also makes the push service refuse the old endpoint.
 * Never throws, and settles within {@link FORGET_TIMEOUT_MS}.
 */
export async function forgetPushSubscription(
  token: string | null,
): Promise<void> {
  if (!isPushSupported()) return;
  const forget = async () => {
    const registration = await navigator.serviceWorker.getRegistration('/');
    const subscription = await registration?.pushManager.getSubscription();
    if (!subscription) return;
    backgroundService.forgetPushSubscriptionOnExit(
      subscription.endpoint,
      token,
    );
    await subscription.unsubscribe();
  };
  await Promise.race([
    forget().catch(() => undefined),
    new Promise<void>((resolve) => setTimeout(resolve, FORGET_TIMEOUT_MS)),
  ]);
}

/** An in-app path from a notification, or null for anything that would leave the app. */
export function safeAppPath(url: unknown): string | null {
  if (typeof url !== 'string' || !url.startsWith('/') || url.startsWith('//')) {
    return null;
  }
  return url;
}
