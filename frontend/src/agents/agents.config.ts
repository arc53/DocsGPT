import userService from '../api/services/userService';
import {
  selectAgents,
  selectSharedAgents,
  selectTemplateAgents,
  setAgents,
  setSharedAgents,
  setTemplateAgents,
} from '../preferences/preferenceSlice';

export type AgentSectionId = 'template' | 'user' | 'team' | 'shared';

export const agentSectionsConfig = [
  {
    id: 'template' as const,
    title: 'Templates',
    description: 'Agents provided by DocsGPT',
    showNewAgentButton: false,
    emptyStateDescription: 'No template agents found.',
    fetchAgents: (token: string | null) => userService.getTemplateAgents(token),
    selectData: selectTemplateAgents,
    updateAction: setTemplateAgents,
  },
  {
    id: 'user' as const,
    title: 'My agents',
    description: 'Agents created or published by you',
    showNewAgentButton: true,
    emptyStateDescription: 'You don’t have any created agents yet.',
    fetchAgents: (token: string | null) => userService.getAgents(token),
    selectData: selectAgents,
    updateAction: setAgents,
  },
  {
    // Team-shared agents are split out of the 'user' payload client-side
    // (they arrive in /api/get_agents tagged ownership:'team'), so this
    // section reuses the same selector/action — the hook partitions by
    // ownership for display.
    id: 'team' as const,
    title: 'Team',
    description: 'Agents your teammates shared with you',
    showNewAgentButton: false,
    emptyStateDescription: 'No agents have been shared with your team yet.',
    fetchAgents: (token: string | null) => userService.getAgents(token),
    selectData: selectAgents,
    updateAction: setAgents,
  },
  {
    id: 'shared' as const,
    title: 'Discovered',
    description: "Public agents you've opened via a link",
    showNewAgentButton: false,
    emptyStateDescription: "You haven't opened any public agents yet.",
    fetchAgents: (token: string | null) => userService.getSharedAgents(token),
    selectData: selectSharedAgents,
    updateAction: setSharedAgents,
  },
];
