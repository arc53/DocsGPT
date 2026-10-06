import { X } from 'lucide-react';
import { useCallback, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useLocation, useNavigate } from 'react-router-dom';

import { Button } from '../components/ui/button';
import {
  Toast,
  ToastActions,
  ToastContent,
  ToastHeader,
  ToastItem,
  ToastMessage,
  ToastTitle,
} from '../components/ui/toast';
import {
  selectRecentEvents,
  type SSEEvent,
} from '../notifications/notificationsSlice';
import type { AppDispatch } from '../store';

import { conversationIdFromPath } from './backgroundListener';
import {
  dismissConversationNotification,
  markConversationRead,
  selectDismissedNotifications,
} from './backgroundSlice';
import { notificationHeadingKey, userTitle } from './kinds';
import { usePageVisible } from './usePageVisible';
import { safeAppPath } from './webPush';

/** A replayed notification older than this is not shown again (the unread dot stays). */
export const NOTIFICATION_MAX_AGE_MS = 15 * 60 * 1000;
/** Visible time before a notification card closes itself. */
export const NOTIFICATION_DISMISS_MS = 12_000;
const MAX_VISIBLE = 3;
const BODY_MAX_CHARS = 180;

type Payload = {
  kind?: string;
  title?: string;
  body?: string;
  url?: string;
  conversation_id?: string | null;
};

function clip(text: string | undefined, limit: number): string {
  const flat = (text ?? '').replace(/\s+/g, ' ').trim();
  return flat.length <= limit ? flat : `${flat.slice(0, limit - 1).trimEnd()}…`;
}

/**
 * One card. Its timer runs only while the page is visible, so a card that
 * landed in a hidden tab is still there when the user comes back.
 */
function NotificationCard({
  event,
  onDismiss,
  onOpen,
}: {
  event: SSEEvent;
  onDismiss: (id: string) => void;
  onOpen: (event: SSEEvent) => void;
}) {
  const { t } = useTranslation();
  const visible = usePageVisible();
  const id = event.id as string;
  const payload = (event.payload ?? {}) as Payload;

  useEffect(() => {
    if (!visible) return;
    const timer = window.setTimeout(
      () => onDismiss(id),
      NOTIFICATION_DISMISS_MS,
    );
    return () => window.clearTimeout(timer);
  }, [id, visible, onDismiss]);

  const title =
    userTitle(payload.title) || t('backgroundJobs.notify.fallbackTitle');
  const body = clip(payload.body, BODY_MAX_CHARS);

  return (
    <Toast data-testid="conversation-notification">
      <ToastHeader variant="default">
        <ToastTitle wrap>{t(notificationHeadingKey(payload.kind))}</ToastTitle>
        <ToastActions>
          <Button
            type="button"
            variant="ghost-muted"
            size="icon-sm"
            onClick={() => onDismiss(id)}
            aria-label={t('notifications.dismiss')}
          >
            <X />
          </Button>
        </ToastActions>
      </ToastHeader>
      <ToastContent>
        <ToastItem label={<span title={title}>{title}</span>}>
          <Button
            type="button"
            size="xs"
            shape="pill"
            onClick={() => onOpen(event)}
          >
            {t('backgroundJobs.notify.open')}
          </Button>
        </ToastItem>
        {body && <ToastMessage>{body}</ToastMessage>}
      </ToastContent>
    </Toast>
  );
}

/**
 * `notification.created` events as toasts with an Open button that goes to
 * the conversation. The server sends them only when a tab is open and the
 * user is not watching that conversation; a card for the conversation on
 * screen is skipped anyway, in case presence lagged.
 */
export default function ConversationNotificationToast() {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const location = useLocation();
  const visible = usePageVisible();
  const events = useSelector(selectRecentEvents);
  const dismissed = useSelector(selectDismissedNotifications);
  const dismissedIds = useMemo(
    () => new Set(dismissed.map((entry) => entry.id)),
    [dismissed],
  );
  const onScreen = visible ? conversationIdFromPath(location.pathname) : null;

  const onDismiss = useCallback(
    (id: string) => dispatch(dismissConversationNotification(id)),
    [dispatch],
  );

  const onOpen = useCallback(
    (event: SSEEvent) => {
      const payload = (event.payload ?? {}) as Payload;
      const conversationId = payload.conversation_id || event.scope?.id;
      if (event.id) dispatch(dismissConversationNotification(event.id));
      const path =
        safeAppPath(payload.url) ??
        (conversationId ? `/c/${encodeURIComponent(conversationId)}` : '/');
      if (conversationId) void dispatch(markConversationRead(conversationId));
      navigate(path);
    },
    [dispatch, navigate],
  );

  const now = Date.now();
  const shown: SSEEvent[] = [];
  for (const event of events) {
    if (event.type !== 'notification.created' || !event.id) continue;
    if (dismissedIds.has(event.id)) continue;
    if (event.ts) {
      const age = now - Date.parse(event.ts);
      if (Number.isFinite(age) && age > NOTIFICATION_MAX_AGE_MS) continue;
    }
    const payload = (event.payload ?? {}) as Payload;
    const conversationId = payload.conversation_id || event.scope?.id;
    if (onScreen && conversationId === onScreen) continue;
    shown.push(event);
    if (shown.length >= MAX_VISIBLE) break;
  }

  if (shown.length === 0) return null;
  return (
    <>
      {shown.map((event) => (
        <NotificationCard
          key={event.id}
          event={event}
          onDismiss={onDismiss}
          onOpen={onOpen}
        />
      ))}
    </>
  );
}
