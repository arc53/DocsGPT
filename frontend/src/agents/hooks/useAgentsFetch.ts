import { useCallback, useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';

import userService from '../../api/services/userService';
import { loadFolders } from '../../components/folders/foldersSlice';
import { selectFoldersInTeam as selectInTeam } from '../../components/folders/folderWorkspace';
import {
  selectToken,
  setAgents,
  setSharedAgents,
  setTemplateAgents,
} from '../../preferences/preferenceSlice';
import type { AppDispatch } from '../../store';
import { captureWorkspace } from '../../workspace/requestWorkspace';
import { AgentSectionId } from '../agents.config';

interface UseAgentsFetchResult {
  isLoading: Record<AgentSectionId, boolean>;
  isAllLoaded: boolean;
  refetchFolders: () => Promise<void>;
  refetchUserAgents: () => Promise<void>;
}

/**
 * Loads the agent list's sections: templates, the workspace's agents (with,
 * in Personal, the ones shared with the caller) and, in Personal, the public
 * agents opened by a link. An answer that comes back after a workspace
 * switch is dropped, so it can't land in the other workspace's list.
 *
 * Returns:
 *   Each section's loading state, and refetches for the agents and folders.
 */
export function useAgentsFetch(): UseAgentsFetchResult {
  const dispatch = useDispatch<AppDispatch>();
  const token = useSelector(selectToken);
  const inTeam = useSelector(selectInTeam);

  const [isLoading, setIsLoading] = useState<Record<AgentSectionId, boolean>>({
    template: true,
    user: true,
    // Shared with you and Shared with this team are split out of the same
    // /api/get_agents payload, so their loading state tracks the user fetch.
    teamShared: true,
    sharedWithYou: true,
    shared: true,
  });

  const fetchTemplateAgents = useCallback(async () => {
    const workspace = captureWorkspace();
    try {
      const response = await userService.getTemplateAgents(token);
      if (!response.ok) throw new Error('Failed to fetch template agents');
      const data = await response.json();
      if (workspace.isCurrent()) dispatch(setTemplateAgents(data));
    } catch (error) {
      if (workspace.isCurrent()) dispatch(setTemplateAgents([]));
    } finally {
      setIsLoading((prev) => ({ ...prev, template: false }));
    }
  }, [token, dispatch]);

  const fetchUserAgents = useCallback(async () => {
    const workspace = captureWorkspace();
    try {
      const response = await userService.getAgents(token);
      if (!response.ok) throw new Error('Failed to fetch user agents');
      const data = await response.json();
      if (workspace.isCurrent()) dispatch(setAgents(data));
    } catch (error) {
      if (workspace.isCurrent()) dispatch(setAgents([]));
    } finally {
      setIsLoading((prev) => ({
        ...prev,
        user: false,
        teamShared: false,
        sharedWithYou: false,
      }));
    }
  }, [token, dispatch]);

  // Discovered is Personal's: a team lists nothing there.
  const fetchSharedAgents = useCallback(async () => {
    if (inTeam) {
      setIsLoading((prev) => ({ ...prev, shared: false }));
      return;
    }
    const workspace = captureWorkspace();
    try {
      const response = await userService.getSharedAgents(token);
      if (!response.ok) throw new Error('Failed to fetch shared agents');
      const data = await response.json();
      if (workspace.isCurrent()) dispatch(setSharedAgents(data));
    } catch (error) {
      if (workspace.isCurrent()) dispatch(setSharedAgents([]));
    } finally {
      setIsLoading((prev) => ({ ...prev, shared: false }));
    }
  }, [token, dispatch, inTeam]);

  // Agent folders live in the shared folders slice: a failed load shows as
  // an error on the page (`selectFolderList('agent').failed`), not as none.
  const fetchFolders = useCallback(async () => {
    await dispatch(loadFolders({ type: 'agent', token }));
  }, [token, dispatch]);

  useEffect(() => {
    setIsLoading({
      template: true,
      user: true,
      teamShared: true,
      sharedWithYou: true,
      shared: true,
    });
    Promise.all([
      fetchTemplateAgents(),
      fetchUserAgents(),
      fetchSharedAgents(),
      fetchFolders(),
    ]);
  }, [fetchTemplateAgents, fetchUserAgents, fetchSharedAgents, fetchFolders]);

  const isAllLoaded =
    !isLoading.template &&
    !isLoading.user &&
    !isLoading.teamShared &&
    !isLoading.sharedWithYou &&
    !isLoading.shared;

  return {
    isLoading,
    isAllLoaded,
    refetchFolders: fetchFolders,
    refetchUserAgents: fetchUserAgents,
  };
}
