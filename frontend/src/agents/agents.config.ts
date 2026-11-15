import userService from '../api/services/userService';
import {
  selectAgents,
  selectSharedAgents,
  selectTemplateAgents,
  setAgents,
  setSharedAgents,
  setTemplateAgents,
} from '../preferences/preferenceSlice';

/**
 * The agent list's sections. `user` is the workspace's own agents (My
 * agents in Personal, the team's in a team); `sharedWithYou` the ones people
 * shared with the caller directly (Personal only); `shared` the public ones
 * opened by a link (Discovered, Personal only).
 */
export type AgentSectionId = 'template' | 'user' | 'sharedWithYou' | 'shared';

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
    // Split out of the same /api/get_agents payload by `origin`, so it reuses
    // the user section's selector and action.
    id: 'sharedWithYou' as const,
    title: 'Shared with you',
    description: 'Agents people shared with you',
    showNewAgentButton: false,
    emptyStateDescription: 'No one has shared an agent with you yet.',
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

/** The sections a team workspace leaves out: nothing is shared into a team. */
export const PERSONAL_ONLY_SECTIONS: readonly AgentSectionId[] = [
  'sharedWithYou',
  'shared',
];
