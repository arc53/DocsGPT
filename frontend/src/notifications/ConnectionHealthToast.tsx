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
import {
  loadConnectors,
  selectConnections,
  selectConnectorCatalog,
  selectConnectorsLoaded,
} from '../connectors/connectorsSlice';
import { reconnectsInPlace } from '../connectors/launchRules';
import useConnectorLauncher from '../connectors/useConnectorLauncher';
import { formatCount } from '../utils/dateTimeUtils';
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
 * "Reconnect Google Drive: 3 sources paused": a connection whose sign-in
 * stopped working (``connection.reconnect_needed``). Reconnect signs in
 * again right here; the toast closes itself once the connection works, or
 * when dismissed. Shares the team notifications' persisted dismissals, so a
 * reload does not pop it again.
 */
export default function ConnectionHealthToast() {
  const dispatch = useDispatch<AppDispatch>();
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const events = useSelector(selectRecentEvents);
  const dismissed = useSelector(selectDismissedShareNotifications);
  const dismissedSet = useMemo(() => new Set(dismissed), [dismissed]);
  const catalog = useSelector(selectConnectorCatalog);
  const connections = useSelector(selectConnections);
  const connectionsLoaded = useSelector(selectConnectorsLoaded);
  const { launch, modals } = useConnectorLauncher();

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
    // Reconnected since (here or anywhere): nothing to say any more.
    const current = connections.find((c) => c.id === connectionId);
    if (connectionsLoaded && current?.status === 'connected') continue;
    seenConnections.add(connectionId);
    visible.push(event);
    if (visible.length >= MAX_VISIBLE) break;
  }

  // Refresh the badges on the Connectors, Sources and Tools pages.
  const newest = visible[0]?.id;
  useEffect(() => {
    if (newest) dispatch(loadConnectors({ token }));
  }, [newest, dispatch, token]);

  if (visible.length === 0) return <>{modals}</>;

  const title = (payload: Record<string, unknown>) => {
    const name = String(payload.name ?? '');
    const sources = Number(payload.source_count ?? 0);
    const tools = Number(payload.tool_count ?? 0);
    const values = {
      name,
      count: sources,
      formatted: formatCount(sources),
      interpolation: { escapeValue: false },
    };
    if (sources && tools)
      return t('settings.connectors.health.reconnectBoth', values);
    if (sources)
      return t('settings.connectors.health.reconnectSources', values);
    if (tools) return t('settings.connectors.health.reconnectTools', values);
    return t('settings.connectors.health.reconnect', values);
  };

  const reconnect = (payload: Record<string, unknown>) => {
    const connectionId = String(payload.connection_id ?? '');
    const connector = catalog.find((c) => c.key === payload.connector_key);
    const inPlace = !!connector && reconnectsInPlace(connector);
    if (connector && connectionId && inPlace) {
      launch(connector, { mode: 'reconnect', connectionId });
      return true;
    }
    return false;
  };

  return (
    <>
      {visible.map((event) => {
        const payload = (event.payload ?? {}) as Record<string, unknown>;
        const key = String(payload.connector_key ?? '');
        const connectionId = String(payload.connection_id ?? '');
        return (
          <Toast key={event.id}>
            <ToastHeader variant="warning">
              <ToastTitle wrap>{title(payload)}</ToastTitle>
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
              {/* Sign in again right here; custom MCP servers reconnect from the
                  connector's drawer. The toast stays until it works. */}
              <Button asChild size="sm" shape="pill">
                <Link
                  to={`/settings/connectors?connector=${encodeURIComponent(key)}${
                    connectionId
                      ? `&connection=${encodeURIComponent(connectionId)}`
                      : ''
                  }`}
                  onClick={(e) => {
                    if (reconnect(payload)) e.preventDefault();
                  }}
                >
                  {t('settings.connectors.status.reconnect')}
                </Link>
              </Button>
            </ToastFooter>
          </Toast>
        );
      })}
      {modals}
    </>
  );
}
