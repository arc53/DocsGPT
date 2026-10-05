import { canAgent, canOpenAgentEditor } from './agentAccess';
import type { Agent } from './types';

const agent = (fields: Partial<Agent>) => ({ id: 'a1', ...fields }) as Agent;

describe('canOpenAgentEditor', () => {
  it('follows the list copy of the agent when there is one', () => {
    const listed = agent({ access: 'editor', allowed_actions: ['view'] });
    expect(canOpenAgentEditor(agent({}), [listed])).toBe(true);
    const viewer = agent({ access: 'viewer', allowed_actions: ['use'] });
    expect(canOpenAgentEditor(agent({}), [viewer])).toBe(false);
  });

  it('uses the selected agent when it carries the actions', () => {
    expect(
      canOpenAgentEditor(
        agent({ access: 'viewer', allowed_actions: ['pin', 'use'] }),
        [],
      ),
    ).toBe(false);
    expect(
      canOpenAgentEditor(agent({ access: 'owner', allowed_actions: ['view'] })),
    ).toBe(true);
  });

  it('refuses an unlisted agent with no access fields', () => {
    expect(canOpenAgentEditor(agent({}), [])).toBe(false);
    expect(canOpenAgentEditor(null, [])).toBe(false);
  });
});

describe('canAgent', () => {
  const all = ['view', 'view_logs', 'manage_schedules', 'pin'];
  it('follows allowed_actions on a published agent', () => {
    const a = agent({
      status: 'published',
      access: 'editor',
      allowed_actions: all,
    });
    expect(all.every((x) => canAgent(a, x))).toBe(true);
  });

  it('drops Logs, Schedules and Pin on a draft, keeps the editor', () => {
    const a = agent({ status: 'draft', access: 'owner', allowed_actions: all });
    expect(canAgent(a, 'view')).toBe(true);
    expect(canAgent(a, 'view_logs')).toBe(false);
    expect(canAgent(a, 'manage_schedules')).toBe(false);
    expect(canAgent(a, 'pin')).toBe(false);
  });

  it('treats an agent with no status yet as published', () => {
    expect(canAgent(agent({ allowed_actions: all }), 'view_logs')).toBe(true);
  });
});
