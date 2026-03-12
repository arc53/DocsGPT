import userService from '../api/services/userService';
import {
  selectAgents,
  selectSharedAgents,
  selectTemplateAgents,
  setAgents,
  setSharedAgents,
  setTemplateAgents,
} from '../preferences/preferenceSlice';

export type AgentSectionId = 'template' | 'user' | 'shared';

export const agentSectionsConfig = [
  {
    id: 'template' as const,
    title: 'By DocsGPT',
    description: 'Agents provided by DocsGPT',
    showNewAgentButton: false,
    emptyStateDescription: 'No template agents found.',
    fetchAgents: (token: string | null) => userService.getTemplateAgents(token),
    selectData: selectTemplateAgents,
    updateAction: setTemplateAgents,
  },
  {
    id: 'user' as const,
    title: 'By me',
    description: 'Agents created or published by you',
    showNewAgentButton: true,
    emptyStateDescription: 'You don’t have any created agents yet.',
    fetchAgents: (token: string | null) => userService.getAgents(token),
    selectData: selectAgents,
    updateAction: setAgents,
  },
  {
    id: 'shared' as const,
    title: 'Shared with me',
    description: 'Agents imported by using a public link',
    showNewAgentButton: false,
    emptyStateDescription: 'No shared agents found.',
    fetchAgents: (token: string | null) => userService.getSharedAgents(token),
    selectData: selectSharedAgents,
    updateAction: setSharedAgents,
  },
];