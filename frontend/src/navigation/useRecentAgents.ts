import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';

import type { Agent } from '../agents/types';
import userService from '../api/services/userService';
import {
  selectAgents,
  selectSharedAgents,
  selectToken,
  setAgents,
} from '../preferences/preferenceSlice';
import { captureWorkspace } from '../workspace/requestWorkspace';
import { selectWorkspaceId } from '../workspace/workspaceSlice';

/** How many agents the sidebar lists. */
const SHOWN = 3;
const NONE: Agent[] = [];

/**
 * The sidebar's agents: the pinned ones, filled up to three with the
 * published agents used last. Both lists are the current workspace's: a
 * switch empties the list at once and loads the new workspace's, and an
 * answer from before a switch is dropped.
 *
 * Returns:
 *   The agents to list.
 */
export default function useRecentAgents(): Agent[] {
  const dispatch = useDispatch();
  const token = useSelector(selectToken);
  const agents = useSelector(selectAgents);
  const sharedAgents = useSelector(selectSharedAgents);
  const workspaceId = useSelector(selectWorkspaceId);
  const [recent, setRecent] = useState<{ workspace: string; list: Agent[] }>({
    workspace: workspaceId,
    list: [],
  });

  useEffect(() => {
    const workspace = captureWorkspace();
    const load = async () => {
      try {
        const response = await userService.getPinnedAgents(token);
        if (!response.ok) throw new Error('Failed to fetch pinned agents');
        const pinnedAgents: Agent[] = await response.json();
        if (!workspace.isCurrent()) return;
        if (pinnedAgents.length >= SHOWN) {
          setRecent({ workspace: workspace.id, list: pinnedAgents });
          return;
        }
        let tempAgents: Agent[] = [];
        if (!agents) {
          const response = await userService.getAgents(token);
          if (!response.ok) throw new Error('Failed to fetch agents');
          const data: Agent[] = await response.json();
          if (!workspace.isCurrent()) return;
          dispatch(setAgents(data));
          tempAgents = data;
        } else tempAgents = agents;
        const additionalAgents = tempAgents
          .filter(
            (agent: Agent) =>
              agent.status === 'published' &&
              !pinnedAgents.some((pinned) => pinned.id === agent.id),
          )
          .sort(
            (a: Agent, b: Agent) =>
              new Date(b.last_used_at ?? 0).getTime() -
              new Date(a.last_used_at ?? 0).getTime(),
          )
          .slice(0, SHOWN - pinnedAgents.length);
        setRecent({
          workspace: workspace.id,
          list: [...pinnedAgents, ...additionalAgents],
        });
      } catch (error) {
        console.error('Failed to fetch recent agents: ', error);
      }
    };
    void load();
  }, [agents, sharedAgents, token, workspaceId, dispatch]);

  // The last workspace's agents never show in this one, even for the
  // render before the new list lands.
  return recent.workspace === workspaceId ? recent.list : NONE;
}
