import { describe, expect, it } from 'vitest';

import {
  agentChatPath,
  agentEditPathFor,
  agentsFilterPath,
  agentsListPath,
  filterFromPath,
  matchAgentScopedRoute,
} from './paths';

describe('agentsFilterPath / filterFromPath', () => {
  it('round-trips every filter', () => {
    for (const filter of ['all', 'template', 'user', 'team', 'shared'] as const)
      expect(filterFromPath(agentsFilterPath(filter))).toBe(filter);
  });

  it('treats the list root and unknown slugs as unfiltered', () => {
    expect(filterFromPath('/agents/manage')).toBe('all');
    expect(filterFromPath('/agents/manage/nonsense')).toBe('all');
  });

  it('does not read a filter out of an agent page', () => {
    expect(filterFromPath('/agents/manage/edit/a1')).toBe('all');
  });
});

describe('agentsListPath', () => {
  it('encodes a folder id into the query', () => {
    expect(agentsListPath()).toBe('/agents/manage');
    expect(agentsListPath('a b')).toBe('/agents/manage?folder=a%20b');
    expect(agentsListPath(null)).toBe('/agents/manage');
  });
});

describe('agentEditPathFor', () => {
  it('sends workflow agents to the builder', () => {
    expect(agentEditPathFor({ id: 'a1', agent_type: 'workflow' })).toBe(
      '/agents/manage/workflow/edit/a1',
    );
    expect(agentEditPathFor({ id: 'a1', agent_type: 'classic' })).toBe(
      '/agents/manage/edit/a1',
    );
  });
});

describe('matchAgentScopedRoute', () => {
  it('recognises each of an agent’s pages', () => {
    expect(matchAgentScopedRoute('/agents/manage/edit/a1')).toEqual({
      agentId: 'a1',
      page: 'overview',
      workflow: false,
    });
    expect(matchAgentScopedRoute('/agents/manage/logs/a1')?.page).toBe('logs');
    expect(matchAgentScopedRoute('/agents/manage/schedules/a1')?.page).toBe(
      'schedules',
    );
    expect(matchAgentScopedRoute('/agents/manage/workflow/edit/a1')).toEqual({
      agentId: 'a1',
      page: 'overview',
      workflow: true,
    });
  });

  it('ignores the list, and a chat with an agent', () => {
    expect(matchAgentScopedRoute('/agents/manage')).toBeNull();
    expect(matchAgentScopedRoute('/agents/manage/mine')).toBeNull();
    expect(matchAgentScopedRoute('/agents/manage/new')).toBeNull();
    // The whole point of the split: this is a conversation, not an editor.
    expect(matchAgentScopedRoute(agentChatPath('a1', 'c1'))).toBeNull();
  });
});
