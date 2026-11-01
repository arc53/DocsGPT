import {
  type AgentDraftForm,
  agentDraftContext,
  agentDraftValues,
  agentProposalSummary,
  isAgentFormEmpty,
  parseAgentProposal,
  planAgentPatch,
} from './agentDraft';

const form = (over: Partial<AgentDraftForm> = {}): AgentDraftForm => ({
  name: '',
  description: '',
  agent_type: 'classic',
  sources: [],
  tools: [],
  starters: [],
  prompt: { prompt_id: 'default', pending: null },
  ...over,
});

const track = { id: 't1', name: 'api_tool', display_name: 'Tracking API' };
const search = { id: 't2', name: 'brave', display_name: 'Web search' };

describe('agentDraft', () => {
  it('reads a proposal, leaving out what is malformed or not allowed', () => {
    const proposal = parseAgentProposal({
      message: 'Done',
      fields: {
        name: 'Shipping help',
        agent_type: 'workflow',
        sources: ['s1', 7],
        tools: 'nope',
        prompt: { kind: 'new', name: ' Support ', content: 'You help.' },
        models: ['gpt'],
      },
      reasons: [{ field: 'name', summary: 'Short' }, { field: 'x' }],
      notes: ['Note', 3],
      dropped: [{ field: 'tools', id: 'zz', reason: 'not_found' }],
    })!;
    expect(proposal.fields).toEqual({
      name: 'Shipping help',
      sources: ['s1'],
      prompt: { kind: 'new', name: 'Support', content: 'You help.' },
    });
    expect(proposal.reasons).toEqual([{ field: 'name', summary: 'Short' }]);
    expect(proposal.notes).toEqual(['Note']);
    expect(proposal.dropped).toHaveLength(1);
    expect(parseAgentProposal('text')).toBeNull();
  });

  it('plans changes in apply order with the values to undo to', () => {
    const now = form({ name: 'Old', tools: [search], sources: ['s1'] });
    const changes = planAgentPatch(
      {
        prompt: { kind: 'existing', id: 'creative' },
        name: 'Shipping help',
        description: 'Answers shipping questions.',
        sources: ['s2', 's1'],
        tools: ['t1', 'missing'],
        agent_type: 'research',
        starters: [' Where is my parcel? ', '', 'where is my parcel?'],
      },
      now,
      [track, search],
    );
    expect(changes.map((change) => change.field)).toEqual([
      'sources',
      'tools',
      'agent_type',
      'name',
      'description',
      'starters',
      'prompt',
    ]);
    expect(changes[1]).toEqual({
      field: 'tools',
      next: [track],
      previous: [search],
    });
    expect(changes[3]).toEqual({
      field: 'name',
      next: 'Shipping help',
      previous: 'Old',
    });
    expect(changes[5].next).toEqual(['Where is my parcel?']);
    expect(changes[6]).toEqual({
      field: 'prompt',
      next: { prompt_id: 'creative', pending: null },
      previous: { prompt_id: 'default', pending: null },
    });
  });

  it('skips fields the proposal leaves as they are', () => {
    const now = form({ name: 'Same', sources: ['a', 'b'], tools: [track] });
    expect(
      planAgentPatch(
        {
          name: 'Same',
          sources: ['b', 'a'],
          tools: ['t1'],
          agent_type: 'classic',
          prompt: { kind: 'existing', id: 'default' },
        },
        now,
        [track],
      ),
    ).toEqual([]);
  });

  it('keeps the picked prompt under a new pending one', () => {
    const [change] = planAgentPatch(
      { prompt: { kind: 'new', name: 'Support', content: 'You help.' } },
      form({ prompt: { prompt_id: 'p9', pending: null } }),
      [],
    );
    expect(change.next).toEqual({
      prompt_id: 'p9',
      pending: { name: 'Support', content: 'You help.' },
    });
  });

  it('compares tools by id and sources in any order', () => {
    expect(
      agentDraftValues(form({ tools: [track], sources: ['b', 'a'] })),
    ).toMatchObject({ tools: ['t1'], sources: ['a', 'b'] });
  });

  it('reads an untouched form as empty, and a picked source as not', () => {
    expect(isAgentFormEmpty(form())).toBe(true);
    expect(isAgentFormEmpty(form({ starters: ['  '] }))).toBe(true);
    expect(isAgentFormEmpty(form({ sources: ['s1'] }))).toBe(false);
    expect(
      isAgentFormEmpty(
        form({
          prompt: {
            prompt_id: 'default',
            pending: { name: 'a', content: 'b' },
          },
        }),
      ),
    ).toBe(false);
  });

  it('sends the form as the contract context', () => {
    expect(
      agentDraftContext(
        '',
        form({
          name: 'N',
          tools: [track],
          starters: ['Hi'],
          prompt: { prompt_id: 'p1', pending: { name: 'P', content: 'C' } },
        }),
      ),
    ).toEqual({
      agent_id: null,
      form: {
        name: 'N',
        description: '',
        agent_type: 'classic',
        sources: [],
        tools: ['t1'],
        prompt_id: 'p1',
        pending_prompt: { name: 'P', content: 'C' },
        starters: ['Hi'],
      },
    });
  });

  it('gives a reason row only for the fields the draft changed', () => {
    const t = ((key: string) => key) as never;
    const proposal = parseAgentProposal({
      fields: { name: 'Shipping help', agent_type: 'classic' },
      reasons: [
        { field: 'name', summary: 'Says what it does' },
        { field: 'agent_type', summary: 'Classic suits Q&A' },
        { field: 'model', summary: 'Not a draft field' },
      ],
      dropped: [{ field: 'tools', reason: 'no_access' }],
    })!;
    const { rows, dropped } = agentProposalSummary(proposal, t, ['name']);
    expect(rows.map((row) => row.summary)).toEqual(['Says what it does']);
    // What the server left out is listed whatever changed.
    expect(dropped).toEqual(['drafter.agent.droppedLine']);
    // Without a record of the changes, every reason shows.
    expect(agentProposalSummary(proposal, t).rows).toHaveLength(3);
  });
});
