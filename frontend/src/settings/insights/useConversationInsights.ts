import { useCallback, useEffect, useRef, useState } from 'react';
import { useSelector } from 'react-redux';

import userService from '../../api/services/userService';
import { selectToken } from '../../preferences/preferenceSlice';
import type { ConversationInsights } from '../types';
import {
  insightsState,
  type InsightsFetchStatus,
  type InsightsState,
} from './format';

/**
 * How often the page asks again while the sweep is still labelling the
 * window. The sweep runs every few minutes, so a minute keeps the progress
 * bar and the partial figures close behind it without asking for nothing.
 */
export const INSIGHTS_REFRESH_MS = 60_000;

/** The states the sweep is still working through, so worth asking again. */
const STILL_LABELLING: InsightsState[] = ['analyzing', 'partial'];

/** One read of the window's insights; rejects unless it succeeded. */
async function fetchInsights(
  agentId: string | undefined,
  filter: string,
  token: string | null,
): Promise<ConversationInsights> {
  const response = await userService.getConversationInsights(
    { api_key_id: agentId, filter_option: filter },
    token,
  );
  if (!response.ok) throw new Error('conversation insights');
  const body: ConversationInsights = await response.json();
  if (!body?.success) throw new Error('conversation insights');
  return body;
}

/**
 * The window's conversation insights (POST /api/get_conversation_insights),
 * fetched again when the agent or the time filter changes.
 *
 * While the sweep is still labelling the window (`analyzing` or `partial`)
 * it also asks again every `INSIGHTS_REFRESH_MS`, and as soon as a hidden tab
 * comes back, until the window is labelled. Those refreshes are quiet: the
 * current figures stay on screen until the new ones arrive, and a failed
 * refresh keeps them (the next period tries again).
 *
 * Args:
 *   agentId: The agent's id, or nothing for the whole account.
 *   filter: The page's time filter (`last_30_days`).
 *
 * Returns:
 *   The fetch status, the response once it is `ready`, and `retry`.
 */
export function useConversationInsights(
  agentId: string | undefined,
  filter: string,
) {
  const token = useSelector(selectToken);
  const [state, setState] = useState<{
    status: InsightsFetchStatus;
    data: ConversationInsights | null;
  }>({ status: 'loading', data: null });
  const [reloadKey, setReloadKey] = useState(0);
  // A response lands only if no newer request was issued meanwhile, so a
  // slow answer for an old filter can't replace the current one.
  const requestId = useRef(0);

  useEffect(() => {
    const id = ++requestId.current;
    setState({ status: 'loading', data: null });
    fetchInsights(agentId, filter, token)
      .then((body) => {
        if (id === requestId.current) setState({ status: 'ready', data: body });
      })
      .catch(() => {
        if (id === requestId.current) setState({ status: 'error', data: null });
      });
  }, [agentId, filter, token, reloadKey]);

  const labelling = STILL_LABELLING.includes(
    insightsState(state.status, state.data),
  );

  useEffect(() => {
    if (!labelling) return;
    const refresh = () => {
      if (document.hidden) return;
      const id = ++requestId.current;
      fetchInsights(agentId, filter, token)
        .then((body) => {
          if (id === requestId.current)
            setState({ status: 'ready', data: body });
        })
        .catch(() => {
          // Keep the figures on screen; the next period asks again.
        });
    };
    const timer = window.setInterval(refresh, INSIGHTS_REFRESH_MS);
    document.addEventListener('visibilitychange', refresh);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', refresh);
    };
  }, [labelling, agentId, filter, token]);

  const retry = useCallback(() => setReloadKey((key) => key + 1), []);
  return { ...state, retry };
}
