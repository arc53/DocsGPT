/*
 * DocsGPT service worker: Web Push notifications only.
 *
 * It has no fetch handler, so it never caches or intercepts requests. It
 * shows the notifications the server pushes when no DocsGPT tab is open
 * (payload: {title, body, url, tag}), and a click focuses an open tab and
 * routes it to the conversation, or opens one.
 */

self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

function appUrl(url) {
  // Only paths inside this app: a push never opens another site.
  if (typeof url !== 'string' || !url.startsWith('/') || url.startsWith('//')) {
    return new URL('/', self.location.origin).href;
  }
  return new URL(url, self.location.origin).href;
}

self.addEventListener('push', (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = { body: event.data ? event.data.text() : '' };
  }
  const title = typeof data.title === 'string' && data.title ? data.title : 'DocsGPT';
  event.waitUntil(
    self.registration.showNotification(title, {
      body: typeof data.body === 'string' ? data.body : '',
      tag: typeof data.tag === 'string' ? data.tag : undefined,
      icon: '/favicon-96x96.png',
      badge: '/favicon-96x96.png',
      data: { url: appUrl(data.url) },
    }),
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = appUrl(event.notification.data && event.notification.data.url);
  const path = new URL(target).pathname;
  event.waitUntil(
    (async () => {
      const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
      const tab =
        windows.find((client) => client.focused && client.url.startsWith(self.location.origin)) ||
        windows.find((client) => client.url.startsWith(self.location.origin));
      if (tab) {
        // The app routes in place (no reload) when it hears this.
        tab.postMessage({ type: 'docsgpt:navigate', url: path });
        await tab.focus();
        return;
      }
      await self.clients.openWindow(target);
    })(),
  );
});
