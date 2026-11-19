import type { TFunction } from 'i18next';

import apiClient from '../api/client';
import endpoints from '../api/endpoints';
import { getConversations } from '../preferences/preferenceApi';
import {
  appendConversations,
  receiveConversations,
  removeAllConversations,
  setConversationsLoading,
} from '../preferences/preferenceSlice';
import {
  captureWorkspace,
  workspaceHeader,
} from '../workspace/requestWorkspace';
import type { WorkspaceRow } from '../workspace/workspaceSlice';

type Dispatch = (action: unknown) => unknown;

/**
 * Loads the newest page of the sidebar's chats again (after a delete or a
 * rename). An answer that lands after a switch is the old workspace's and
 * is dropped.
 *
 * Args:
 *   token: The session token.
 */
export const refreshChats =
  (token: string | null) =>
  async (dispatch: Dispatch): Promise<void> => {
    const workspace = captureWorkspace();
    // Only the flag: a copy of the list from this render would put back a
    // chat removed just before, and the merge would then keep it.
    dispatch(setConversationsLoading(true));
    const fetched = await getConversations(token);
    if (!workspace.isCurrent()) return;
    dispatch(receiveConversations(fetched));
  };

/**
 * Loads the chats older than `before`, for the end of the sidebar's list.
 *
 * Args:
 *   token: The session token.
 *   before: The oldest chat listed.
 *
 * Returns:
 *   `loaded`, `failed`, or `stale` when the workspace switched meanwhile
 *   (nothing is added).
 */
export const loadOlderChats =
  (token: string | null, before: { date: string; id: string }) =>
  async (dispatch: Dispatch): Promise<'loaded' | 'failed' | 'stale'> => {
    const workspace = captureWorkspace();
    const result = await getConversations(token, before);
    if (!workspace.isCurrent()) return 'stale';
    if (!result.data) return 'failed';
    dispatch(appendConversations(result.data, result.requestedAt));
    return 'loaded';
  };

/**
 * Deletes every chat the caller started in one workspace (the server clears
 * only the workspace the request names), then loads the list again when
 * that workspace is still the one shown.
 *
 * Args:
 *   token: The session token.
 *   workspaceId: The workspace the confirmation named.
 *
 * Raises:
 *   Error: The server refused; the confirmation shows it.
 */
export const deleteAllChats =
  (token: string | null, workspaceId: string) =>
  async (dispatch: Dispatch): Promise<void> => {
    const workspace = captureWorkspace();
    // A GET that deletes: named explicitly, so it clears the workspace the
    // dialog named and no other.
    const response: Response = await apiClient.get(
      endpoints.CONVERSATION.DELETE_ALL,
      token,
      workspaceHeader(workspaceId),
    );
    if (!response.ok) throw new Error('Failed to delete conversations');
    if (!workspace.isCurrent() || workspace.id !== workspaceId) return;
    dispatch(removeAllConversations());
    await (dispatch(refreshChats(token)) as Promise<void>);
  };

/**
 * The confirmation for Delete all chats, naming the workspace it clears:
 * "Delete all your chats in Operations?".
 *
 * Args:
 *   t: The translate function.
 *   workspace: The current workspace.
 */
export function deleteAllChatsCopy(
  t: TFunction,
  workspace: WorkspaceRow,
): { message: string; description: string } {
  const name =
    workspace.kind === 'team'
      ? workspace.name || t('workspace.chat.thisTeam')
      : t('workspace.switcher.personal');
  const values = { name, interpolation: { escapeValue: false } };
  return {
    message: t('workspace.chat.deleteAll.confirm', values),
    description: t('workspace.chat.deleteAll.consequence', values),
  };
}
