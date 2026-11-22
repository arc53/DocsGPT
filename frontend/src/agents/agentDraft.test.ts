import i18next from 'i18next';

import { DEFAULT_ANALYTICS } from './analyticsConfig';
import {
  AGENT_DRAFT_FIELDS,
  AGENT_STEP_FIELDS,
  type AgentDraftForm,
  type GuardrailControlToAdd,
  agentDraftContext,
  agentDraftValues,
  agentProposalSummary,
  agentStepResult,
  draftValueOf,
  editedSinceFields,
  fieldsToApply,
  gapLine,
  gapRequest,
  gapTitle,
  improveSuggestions,
  isAgentFormEmpty,
  isSafetyUnset,
  parseAgentProposal,
  planAgentPatch,
  planAgentProposal,
  undoneKindOf,
} from './agentDraft';
import { DEFAULT_GUARDRAILS } from './components/GuardrailsSection';
import type { GuardrailsConfig } from './types';

const form = (over: Partial<AgentDraftForm> = {}): AgentDraftForm => ({
  name: '',
  description: '',
  agent_type: 'classic',
  sources: [],
  folders: [],
  tools: [],
  starters: [],
  prompt: 'default',
  limits: { limited_request_mode: false, limited_token_mode: false },
  guardrails: undefined,
  analytics: DEFAULT_ANALYTICS,
  ...over,
});

const track = { id: 't1', name: 'api_tool', display_name: 'Tracking API' };
const search = { id: 't2', name: 'brave', display_name: 'Web search' };
const t = ((key: string, options?: Record<string, unknown>) =>
  options && 'count' in options
    ? `${key}:${options.count}`
    : options && 'value' in options
      ? `${key}:${options.value}`
      : key) as never;

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
      reasons: [
        { field: 'name', summary: 'Short', detail: 'Longer' },
        { field: 'x' },
      ],
      notes: ['Note', 3],
      dropped: [{ field: 'tools', id: 'zz', reason: 'not_found' }],
      steps: ['basics', 'later', 'knowledge'],
      next_step: 'prompt',
    })!;
    expect(proposal.fields).toEqual({
      name: 'Shipping help',
      sources: ['s1'],
      // An older server sends no checks.
      prompt: {
        kind: 'new',
        name: 'Support',
        content: 'You help.',
        checks: [],
      },
    });
    expect(proposal.reasons).toEqual([{ field: 'name', summary: 'Short' }]);
    expect(proposal.notes).toEqual(['Note']);
    expect(proposal.dropped).toHaveLength(1);
    expect(proposal.steps).toEqual(['basics', 'knowledge']);
    expect(proposal.next_step).toBe('prompt');
    expect(parseAgentProposal('text')).toBeNull();
    expect(parseAgentProposal({ fields: {} })!.next_step).toBeNull();
  });

  it('reads drafted knowledge folders as the whole list, like sources', () => {
    const proposal = parseAgentProposal({
      fields: { sources: ['s1'], folders: ['f1', 7, 'f2'] },
      reasons: [
        { field: 'folders', summary: 'Live: what is filed later reaches it' },
      ],
      gaps: [{ gap_type: 'docs gap', fields: ['folders', 'tools'] }],
      dropped: [{ field: 'folders', id: 'gone', reason: 'not_found' }],
    })!;
    expect(proposal.fields).toEqual({ sources: ['s1'], folders: ['f1', 'f2'] });
    // A gap names only the fields the proposal sets.
    expect(proposal.gaps[0].fields).toEqual(['folders']);
    expect(proposal.dropped).toEqual([
      { field: 'folders', id: 'gone', reason: 'not_found' },
    ]);
    expect(parseAgentProposal({ fields: { folders: 'f1' } })!.fields).toEqual(
      {},
    );
  });

  it('drafts knowledge folders in the knowledge step, right after sources', () => {
    expect(AGENT_DRAFT_FIELDS.slice(0, 3)).toEqual([
      'sources',
      'folders',
      'tools',
    ]);
    expect(AGENT_STEP_FIELDS.knowledge).toContain('folders');
    // Compared in any order, like sources.
    expect(draftValueOf('folders', ['b', 'a'])).toEqual(['a', 'b']);
    const now = form({ sources: ['s1', 's2'], folders: ['f1'] });
    // The server takes fed sources off when it adds their folder: both change.
    const changes = planAgentPatch(
      { sources: ['s2'], folders: ['f2', 'f1', 'f2'] },
      now,
      [],
    );
    expect(changes).toEqual([
      { field: 'sources', next: ['s2'], previous: ['s1', 's2'] },
      { field: 'folders', next: ['f2', 'f1'], previous: ['f1'] },
    ]);
    expect(planAgentPatch({ folders: ['f1'] }, now, [])).toEqual([]);
  });

  it('leaves drafted folders out where the picker offers none', () => {
    const fields = { sources: ['s1'], folders: ['f1'], name: 'N' };
    expect(fieldsToApply(fields, true)).toBe(fields);
    // The server trimmed the sources for those folders: neither applies.
    expect(fieldsToApply(fields, false)).toEqual({ name: 'N' });
    expect(fieldsToApply({ sources: ['s1'] }, false)).toEqual({
      sources: ['s1'],
    });
  });

  it('reads limits, guardrail checks and topics from the safety step', () => {
    const read = (fields: Record<string, unknown>) =>
      parseAgentProposal({ fields })!.fields;
    expect(read({ limits: { mode: 'requests', value: 500 } })).toEqual({
      limits: { mode: 'requests', value: 500 },
    });
    expect(read({ limits: { mode: 'none', value: 3 } })).toEqual({
      limits: { mode: 'none' },
    });
    expect(read({ limits: { mode: 'tokens', value: -1 } })).toEqual({});
    expect(read({ limits: { mode: 'tokens', value: 1.5 } })).toEqual({});
    const pii = { check: 'pii', stage: 'input', action: 'redact' };
    expect(
      read({
        guardrails: {
          controls: [
            pii,
            { check: 'pii', stage: 'later', action: 'redact' },
            { check: 'pii', stage: 'output', action: 'erase' },
            { stage: 'input', action: 'block' },
            // Keys an object only inherits name no stage or action.
            { check: 'pii', stage: 'toString', action: 'redact' },
            { check: 'pii', stage: 'input', action: 'constructor' },
            7,
          ],
        },
      }),
    ).toEqual({ guardrails: { controls: [pii] } });
    // An older server sent check names only: the form can't tell their controls.
    expect(read({ guardrails: { checks: ['pii'] } })).toEqual({});
    expect(
      read({
        analytics: {
          topics: [
            { name: ' Tracking ', description: 'Where a parcel is.' },
            { name: '', description: 'x' },
            { name: 'Rates' },
          ],
        },
      }),
    ).toEqual({
      analytics: {
        topics: [{ name: 'Tracking', description: 'Where a parcel is.' }],
      },
    });
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
        limits: { mode: 'requests', value: 500 },
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
      'limits',
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
      next: 'creative',
      previous: 'default',
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
          limits: { mode: 'none' },
        },
        now,
        [track],
      ),
    ).toEqual([]);
  });

  // A new prompt opens in the prompt view; the form's prompt changes only
  // once it is saved there (Use this prompt).
  it('leaves the picked prompt alone for a new prompt', () => {
    expect(
      planAgentPatch(
        {
          prompt: {
            kind: 'new',
            name: 'Support',
            content: 'You help.',
            checks: [],
          },
        },
        form({ prompt: 'p9' }),
        [],
      ),
    ).toEqual([]);
  });

  it('sets one limit at a time, and none turns both off', () => {
    const tokens = form({
      limits: {
        limited_request_mode: false,
        request_limit: 20,
        limited_token_mode: true,
        token_limit: 9000,
      },
    });
    const [requests] = planAgentPatch(
      { limits: { mode: 'requests', value: 500 } },
      tokens,
      [],
    );
    expect(requests.next).toEqual({
      limited_request_mode: true,
      request_limit: 500,
      limited_token_mode: false,
      token_limit: 9000,
    });
    expect(requests.previous).toEqual(tokens.limits);
    const [none] = planAgentPatch({ limits: { mode: 'none' } }, tokens, []);
    expect(none.next).toEqual({
      limited_request_mode: false,
      request_limit: 20,
      limited_token_mode: false,
      token_limit: 9000,
    });
  });

  it('adds guardrail checks once per stage, on and in Monitor only', () => {
    const pii: { controls: GuardrailControlToAdd[] } = {
      controls: [
        { check: 'pii', stage: 'input', action: 'redact' },
        { check: 'pii', stage: 'output', action: 'redact' },
      ],
    };
    const piiAndInjection: { controls: GuardrailControlToAdd[] } = {
      controls: [
        ...pii.controls,
        { check: 'injection', stage: 'input', action: 'block' },
      ],
    };
    const [fresh] = planAgentPatch({ guardrails: piiAndInjection }, form(), []);
    const added = fresh.next as GuardrailsConfig;
    expect(added).toMatchObject({
      enabled: true,
      mode: 'monitor_only',
      block_message: DEFAULT_GUARDRAILS.block_message,
    });
    expect(
      added.controls.map((c) => [c.check, c.stage, c.action, c.enabled]),
    ).toEqual([
      ['pii', 'input', 'redact', true],
      ['pii', 'output', 'redact', true],
      ['injection', 'input', 'block', true],
    ]);
    // A PII control names what it finds, so the form can save it.
    expect(added.controls[0].settings.entities.length).toBeGreaterThan(0);
    expect(fresh.previous).toBeUndefined();

    const existing: GuardrailsConfig = {
      ...DEFAULT_GUARDRAILS,
      mode: 'scan_all',
      controls: [
        {
          check: 'pii',
          stage: 'input',
          action: 'flag',
          enabled: true,
          settings: { entities: ['EMAIL'] },
        },
      ],
    };
    const [onto] = planAgentPatch(
      { guardrails: pii },
      form({ guardrails: existing }),
      [],
    );
    const merged = onto.next as GuardrailsConfig;
    expect(merged.mode).toBe('scan_all');
    expect(merged.enabled).toBe(true);
    expect(merged.controls.map((c) => [c.stage, c.action])).toEqual([
      ['input', 'flag'],
      ['output', 'redact'],
    ]);

    // A control the agent has switched off is switched on, not left off
    // while the form shows its stage as picked.
    const [enabled] = planAgentPatch(
      { guardrails: pii },
      form({
        guardrails: {
          ...existing,
          controls: [{ ...existing.controls[0], enabled: false }],
        },
      }),
      [],
    );
    expect(
      (enabled.next as GuardrailsConfig).controls.map((c) => [
        c.stage,
        c.action,
        c.enabled,
      ]),
    ).toEqual([
      ['input', 'flag', true],
      ['output', 'redact', true],
    ]);
  });

  it('appends Insights topics, skipping a name the agent has', () => {
    const now = form({
      analytics: {
        ...DEFAULT_ANALYTICS,
        topics: [
          { id: 'abc12345', name: 'Rates', description: '', overlap: false },
        ],
      },
    });
    const [change] = planAgentPatch(
      {
        analytics: {
          topics: [
            { name: 'rates', description: 'Prices.' },
            { name: 'Customs', description: 'Papers by country.' },
          ],
        },
      },
      now,
      [],
    );
    expect(change.field).toBe('analytics');
    const topics = (change.next as AgentDraftForm['analytics']).topics;
    expect(topics.map((topic) => topic.name)).toEqual(['Rates', 'Customs']);
    expect(topics[1]).toMatchObject({
      description: 'Papers by country.',
      overlap: false,
    });
    expect(topics[1].id).toMatch(/^[a-z0-9]{8,32}$/);
    expect(
      planAgentPatch(
        { analytics: { topics: [{ name: 'RATES', description: 'x' }] } },
        now,
        [],
      ),
    ).toEqual([]);
  });

  it('compares tools by id, sources in any order and limits by value', () => {
    expect(
      agentDraftValues(form({ tools: [track], sources: ['b', 'a'] })),
    ).toMatchObject({
      tools: ['t1'],
      sources: ['a', 'b'],
      limits: {
        limited_request_mode: false,
        request_limit: null,
        limited_token_mode: false,
        token_limit: null,
      },
      guardrails: null,
    });
  });

  it('reads an untouched form as empty, and a picked source or folder as not', () => {
    expect(isAgentFormEmpty(form())).toBe(true);
    expect(isAgentFormEmpty(form({ starters: ['  '] }))).toBe(true);
    expect(isAgentFormEmpty(form({ sources: ['s1'] }))).toBe(false);
    expect(isAgentFormEmpty(form({ folders: ['f1'] }))).toBe(false);
    expect(isAgentFormEmpty(form({ prompt: 'p1' }))).toBe(false);
  });

  it('reads safety as never set with no limit and guardrails off', () => {
    expect(isSafetyUnset(form())).toBe(true);
    expect(isSafetyUnset(form({ guardrails: { ...DEFAULT_GUARDRAILS } }))).toBe(
      true,
    );
    expect(
      isSafetyUnset(
        form({ guardrails: { ...DEFAULT_GUARDRAILS, enabled: true } }),
      ),
    ).toBe(false);
    expect(
      isSafetyUnset(
        form({
          limits: {
            limited_request_mode: true,
            request_limit: 5,
            limited_token_mode: false,
          },
        }),
      ),
    ).toBe(false);
  });

  it('offers improve rows for what the agent lacks, then what fits it, at most four', () => {
    const none = { safety: false, promptDraft: false };
    // An agent with nothing yet: knowledge, a prompt of its own, starters.
    expect(improveSuggestions(form({ name: 'Help' }), none)).toEqual([
      'knowledge',
      'writePrompt',
      'starters',
    ]);
    // Limits and safety lead while they were never set, and four is the cap.
    expect(
      improveSuggestions(form({ description: 'x'.repeat(200) }), {
        ...none,
        safety: true,
      }),
    ).toEqual(['safety', 'knowledge', 'writePrompt', 'starters']);
    // A complete agent with its own prompt: tighten it; a long description: shorten it.
    const complete = form({
      description: 'x'.repeat(200),
      sources: ['s1'],
      starters: ['Hi'],
      prompt: 'p1',
    });
    expect(improveSuggestions(complete, none)).toEqual([
      'shorter',
      'tightenPrompt',
    ]);
    // A short description isn't worth shortening.
    expect(
      improveSuggestions(
        { ...complete, description: 'Answers shipping questions.' },
        none,
      ),
    ).toEqual(['tightenPrompt']);
    // A tool counts as something to answer with; unsaved prompt text is a prompt of its own.
    expect(
      improveSuggestions(form({ tools: [track], starters: ['Hi'] }), {
        ...none,
        promptDraft: true,
      }),
    ).toEqual(['tightenPrompt']);
    // A knowledge folder is something to answer from too.
    expect(
      improveSuggestions(form({ folders: ['f1'], starters: ['Hi'] }), none),
    ).toEqual(['writePrompt']);
  });

  it('sends the form and the step as the contract context', () => {
    expect(
      agentDraftContext(
        '',
        form({
          name: 'N',
          tools: [track],
          starters: ['Hi'],
          prompt: 'p1',
          limits: {
            limited_request_mode: false,
            limited_token_mode: true,
            token_limit: 50000,
          },
          guardrails: {
            ...DEFAULT_GUARDRAILS,
            enabled: true,
            controls: [
              {
                check: 'PII',
                stage: 'input',
                action: 'redact',
                enabled: true,
                settings: {},
              },
              {
                check: 'pii',
                stage: 'output',
                action: 'redact',
                enabled: true,
                settings: {},
              },
            ],
          },
          analytics: {
            ...DEFAULT_ANALYTICS,
            topics: [
              {
                id: 'abc12345',
                name: 'Rates',
                description: '',
                overlap: false,
              },
              {
                id: 'def67890',
                name: 'Asks for a person',
                description: '',
                overlap: true,
              },
            ],
            hidden_folders: ['overview'],
          },
        }),
        {
          step: 'knowledge',
          earlier: ['A shipping agent'],
          starter: 'website',
        },
        { name: 'P', content: 'C' },
      ),
    ).toEqual({
      agent_id: null,
      step: 'knowledge',
      earlier: ['A shipping agent'],
      starter: 'website',
      form: {
        name: 'N',
        description: '',
        agent_type: 'classic',
        sources: [],
        folders: [],
        folders_offered: true,
        tools: ['t1'],
        // The prompt view's unsaved text goes beside the picked prompt.
        prompt_id: 'p1',
        prompt_draft: { name: 'P', content: 'C' },
        starters: ['Hi'],
        limits: { mode: 'tokens', value: 50000 },
        guardrails: {
          enabled: true,
          mode: 'monitor_only',
          controls: [
            { check: 'pii', stage: 'input' },
            { check: 'pii', stage: 'output' },
          ],
        },
        // Folders and overlapping topics change how many topics fit.
        analytics: {
          enabled: true,
          topics: [
            { name: 'Rates', overlap: false },
            { name: 'Asks for a person', overlap: true },
          ],
          hidden_folders: ['overview'],
        },
      },
    });
    // Improve mode began from no starting point.
    expect(
      agentDraftContext('a1', form(), { step: null, earlier: [] }, null)
        .starter,
    ).toBeNull();
    expect(
      agentDraftContext('a1', form(), { step: null, earlier: [] }, null).form,
    ).toMatchObject({
      prompt_draft: null,
      limits: { mode: 'none', value: null },
      guardrails: { enabled: false, mode: 'monitor_only', controls: [] },
    });
    // The form's knowledge folders go beside its sources; an agent of
    // another workspace has a picker that offers none.
    expect(
      agentDraftContext(
        'a1',
        form({ sources: ['s1'], folders: ['f1', 'f2'] }),
        { step: null, earlier: [] },
        null,
      ).form,
    ).toMatchObject({
      sources: ['s1'],
      folders: ['f1', 'f2'],
      folders_offered: true,
    });
    expect(
      agentDraftContext(
        'a1',
        form({ folders: ['f1'] }),
        { step: null, earlier: [] },
        null,
        {},
        false,
      ).form,
    ).toMatchObject({ folders: ['f1'], folders_offered: false });
    // A control switched off runs no check: the recipe may offer it again,
    // and a check on at one stage only can get its other stage.
    expect(
      agentDraftContext(
        'a1',
        form({
          guardrails: {
            ...DEFAULT_GUARDRAILS,
            enabled: true,
            controls: [
              {
                check: 'pii',
                stage: 'input',
                action: 'redact',
                enabled: false,
                settings: {},
              },
              {
                check: 'injection',
                stage: 'input',
                action: 'block',
                enabled: true,
                settings: {},
              },
            ],
          },
        }),
        { step: 'safety', earlier: [] },
        null,
      ).form.guardrails.controls,
    ).toEqual([{ check: 'injection', stage: 'input' }]);
  });

  it('labels drafted and dropped knowledge folders as their own field', () => {
    const proposal = parseAgentProposal({
      fields: { sources: ['s2'], folders: ['f1'] },
      reasons: [
        { field: 'sources', summary: 'The handbook' },
        { field: 'folders', summary: 'Live: new policies reach it' },
      ],
      dropped: [{ field: 'folders', id: 'gone', reason: 'not_found' }],
    })!;
    const fields: unknown[] = [];
    const record = ((key: string, options?: Record<string, unknown>) => {
      if (key === 'drafter.agent.droppedLine') fields.push(options?.field);
      return key;
    }) as never;
    const { rows } = agentProposalSummary(proposal, record, [
      'sources',
      'folders',
    ]);
    expect(rows.map((row) => [row.key, row.label])).toEqual([
      ['sources-0', 'agents.form.labels.sources'],
      ['folders-1', 'drafter.agent.fields.folders'],
    ]);
    expect(fields).toEqual(['drafter.agent.fields.folders']);
  });

  it('gives a reason row only for the fields the draft changed', () => {
    const proposal = parseAgentProposal({
      fields: { name: 'Shipping help', agent_type: 'classic' },
      reasons: [
        { field: 'name', summary: 'Says what it does', detail: 'More' },
        { field: 'agent_type', summary: 'Classic suits Q&A' },
        { field: 'model', summary: 'Not a draft field' },
      ],
      dropped: [
        { field: 'tools', reason: 'not_found' },
        { field: 'limits', reason: 'not_allowed' },
      ],
    })!;
    const { rows, dropped } = agentProposalSummary(proposal, t, ['name']);
    expect(rows).toEqual([
      {
        key: 'name-0',
        label: 'agents.form.labels.name',
        summary: 'Says what it does',
      },
    ]);
    // What the server left out is listed whatever changed.
    expect(dropped).toEqual([
      'drafter.agent.droppedLine',
      'drafter.agent.droppedLine',
    ]);
    // A field this step doesn't take has a reason of its own.
    const reasons: string[] = [];
    const record = ((key: string) => {
      if (key.startsWith('drafter.agent.droppedReasons.')) reasons.push(key);
      return key;
    }) as never;
    agentProposalSummary(
      parseAgentProposal({
        fields: {},
        dropped: [
          { field: 'prompt', reason: 'other_step' },
          { field: 'tools', reason: 'made_up' },
        ],
      })!,
      record,
    );
    expect(reasons).toEqual([
      'drafter.agent.droppedReasons.other_step',
      'drafter.agent.droppedReasons.other',
    ]);
    // Without a record of the changes, every reason shows.
    expect(agentProposalSummary(proposal, t).rows).toHaveLength(3);
  });

  // The prompt it wrote isn't on the form yet: one row says so, with its
  // length, in place of the prompt's reason.
  it('gives a new prompt one row with its word count', () => {
    const proposal = parseAgentProposal({
      fields: {
        prompt: {
          kind: 'new',
          name: 'Support',
          content: ' You help\n people. ',
          checks: ['citations_removed', 'nope'],
        },
        starters: ['Hi'],
      },
      reasons: [
        { field: 'prompt', summary: 'Written for customers' },
        { field: 'starters', summary: 'One per task' },
      ],
    })!;
    // What it does to the prompt it replaces, as edits carry it.
    expect(proposal.fields.prompt).toMatchObject({
      kind: 'new',
      checks: ['citations_removed'],
    });
    expect(agentProposalSummary(proposal, t, ['starters']).rows).toEqual([
      {
        key: 'prompt-new',
        label: 'agents.form.sections.prompt',
        summary: 'drafter.agent.prompt.wrote:3',
      },
      {
        key: 'starters-0',
        label: 'agents.form.sections.starters',
        summary: 'One per task',
      },
    ]);
  });

  it('reads edits to a saved prompt and gives them one row', () => {
    const proposal = parseAgentProposal({
      fields: {
        prompt: {
          kind: 'edit',
          id: 'p1',
          edits: [
            { id: 'e1', find: 'Be brief.', replace: 'Be short.', reason: 'r' },
            { id: 'e2', find: 7 },
          ],
          checks: ['to_template', 'nope'],
        },
      },
      reasons: [{ field: 'prompt', summary: 'Shorter answers' }],
    })!;
    expect(proposal.fields.prompt).toEqual({
      kind: 'edit',
      id: 'p1',
      edits: [
        { id: 'e1', find: 'Be brief.', replace: 'Be short.', reason: 'r' },
      ],
      checks: ['to_template'],
    });
    // The prompt isn't changed on the form: its row counts the changes to review.
    expect(agentProposalSummary(proposal, t, []).rows).toEqual([
      {
        key: 'prompt-edits',
        label: 'agents.form.sections.prompt',
        summary: 'drafter.agent.prompt.changes:1',
      },
    ]);
    // Once the view held the text, the row counts the changes that fit it
    // and a line says how many didn't; with none left there is no row.
    const twice = parseAgentProposal({
      fields: {
        prompt: {
          kind: 'edit',
          id: 'p1',
          edits: [
            { id: 'e1', find: 'a', replace: 'b', reason: 'r' },
            { id: 'e2', find: 'c', replace: 'd', reason: 'r' },
          ],
        },
      },
    })!;
    expect(agentProposalSummary(twice, t, [], 1)).toEqual({
      rows: [
        {
          key: 'prompt-edits',
          label: 'agents.form.sections.prompt',
          summary: 'drafter.agent.prompt.changes:1',
        },
      ],
      dropped: ['drafter.agent.prompt.unfit:1'],
    });
    expect(agentProposalSummary(twice, t, [], 0).rows).toEqual([]);
    expect(
      parseAgentProposal({
        fields: { prompt: { kind: 'edit', id: 'p1', edits: [] } },
      })!.fields.prompt,
    ).toBeUndefined();
  });

  it('names what each finished step holds', () => {
    const filled = form({
      name: 'Shipping help desk',
      sources: ['s1', 's2'],
      tools: [track],
      starters: ['Where is it?', 'Refunds?'],
      limits: {
        limited_request_mode: true,
        request_limit: 500,
        limited_token_mode: false,
      },
      guardrails: {
        ...DEFAULT_GUARDRAILS,
        enabled: true,
        controls: [
          {
            check: 'pii',
            stage: 'input',
            action: 'redact',
            enabled: true,
            settings: {},
          },
          {
            check: 'pii',
            stage: 'output',
            action: 'redact',
            enabled: true,
            settings: {},
          },
          {
            check: 'injection',
            stage: 'input',
            action: 'block',
            enabled: true,
            settings: {},
          },
        ],
      },
    });
    expect(agentStepResult('basics', filled, t, '')).toBe('Shipping help desk');
    // Not the page's fallback name: the agent has none yet.
    expect(agentStepResult('basics', form(), t, '')).toBe(
      'drafter.agent.build.result.noName',
    );
    expect(agentStepResult('knowledge', filled, t, '')).toBe(
      'drafter.counts.sources:2 and Tracking API',
    );
    expect(agentStepResult('prompt', filled, t, 'Support')).toBe(
      'Support and drafter.agent.build.result.starters:2',
    );
    expect(agentStepResult('safety', filled, t, '')).toBe(
      'drafter.agent.build.result.requests:500 and drafter.agent.build.result.checks:2',
    );
    // Listed the way the language lists things.
    const language = i18next.language;
    i18next.language = 'ja';
    try {
      expect(agentStepResult('prompt', filled, t, 'Support')).toBe(
        'Support、drafter.agent.build.result.starters:2',
      );
    } finally {
      i18next.language = language;
    }
    expect(agentStepResult('knowledge', form(), t, '')).toBe(
      'drafter.agent.build.result.none',
    );
    // Knowledge folders count beside sources and tools, or on their own.
    expect(
      agentStepResult('knowledge', { ...filled, folders: ['f1'] }, t, ''),
    ).toBe(
      'drafter.counts.sources:2, drafter.counts.folders:1, and Tracking API',
    );
    expect(
      agentStepResult('knowledge', form({ folders: ['f1', 'f2'] }), t, ''),
    ).toBe('drafter.counts.folders:2');
    expect(agentStepResult('safety', form(), t, '')).toBe(
      'drafter.agent.build.result.noLimit',
    );
  });

  it('reads the gaps an improve acts on, keeping only fields it sets and links that exist', () => {
    const proposal = parseAgentProposal({
      fields: { prompt: { kind: 'existing', id: 'p1' }, starters: ['Hi'] },
      gaps: [
        {
          topic: 'Order status',
          gap_type: 'needs account data',
          expected: 31,
          turns: 96,
          previous: null,
          example: ' Where is shipment MRD-48213? ',
          fields: ['prompt', 'guardrails', 'nope'],
          needs: '  ',
          links: [
            { kind: 'source', id: 's1', name: 'Claims policy' },
            { kind: 'source', id: '' },
            { kind: 'logs', label: 'docs_gap' },
            { kind: 'logs', label: 'everything' },
            { kind: 'web', url: 'https://example.com' },
          ],
        },
        { topic: 3, gap_type: 'docs missing' },
        { gap_type: '' },
        'junk',
      ],
    })!;
    expect(proposal.gaps).toEqual([
      {
        topic: 'Order status',
        gap_type: 'needs account data',
        expected: 31,
        turns: 96,
        previous: null,
        example: 'Where is shipment MRD-48213?',
        fields: ['prompt'],
        needs: null,
        links: [
          { kind: 'source', id: 's1', name: 'Claims policy' },
          { kind: 'logs', label: 'docs_gap' },
        ],
      },
    ]);
    expect(parseAgentProposal({ fields: {} })!.gaps).toEqual([]);
  });

  it('words a gap row from the data alone, as Insights names it', () => {
    const tr = ((key: string, options?: Record<string, unknown>) => {
      if (!options) return key;
      const shown = Object.entries(options)
        .filter(([name]) => name !== 'interpolation' && name !== 'count')
        .map(([name, value]) => `${name}=${value}`)
        .join(',');
      return `${key}(${shown})`;
    }) as never;
    const row = {
      topic: 'Returns & claims',
      gap_type: 'docs missing',
      expected: 23,
      turns: 160,
      previous: 19,
    };
    const gap = 'settings.analytics.insights.options.gapType.docsMissing';
    expect(gapTitle(tr, row)).toBe('Returns & claims');
    expect(gapTitle(tr, { ...row, topic: null })).toBe(gap);
    // A page's gap, named as the Docs gaps row it came from showed it.
    expect(
      gapTitle(
        tr,
        { ...row, topic: 'App Configuration | DocsGPT Docs' },
        'App Configuration',
      ),
    ).toBe('App Configuration');
    expect(gapLine(tr, row)).toBe(
      `drafter.agent.insights.gapLine(gap=${gap},expected=23,formatted=160)` +
        ' · drafter.agent.insights.upFrom(previous=19)',
    );
    // No change, no earlier window, and fewer than before.
    expect(gapLine(tr, { ...row, previous: 23.2 })).not.toContain('From');
    expect(gapLine(tr, { ...row, previous: null })).not.toContain('From');
    expect(gapLine(tr, { ...row, previous: 30 })).toContain(
      'drafter.agent.insights.downFrom(previous=30)',
    );
    expect(gapRequest(tr, row)).toBe(
      `drafter.agent.insights.fixIn(gap=${gap},topic=Returns & claims)`,
    );
    expect(gapRequest(tr, { ...row, topic: null })).toBe(
      `drafter.agent.insights.fix(gap=${gap})`,
    );
    // The topic question's catch-all reads as Insights shows it.
    expect(gapTitle(tr, { ...row, topic: 'none of these' })).toBe(
      'settings.analytics.insights.panels.noneOfThese',
    );
    // A gap type a newer model added reads as its own key.
    expect(gapTitle(tr, { ...row, topic: null, gap_type: 'new kind' })).toBe(
      'new kind',
    );
  });

  it('sends the gap or conversation an improve started from, only for a saved agent outside a step', () => {
    const focus = {
      gap: { topic: 'Order status', gap_type: 'needs account data' },
      conversation_id: 'c1',
      message_id: 'm1',
    };
    const improving = agentDraftContext(
      'a1',
      form(),
      { step: null, earlier: [] },
      null,
      focus,
    );
    expect(improving.gap).toEqual(focus.gap);
    expect(improving.conversation_id).toBe('c1');
    expect(improving.message_id).toBe('m1');
    const fresh = agentDraftContext(
      null,
      form(),
      { step: null, earlier: [] },
      null,
      focus,
    );
    expect(fresh).not.toHaveProperty('gap');
    expect(fresh).not.toHaveProperty('conversation_id');
    expect(fresh).not.toHaveProperty('message_id');
    expect(
      agentDraftContext(
        'a1',
        form(),
        { step: 'safety', earlier: [] },
        null,
        focus,
      ),
    ).not.toHaveProperty('gap');
    expect(
      agentDraftContext('a1', form(), { step: null, earlier: [] }, null),
    ).not.toHaveProperty('gap');
  });
  it('leaves a field the user changed while the turn ran, and records the rest', () => {
    const sent = form({ name: 'Old', description: 'Was' });
    const now = form({ name: 'Typed', description: 'Was' });
    const plan = planAgentProposal(
      { name: 'Drafted', description: 'New' },
      now,
      sent,
      [],
      // Drafted before: its Undo goes back to before the first draft.
      (field) => (field === 'description' ? { previous: 'First' } : null),
    );
    expect(plan.changes.map((change) => change.field)).toEqual(['description']);
    expect(plan.applied).toEqual([
      { field: 'description', previous: 'First', applied: 'New' },
    ]);
    expect(plan.kept).toEqual([
      { field: 'name', previous: 'Old', applied: 'Drafted' },
    ]);
    // A later proposal of the same turn takes this one's values as sent.
    expect(plan.sent).toMatchObject({ name: 'Old', description: 'New' });
  });

  it('keeps sources and folders together when either moved while the turn ran', () => {
    // Sent with sources S and T; folder H ticked by hand meanwhile. The
    // server took S off because the drafted folder G feeds it.
    const sent = form({ sources: ['S', 'T'], description: 'Was' });
    const now = form({
      sources: ['S', 'T'],
      folders: ['H'],
      description: 'Was',
    });
    const plan = planAgentProposal(
      { folders: ['G'], sources: ['T'], description: 'New' },
      now,
      sent,
      [],
      () => null,
    );
    expect(plan.changes.map((change) => change.field)).toEqual(['description']);
    expect(plan.kept).toEqual([
      { field: 'sources', previous: ['S', 'T'], applied: ['T'] },
      { field: 'folders', previous: [], applied: ['G'] },
    ]);
    expect(plan.sent).toMatchObject({ sources: ['S', 'T'], folders: [] });
    // "You changed Knowledge… in the form" names what still differs.
    expect(
      editedSinceFields(plan.applied, plan.kept, agentDraftValues(now)),
    ).toEqual(['sources', 'folders']);
    // Sources alone were normalised against the folders sent: kept too.
    const sourcesOnly = planAgentProposal(
      { sources: ['T'] },
      now,
      sent,
      [],
      () => null,
    );
    expect(sourcesOnly.changes).toEqual([]);
    expect(sourcesOnly.kept.map((change) => change.field)).toEqual(['sources']);
    // Sources picked by hand hold back drafted folders the same way.
    const picked = planAgentProposal(
      { folders: ['G'] },
      form({ sources: ['S', 'T', 'U'] }),
      sent,
      [],
      () => null,
    );
    expect(picked.changes).toEqual([]);
    expect(picked.kept.map((change) => change.field)).toEqual(['folders']);
  });

  it('tells an undone field from an edited one', () => {
    const change = { field: 'name' as const, previous: '', applied: 'Bot' };
    const values = (name: string) => agentDraftValues(form({ name }));
    expect(undoneKindOf(change, values(''))).toBe('empty');
    expect(undoneKindOf({ ...change, previous: 'Old' }, values('Old'))).toBe(
      'previous',
    );
    expect(undoneKindOf(change, values('Bot'))).toBeNull();
    expect(undoneKindOf(change, values('Typed'))).toBeNull();
    expect(undoneKindOf(undefined, values(''))).toBeNull();
    // Typed over since, applied or kept, it counts as edited.
    expect(editedSinceFields([change], [], values('Typed'))).toEqual(['name']);
    expect(editedSinceFields([change], [], values(''))).toEqual([]);
    expect(
      editedSinceFields(
        [],
        [{ field: 'name', previous: 'Old', applied: 'Bot' }],
        values('Typed'),
      ),
    ).toEqual(['name']);
  });
});
