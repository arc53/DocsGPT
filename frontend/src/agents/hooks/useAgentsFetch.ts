import { useCallback, useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';

import userService from '../../api/services/userService';
import {
  selectToken,
  setAgentFolders,
  setAgents,
  setSharedAgents,
  setTemplateAgents,
} from '../../preferences/preferenceSlice';
import { AgentSectionId } from '../agents.config';

interface UseAgentsFetchResult {
  isLoading: Record<AgentSectionId, boolean>;
  isAllLoaded: boolean;
  refetchFolders: () => Promise<void>;
}

export function useAgentsFetch(): UseAgentsFetchResult {
  const dispatch = useDispatch();
  const token = useSelector(selectToken);

  const [isLoading, setIsLoading] = useState<Record<AgentSectionId, boolean>>({
    template: true,
    user: true,
    shared: true,
  });

  const fetchTemplateAgents = useCallback(async () => {
    try {
      const response = await userService.getTemplateAgents(token);
      if (!response.ok) throw new Error('Failed to fetch template agents');
      const data = await response.json();
      dispatch(setTemplateAgents(data));
    } catch (error) {
      dispatch(setTemplateAgents([]));
    } finally {
      setIsLoading((prev) => ({ ...prev, template: false }));
    }
  }, [token, dispatch]);

  const fetchUserAgents = useCallback(async () => {
    try {
      const response = await userService.getAgents(token);
      if (!response.ok) throw new Error('Failed to fetch user agents');
      const data = await response.json();
      dispatch(setAgents(data));
    } catch (error) {
      dispatch(setAgents([]));
    } finally {
      setIsLoading((prev) => ({ ...prev, user: false }));
    }
  }, [token, dispatch]);

  const fetchSharedAgents = useCallback(async () => {
    try {
      const response = await userService.getSharedAgents(token);
      if (!response.ok) throw new Error('Failed to fetch shared agents');
      const data = await response.json();
      dispatch(setSharedAgents(data));
    } catch (error) {
      dispatch(setSharedAgents([]));
    } finally {
      setIsLoading((prev) => ({ ...prev, shared: false }));
    }
  }, [token, dispatch]);

  const fetchFolders = useCallback(async () => {
    try {
      const response = await userService.getAgentFolders(token);
      if (!response.ok) throw new Error('Failed to fetch folders');
      const data = await response.json();
      dispatch(setAgentFolders(data.folders || []));
    } catch (error) {
      dispatch(setAgentFolders([]));
    }
  }, [token, dispatch]);

  useEffect(() => {
    setIsLoading({ template: true, user: true, shared: true });
    Promise.all([
      fetchTemplateAgents(),
      fetchUserAgents(),
      fetchSharedAgents(),
      fetchFolders(),
    ]);
  }, [fetchTemplateAgents, fetchUserAgents, fetchSharedAgents, fetchFolders]);

  const isAllLoaded =
    !isLoading.template && !isLoading.user && !isLoading.shared;

  return {
    isLoading,
    isAllLoaded,
    refetchFolders: fetchFolders,
  };
}
