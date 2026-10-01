import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import { selectRecentEvents } from '../notifications/notificationsSlice';
import { selectToken } from '../preferences/preferenceSlice';

export type McpOAuthConfig = {
  server_url: string;
  auth_type: 'oauth';
  oauth_scopes: string[];
  timeout: number;
  redirect_uri: string;
};

type Handlers = {
  /** Signed in: `taskId` is the OAuth task to save with (null when the
   * server already had a valid sign-in). */
  onDone: (result: { taskId: string | null }) => void;
  onError: (message: string) => void;
};

/**
 * Sign in to an MCP server over OAuth from a click. The pop-up opens blank
 * inside the click (so the browser allows it) and follows the worker's
 * `mcp.oauth.*` events: pointed at the provider on `awaiting_redirect`,
 * closed on `completed` or `failed`. Closing the pop-up first stops the
 * wait and reports `authCancelled`, as the connector sign-in does.
 * `blockedUrl` is set when the browser blocked the pop-up anyway, so the
 * caller can offer the link.
 */
export default function useMcpOAuth() {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const events = useSelector(selectRecentEvents);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [blockedUrl, setBlockedUrl] = useState<string | null>(null);
  const popupRef = useRef<Window | null>(null);
  const handlersRef = useRef<Handlers | null>(null);
  const handledRef = useRef<Set<string>>(new Set());
  const pollRef = useRef<number | null>(null);

  const stopPolling = () => {
    if (pollRef.current !== null) window.clearInterval(pollRef.current);
    pollRef.current = null;
  };

  const closePopup = () => {
    if (popupRef.current && !popupRef.current.closed) popupRef.current.close();
    popupRef.current = null;
  };

  const finish = useCallback(() => {
    stopPolling();
    closePopup();
    setTaskId(null);
    setPending(false);
    handlersRef.current = null;
  }, []);

  useEffect(() => finish, [finish]);

  // The user closed the pop-up before signing in: stop waiting.
  const watchPopup = useCallback(() => {
    stopPolling();
    pollRef.current = window.setInterval(() => {
      if (!popupRef.current?.closed) return;
      const done = handlersRef.current;
      finish();
      done?.onError(t('modals.uploadDoc.connectors.auth.authCancelled'));
    }, 1000);
  }, [finish, t]);

  const start = useCallback(
    async (config: McpOAuthConfig, handlers: Handlers) => {
      handlersRef.current = handlers;
      handledRef.current = new Set();
      setBlockedUrl(null);
      setPending(true);
      closePopup();
      popupRef.current = window.open(
        'about:blank',
        'mcpOAuth',
        'width=600,height=700',
      );
      if (popupRef.current) watchPopup();
      try {
        const response = await userService.testMCPConnection({ config }, token);
        const result = await response.json();
        // Cancelled (or started again) while the server answered.
        if (handlersRef.current !== handlers) return;
        if (result.requires_oauth && result.task_id) {
          setTaskId(result.task_id);
          return;
        }
        const done = handlersRef.current;
        finish();
        if (result.success) done?.onDone({ taskId: null });
        else done?.onError(result.message || result.error || '');
      } catch {
        if (handlersRef.current !== handlers) return;
        finish();
        handlers.onError('');
      }
    },
    [token, finish, watchPopup],
  );

  useEffect(() => {
    if (!taskId) return;
    // Newest first in the slice; walk oldest first so a redirect buffered
    // before its completion still opens the provider.
    for (let i = events.length - 1; i >= 0; i--) {
      const event = events[i];
      if (event.scope?.id !== taskId || !event.id) continue;
      if (handledRef.current.has(event.id)) continue;
      handledRef.current.add(event.id);
      const payload = (event.payload ?? {}) as Record<string, unknown>;
      if (event.type === 'mcp.oauth.awaiting_redirect') {
        const url = payload.authorization_url as string | undefined;
        if (!url) continue;
        if (popupRef.current && !popupRef.current.closed) {
          popupRef.current.location.href = url;
        } else {
          popupRef.current = window.open(
            url,
            'mcpOAuth',
            'width=600,height=700',
          );
          if (popupRef.current) watchPopup();
          else setBlockedUrl(url);
        }
      } else if (event.type === 'mcp.oauth.completed') {
        const done = handlersRef.current;
        const id = taskId;
        finish();
        done?.onDone({ taskId: id });
        return;
      } else if (event.type === 'mcp.oauth.failed') {
        const done = handlersRef.current;
        finish();
        done?.onError(String(payload.error ?? ''));
        return;
      }
    }
  }, [events, taskId, finish, watchPopup]);

  return { start, cancel: finish, pending, blockedUrl };
}
