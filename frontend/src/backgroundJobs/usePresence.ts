import { useEffect, useRef } from 'react';
import { useSelector } from 'react-redux';
import { useLocation } from 'react-router-dom';

import backgroundService from '../api/services/backgroundService';
import { selectToken } from '../preferences/preferenceSlice';
import type { RootState } from '../store';

import { conversationIdFromPath } from './backgroundListener';

/** How often a visible tab re-reports; the server forgets a report after 45 s. */
export const PRESENCE_HEARTBEAT_MS = 20_000;

function randomTabId(): string {
  try {
    return `tab-${crypto.randomUUID()}`;
  } catch {
    return `tab-${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
  }
}

/** One id per page load: a duplicated tab (which copies sessionStorage) still gets its own. */
export const TAB_ID = randomTabId();

const NEW_CHAT_PATHS = /^\/(?:(?:agents\/[^/]+\/)?c\/new\/?)?$/;

/**
 * The conversation this tab shows: the one in the URL, or, on a new chat
 * whose first answer is streaming (the URL still says new), the one the
 * stream was given.
 */
export function shownConversationId(
  pathname: string,
  streamingConversationId: string | null,
  streaming: boolean,
): string | null {
  const fromPath = conversationIdFromPath(pathname);
  if (fromPath) return fromPath;
  if (streaming && NEW_CHAT_PATHS.test(pathname))
    return streamingConversationId;
  return null;
}

/**
 * Report what this tab shows to `POST /api/presence`: when the route or the
 * visibility changes, every 20 s while visible, and `closing` when the page
 * goes away. The server uses it to stay quiet about a conversation the user
 * is watching, and to choose a toast or a Web Push otherwise.
 */
export function usePresence(): void {
  const { pathname } = useLocation();
  const token = useSelector(selectToken);
  const streamingId = useSelector(
    (state: RootState) => state.conversation.conversationId,
  );
  const streaming = useSelector(
    (state: RootState) => state.conversation.status === 'loading',
  );
  const conversationId = shownConversationId(pathname, streamingId, streaming);
  const latest = useRef({ conversationId, token });
  latest.current = { conversationId, token };

  useEffect(() => {
    const send = (closing = false) => {
      const { conversationId: shown, token: current } = latest.current;
      backgroundService.reportPresence(
        {
          tab_id: TAB_ID,
          conversation_id: shown,
          visible: document.visibilityState === 'visible',
          ...(closing ? { closing: true } : {}),
        },
        current,
      );
    };
    send();
    const onVisibility = () => send();
    const onPageHide = () => send(true);
    // A page restored from the back/forward cache is open again.
    const onPageShow = (event: PageTransitionEvent) => {
      if (event.persisted) send();
    };
    const heartbeat = window.setInterval(() => {
      if (document.visibilityState === 'visible') send();
    }, PRESENCE_HEARTBEAT_MS);
    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('pagehide', onPageHide);
    window.addEventListener('pageshow', onPageShow);
    return () => {
      window.clearInterval(heartbeat);
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('pagehide', onPageHide);
      window.removeEventListener('pageshow', onPageShow);
    };
    // Re-run (and report at once) when the shown conversation or the token changes.
  }, [conversationId, token]);
}
