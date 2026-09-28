import { X } from 'lucide-react';
import { useCallback, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { Link } from 'react-router-dom';

import { Button } from '../components/ui/button';
import {
  Toast,
  ToastActions,
  ToastFooter,
  ToastHeader,
  ToastTitle,
} from '../components/ui/toast';
import { loadConnectors } from '../connectors/connectorsSlice';
import { selectToken } from '../preferences/preferenceSlice';
import type { AppDispatch } from '../store';
import {
  dismissShareNotification,
  selectDismissedShareNotifications,
  selectRecentEvents,
  type SSEEvent,
} from './notificationsSlice';

// Backlog replay re-delivers up to a day of events; an old one is noise.
const MAX_AGE_MS = 24 * 60 * 60 * 1000;
const MAX_VISIBLE = 2;

/**
 * "Reconnect Google Drive to keep syncing": a connection whose sign-in
 * stopped working (``connection.reconnect_needed``). Stays until the user
 * reconnects or dismisses it, since syncing is paused until then. Shares
 * the team notifications' persisted dismissals, so a reload does not pop it
 * again.
 */
export default function ConnectionHealthToast() {
  const dispatch = useDispatch<AppDispatch>();
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const events = useSelector(selectRecentEvents);
  const dismissed = useSelector(selectDismissedShareNotifications);
  const dismissedSet = useMemo(() => new Set(dismissed), [dismissed]);

  const onDismiss = useCallback(
    (id: string) => dispatch(dismissShareNotification(id)),
    [dispatch],
  );

  const now = Date.now();
  const visible: SSEEvent[] = [];
  const seenConnections = new Set<string>();
  for (const event of events) {
    if (event.type !== 'connection.reconnect_needed') continue;
    if (!event.id || dismissedSet.has(event.id)) continue;
    if (event.ts) {
      const age = now - Date.parse(event.ts);
      if (Number.isFinite(age) && age > MAX_AGE_MS) continue;
    }
    const connectionId = String(event.scope?.id ?? event.id);
    if (seenConnections.has(connectionId)) continue;
    seenConnections.add(connectionId);
    visible.push(event);
    if (visible.length >= MAX_VISIBLE) break;
  }

  // Refresh the badges on the Connectors, Sources and Tools pages.
  const newest = visible[0]?.id;
  useEffect(() => {
    if (newest) dispatch(loadConnectors({ token }));
  }, [newest, dispatch, token]);

  if (visible.length === 0) return null;

  return (
    <>
      {visible.map((event) => {
        const payload = (event.payload ?? {}) as Record<string, unknown>;
        const name = String(payload.name ?? '');
        const key = String(payload.connector_key ?? '');
        return (
          <Toast key={event.id}>
            <ToastHeader variant="warning">
              <ToastTitle wrap>
                {t('settings.connectors.health.reconnect', {
                  name,
                  interpolation: { escapeValue: false },
                })}
              </ToastTitle>
              <ToastActions>
                <Button
                  type="button"
                  variant="ghost-muted"
                  size="icon-sm"
                  onClick={() => onDismiss(event.id as string)}
                  aria-label={t('notifications.dismiss')}
                >
                  <X />
                </Button>
              </ToastActions>
            </ToastHeader>
            <ToastFooter>
              <Button asChild size="sm" shape="pill">
                <Link
                  to={`/settings/connectors?connector=${encodeURIComponent(key)}`}
                  onClick={() => onDismiss(event.id as string)}
                >
                  {t('settings.connectors.status.reconnect')}
                </Link>
              </Button>
            </ToastFooter>
          </Toast>
        );
      })}
    </>
  );
}
