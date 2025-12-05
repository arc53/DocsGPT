import { useCallback, useMemo, useState } from 'react';
import { useSelector } from 'react-redux';

import {
  selectAgents,
  selectSharedAgents,
  selectTemplateAgents,
} from '../../preferences/preferenceSlice';
import { AgentSectionId } from '../agents.config';
import { Agent } from '../types';

export type AgentFilterTab = 'all' | AgentSectionId;

export type AgentsBySection = Record<AgentSectionId, Agent[]>;

interface UseAgentSearchResult {
  searchQuery: string;
  setSearchQuery: (query: string) => void;
  activeFilter: AgentFilterTab;
  setActiveFilter: (filter: AgentFilterTab) => void;
  filteredAgentsBySection: AgentsBySection;
  totalAgentsBySection: Record<AgentSectionId, number>;
  hasAnyAgents: boolean;
  hasFilteredResults: boolean;
  isDataLoaded: Record<AgentSectionId, boolean>;
}

const filterAgentsByQuery = (
  agents: Agent[] | null,
  query: string,
): Agent[] => {
  if (!agents) return [];
  if (!query.trim()) return agents;

  const normalizedQuery = query.toLowerCase().trim();
  return agents.filter(
    (agent) =>
      agent.name.toLowerCase().includes(normalizedQuery) ||
      agent.description?.toLowerCase().includes(normalizedQuery),
  );
};

export function useAgentSearch(): UseAgentSearchResult {
  const [searchQuery, setSearchQuery] = useState('');
  const [activeFilter, setActiveFilter] = useState<AgentFilterTab>('all');

  const templateAgents = useSelector(selectTemplateAgents);
  const userAgents = useSelector(selectAgents);
  const sharedAgents = useSelector(selectSharedAgents);

  const handleSearchChange = useCallback((query: string) => {
    setSearchQuery(query);
  }, []);

  const handleFilterChange = useCallback((filter: AgentFilterTab) => {
    setActiveFilter(filter);
  }, []);

  const isDataLoaded = useMemo(
    (): Record<AgentSectionId, boolean> => ({
      template: templateAgents !== null,
      user: userAgents !== null,
      shared: sharedAgents !== null,
    }),
    [templateAgents, userAgents, sharedAgents],
  );

  const totalAgentsBySection = useMemo(
    (): Record<AgentSectionId, number> => ({
      template: templateAgents?.length ?? 0,
      user: userAgents?.length ?? 0,
      shared: sharedAgents?.length ?? 0,
    }),
    [templateAgents, userAgents, sharedAgents],
  );

  const filteredAgentsBySection = useMemo((): AgentsBySection => {
    const filtered = {
      template: filterAgentsByQuery(templateAgents, searchQuery),
      user: filterAgentsByQuery(userAgents, searchQuery),
      shared: filterAgentsByQuery(sharedAgents, searchQuery),
    };

    if (activeFilter === 'all') {
      return filtered;
    }

    return {
      template: activeFilter === 'template' ? filtered.template : [],
      user: activeFilter === 'user' ? filtered.user : [],
      shared: activeFilter === 'shared' ? filtered.shared : [],
    };
  }, [templateAgents, userAgents, sharedAgents, searchQuery, activeFilter]);

  const hasAnyAgents = useMemo(() => {
    return (
      totalAgentsBySection.template > 0 ||
      totalAgentsBySection.user > 0 ||
      totalAgentsBySection.shared > 0
    );
  }, [totalAgentsBySection]);

  const hasFilteredResults = useMemo(() => {
    return (
      filteredAgentsBySection.template.length > 0 ||
      filteredAgentsBySection.user.length > 0 ||
      filteredAgentsBySection.shared.length > 0
    );
  }, [filteredAgentsBySection]);

  return {
    searchQuery,
    setSearchQuery: handleSearchChange,
    activeFilter,
    setActiveFilter: handleFilterChange,
    filteredAgentsBySection,
    totalAgentsBySection,
    hasAnyAgents,
    hasFilteredResults,
    isDataLoaded,
  };
}
