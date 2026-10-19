import { useCallback, useEffect, useRef, useState } from 'react';
import { useSelector } from 'react-redux';

import userService from '../../api/services/userService';
import { selectToken } from '../../preferences/preferenceSlice';
import type { ConversationInsights } from '../types';
import type { InsightsFetchStatus } from './format';

/**
 * The window's conversation insights (POST /api/get_conversation_insights),
 * fetched again when the agent or the time filter changes. One fetch feeds
 * both the implicit-feedback panel and the insights section.
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
    userService
      .getConversationInsights(
        { api_key_id: agentId, filter_option: filter },
        token,
      )
      .then((response) => {
        if (!response.ok) throw new Error('conversation insights');
        return response.json();
      })
      .then((body: ConversationInsights) => {
        if (id !== requestId.current) return;
        setState(
          body?.success
            ? { status: 'ready', data: body }
            : { status: 'error', data: null },
        );
      })
      .catch(() => {
        if (id === requestId.current) setState({ status: 'error', data: null });
      });
  }, [agentId, filter, token, reloadKey]);

  const retry = useCallback(() => setReloadKey((key) => key + 1), []);
  return { ...state, retry };
}
