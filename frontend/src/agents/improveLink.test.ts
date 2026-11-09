vi.mock('react-redux', () => ({ useSelector: () => undefined }));

import {
  agentImprovePath,
  canImproveAgent,
  readImproveHandoff,
} from './improveLink';
import type { Agent } from './types';

const CONVERSATION = '0b6f3a52-1c2d-4e5f-8a9b-0c1d2e3f4a5b';
const query = (path: string) => new URL(path, 'http://x').searchParams;

describe('improveLink', () => {
  it('carries a gap or a conversation to the agent form and reads it back', () => {
    const gap = {
      kind: 'gap' as const,
      gap_type: 'docs missing',
      topic: 'Returns & claims',
      where: 'Returns & claims',
    };
    const path = agentImprovePath('a1', gap);
    expect(path.startsWith('/agents/manage/edit/a1?')).toBe(true);
    expect(readImproveHandoff(query(path))).toEqual(gap);
    expect(
      readImproveHandoff(
        query(agentImprovePath('a1', { ...gap, topic: null, where: '/faq' })),
      ),
    ).toEqual({ ...gap, topic: null, where: '/faq' });
    const conversation = {
      kind: 'conversation' as const,
      conversation_id: CONVERSATION,
    };
    expect(
      readImproveHandoff(query(agentImprovePath('a1', conversation))),
    ).toEqual(conversation);
  });

  it('reads nothing from a missing or malformed hand-off', () => {
    const read = (search: string) =>
      readImproveHandoff(new URLSearchParams(search));
    expect(read('')).toBeNull();
    expect(read('improve=other')).toBeNull();
    expect(read('improve=conversation&conversation=not-a-uuid')).toBeNull();
    expect(read('improve=gap&where=Page')).toBeNull();
    expect(read('improve=gap&gap_type=docs%20missing')).toBeNull();
    expect(read(`improve=gap&gap_type=${'x'.repeat(65)}&where=P`)).toBeNull();
  });

  it('lets only an editor of a classic agent, with access fields, improve it', () => {
    const agent = {
      id: 'a1',
      agent_type: 'classic',
      allowed_actions: ['edit', 'view'],
    } as Agent;
    expect(canImproveAgent(agent)).toBe(true);
    expect(canImproveAgent({ ...agent, allowed_actions: ['view'] })).toBe(
      false,
    );
    expect(canImproveAgent({ ...agent, agent_type: 'workflow' })).toBe(false);
    expect(canImproveAgent({ ...agent, allowed_actions: undefined })).toBe(
      false,
    );
    expect(canImproveAgent(null)).toBe(false);
  });
});
