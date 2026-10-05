import { createListenerMiddleware, type PayloadAction } from '@reduxjs/toolkit';
import i18n from 'i18next';

import {
  sseEventReceived,
  type SSEEvent,
} from '../notifications/notificationsSlice';

import {
  markConversationUnread,
  requestPushPrompt,
  type BackgroundState,
} from './backgroundSlice';
import { notificationText } from './kinds';
import { safeAppPath, shouldOfferPush, showLocalNotification } from './webPush';

/** Events older than this are backlog replay, not something that just happened. */
export const FRESH_EVENT_MS = 60_000;

/** The conversation a path shows: `/c/<id>` or `/agents/<agent>/c/<id>`. */
export function conversationIdFromPath(pathname: string): string | null {
  const match = /^\/(?:agents\/[^/]+\/)?c\/([^/]+)\/?$/.exec(pathname);
  if (!match || match[1] === 'new') return null;
  return decodeURIComponent(match[1]);
}

export function isFreshEvent(event: SSEEvent, now = Date.now()): boolean {
  if (!event.ts) return true;
  const age = now - Date.parse(event.ts);
  return !Number.isFinite(age) || age <= FRESH_EVENT_MS;
}

function pageVisible(): boolean {
  return (
    typeof document === 'undefined' || document.visibilityState === 'visible'
  );
}

function currentPath(): string {
  return typeof window === 'undefined' ? '/' : window.location.pathname;
}

type NotificationPayload = {
  kind?: string;
  title?: string;
  body?: string;
  url?: string;
  conversation_id?: string | null;
};

/**
 * Side effects of the event stream for background work:
 *
 * - `notification.created` marks its conversation unread (unless this tab
 *   shows it right now) and, when this tab is hidden and the user allowed
 *   notifications, shows a system notification: the server sent a toast
 *   because a tab is open, but nobody is looking at it.
 * - A job that just went to the background (`job.updated` working), a
 *   monitor or link that was just set up (`monitor.updated`), or a fresh
 *   `notification.created` (a job, monitor or link reporting back) opens the
 *   Web Push prompt, if the user was never asked: the moment it is clear
 *   what the notifications would be for.
 */
export const backgroundListenerMiddleware = createListenerMiddleware();

backgroundListenerMiddleware.startListening({
  actionCreator: sseEventReceived,
  effect: async (action: PayloadAction<SSEEvent>, listenerApi) => {
    const event = action.payload;
    const state = listenerApi.getState() as { background: BackgroundState };

    if (event.type === 'notification.created') {
      const payload = (event.payload ?? {}) as NotificationPayload;
      const conversationId = payload.conversation_id || event.scope?.id || null;
      const onIt =
        conversationId !== null &&
        conversationIdFromPath(currentPath()) === conversationId &&
        pageVisible();
      if (conversationId && !onIt) {
        listenerApi.dispatch(markConversationUnread(conversationId));
      }
      if (!pageVisible() && isFreshEvent(event)) {
        const text = notificationText(payload, (key) => i18n.t(key) ?? key);
        try {
          await showLocalNotification({
            title: text.title,
            body: text.body,
            url: safeAppPath(payload.url) ?? '/',
            tag: `docsgpt:${conversationId ?? event.id ?? 'notice'}`,
          });
        } catch {
          // No registration or permission: the toast waits in the tab.
        }
      }
    }

    const offersPush =
      (event.type === 'job.updated' &&
        (event.payload as { status?: string } | undefined)?.status ===
          'working') ||
      event.type === 'monitor.updated' ||
      event.type === 'notification.created';
    if (
      offersPush &&
      isFreshEvent(event) &&
      !state.background.pushPromptOpen &&
      shouldOfferPush(state.background.pushConfig?.enabled)
    ) {
      listenerApi.dispatch(requestPushPrompt());
    }
  },
});
