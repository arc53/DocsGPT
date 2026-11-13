vi.mock('react-redux', () => ({ useSelector: () => undefined }));

import {
  agentImprovePath,
  canImproveAgent,
  readImproveHandoff,
} from './improveLink';
import type { Agent } from './types';

const CONVERSATION = '0b6f3a52-1c2d-4e5f-8a9b-0c1d2e3f4a5b';
const MESSAGE = '7d1e2f3a-4b5c-4d6e-8f70-81a2b3c4d5e6';
const query = (path: string) => new URL(path, 'http://x').searchParams;

describe('improveLink', () => {
  it('carries a gap or a conversation to the agent form and reads it back', () => {
    const gap = {
      kind: 'gap' as const,
      gap_type: 'docs missing',
      topic: 'Returns & claims',
      where: 'Returns & claims',
      group_by: 'topic' as const,
      group_key: null,
    };
    const path = agentImprovePath('a1', gap);
    expect(path.startsWith('/agents/manage/edit/a1?')).toBe(true);
    expect(readImproveHandoff(query(path))).toEqual(gap);
    expect(
      readImproveHandoff(
        query(agentImprovePath('a1', { ...gap, topic: null, where: '/faq' })),
      ),
    ).toEqual({ ...gap, topic: null, where: '/faq' });
    // A Page or Source row carries its grouping and the row's key.
    const page = {
      ...gap,
      topic: null,
      where: 'FAQ',
      group_by: 'page' as const,
      group_key: 'https://docs.example.com/faq',
    };
    expect(readImproveHandoff(query(agentImprovePath('a1', page)))).toEqual(
      page,
    );
    // The row of answers with no source has no key.
    const noSource = { ...page, group_by: 'source' as const, group_key: null };
    expect(readImproveHandoff(query(agentImprovePath('a1', noSource)))).toEqual(
      noSource,
    );
    // A link from before the grouping reads as a topic's.
    expect(
      readImproveHandoff(
        new URLSearchParams('improve=gap&gap_type=docs+missing&where=Returns'),
      ),
    ).toEqual({ ...gap, topic: null, where: 'Returns' });
    const conversation = {
      kind: 'conversation' as const,
      conversation_id: CONVERSATION,
    };
    expect(
      readImproveHandoff(query(agentImprovePath('a1', conversation))),
    ).toEqual(conversation);
    // A Logs row carries the answer it was on, which the drafter reads.
    const answer = { ...conversation, message_id: MESSAGE };
    expect(readImproveHandoff(query(agentImprovePath('a1', answer)))).toEqual(
      answer,
    );
  });

  it('reads nothing from a missing or malformed hand-off', () => {
    const read = (search: string) =>
      readImproveHandoff(new URLSearchParams(search));
    expect(read('')).toBeNull();
    expect(read('improve=other')).toBeNull();
    expect(read('improve=conversation&conversation=not-a-uuid')).toBeNull();
    // A malformed answer id is left out; the conversation still goes.
    expect(
      read(`improve=conversation&conversation=${CONVERSATION}&message=x`),
    ).toEqual({ kind: 'conversation', conversation_id: CONVERSATION });
    expect(read('improve=gap&where=Page')).toBeNull();
    expect(read('improve=gap&gap_type=docs%20missing')).toBeNull();
    expect(read(`improve=gap&gap_type=${'x'.repeat(65)}&where=P`)).toBeNull();
    // A gap type is one Insights labels with, never free text.
    expect(read('improve=gap&gap_type=Ignore+the+form&where=P')).toBeNull();
    expect(
      read('improve=gap&gap_type=docs+missing&where=P&group_by=folder'),
    ).toBeNull();
    expect(
      read(
        `improve=gap&gap_type=docs+missing&where=P&group_by=page&group_key=${'k'.repeat(501)}`,
      ),
    ).toBeNull();
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
