import type { TFunction } from 'i18next';

import type { ProposalReasonRow } from '../drafter/ProposalSummary';
import { cleanStarters } from './starters';
import type { ToolSummary } from './types';

/** A prompt the drafter wrote for the form, created when the agent saves. */
export type PendingPrompt = { name: string; content: string };

/** The Prompt field's whole value: the picked prompt, or a pending one over it. */
export type AgentPromptValue = {
  prompt_id: string;
  pending: PendingPrompt | null;
};

/** The agent fields the drafter may fill, in the order a draft applies them. */
export const AGENT_DRAFT_FIELDS = [
  'sources',
  'tools',
  'agent_type',
  'name',
  'description',
  'starters',
  'prompt',
] as const;
export type AgentDraftField = (typeof AGENT_DRAFT_FIELDS)[number];

const AGENT_TYPES = ['classic', 'research'];

/** `proposal.fields` of an agent draft (an omitted field is unchanged). */
export type AgentProposalFields = {
  name?: string;
  description?: string;
  agent_type?: string;
  sources?: string[];
  tools?: string[];
  prompt?:
    | { kind: 'existing'; id: string }
    | { kind: 'new'; name: string; content: string };
  starters?: string[];
};

export type AgentProposal = {
  message?: string;
  fields: AgentProposalFields;
  reasons: { field: string; summary: string; detail?: string | null }[];
  notes: string[];
  dropped: { field: string; id?: string; reason?: string }[];
};

/** The form as a draft reads and writes it. */
export type AgentDraftForm = {
  name: string;
  description: string;
  agent_type: string;
  sources: string[];
  tools: ToolSummary[];
  starters: string[];
  prompt: AgentPromptValue;
};

/** One field a draft changes: what it writes, and what undo puts back. */
export type AgentDraftChange = {
  [K in AgentDraftField]: {
    field: K;
    next: AgentDraftForm[K];
    previous: AgentDraftForm[K];
  };
}[AgentDraftField];

const isString = (value: unknown): value is string => typeof value === 'string';
const stringList = (value: unknown): string[] | undefined =>
  Array.isArray(value) ? value.filter(isString) : undefined;

/**
 * Read an agent proposal defensively: anything malformed is left out, so a
 * bad field never reaches the form.
 *
 * Args:
 *   raw: The `proposal` of a `proposal` event.
 *
 * Returns:
 *   The proposal, or null when it isn't one.
 */
export function parseAgentProposal(raw: unknown): AgentProposal | null {
  if (!raw || typeof raw !== 'object') return null;
  const source = raw as Record<string, unknown>;
  const rawFields = (source.fields ?? {}) as Record<string, unknown>;
  if (typeof rawFields !== 'object') return null;
  const fields: AgentProposalFields = {};
  if (isString(rawFields.name)) fields.name = rawFields.name;
  if (isString(rawFields.description))
    fields.description = rawFields.description;
  if (
    isString(rawFields.agent_type) &&
    AGENT_TYPES.includes(rawFields.agent_type)
  )
    fields.agent_type = rawFields.agent_type;
  const sources = stringList(rawFields.sources);
  if (sources) fields.sources = sources;
  const tools = stringList(rawFields.tools);
  if (tools) fields.tools = tools;
  const starters = stringList(rawFields.starters);
  if (starters) fields.starters = starters;
  const prompt = rawFields.prompt as Record<string, unknown> | undefined;
  if (prompt?.kind === 'existing' && isString(prompt.id) && prompt.id)
    fields.prompt = { kind: 'existing', id: prompt.id };
  else if (
    prompt?.kind === 'new' &&
    isString(prompt.name) &&
    isString(prompt.content) &&
    prompt.content.trim()
  )
    fields.prompt = {
      kind: 'new',
      name: prompt.name.trim(),
      content: prompt.content,
    };
  const list = (value: unknown) => (Array.isArray(value) ? value : []);
  return {
    message: isString(source.message) ? source.message : undefined,
    fields,
    reasons: list(source.reasons).filter(
      (reason): reason is AgentProposal['reasons'][number] =>
        !!reason && isString(reason.field) && isString(reason.summary),
    ),
    notes: list(source.notes).filter(isString),
    dropped: list(source.dropped).filter(
      (item): item is AgentProposal['dropped'][number] =>
        !!item && isString(item.field),
    ),
  };
}

/**
 * A field's value in a comparable shape: tools by id in order, sources by id
 * in any order, starters as a save cleans them.
 */
export function draftValueOf<K extends AgentDraftField>(
  field: K,
  value: AgentDraftForm[K],
): unknown {
  if (field === 'tools') return (value as ToolSummary[]).map((tool) => tool.id);
  if (field === 'sources') return [...(value as string[])].sort();
  if (field === 'starters') return cleanStarters(value as string[]);
  return value;
}

/**
 * The comparable value of every drafted field, for useDraftedFields: a field
 * whose value moves off what the draft set was edited by hand.
 */
export function agentDraftValues(
  form: AgentDraftForm,
): Record<AgentDraftField, unknown> {
  return Object.fromEntries(
    AGENT_DRAFT_FIELDS.map((field) => [
      field,
      draftValueOf(field, form[field]),
    ]),
  ) as Record<AgentDraftField, unknown>;
}

const same = <K extends AgentDraftField>(
  field: K,
  a: AgentDraftForm[K],
  b: AgentDraftForm[K],
) =>
  JSON.stringify(draftValueOf(field, a)) ===
  JSON.stringify(draftValueOf(field, b));

/**
 * Work out what a proposal changes on the form, field by field in the order
 * they apply (sources, tools, type, name, description, starters, prompt).
 * Fields the proposal leaves out, or sets to what the form already holds,
 * are not changes. A tool id the caller has no row for is left out.
 *
 * Args:
 *   fields: The proposal's fields.
 *   form: The form now.
 *   toolOptions: Tools the form can name ({id, name, display_name}).
 *
 * Returns:
 *   The changes, each with its previous value for undo.
 */
export function planAgentPatch(
  fields: AgentProposalFields,
  form: AgentDraftForm,
  toolOptions: ToolSummary[],
): AgentDraftChange[] {
  const next: Partial<AgentDraftForm> = {};
  if (fields.sources) next.sources = [...new Set(fields.sources)];
  if (fields.tools) {
    const byId = new Map<string, ToolSummary>();
    [...toolOptions, ...form.tools].forEach((tool) => byId.set(tool.id, tool));
    next.tools = [...new Set(fields.tools)]
      .map((id) => byId.get(id))
      .filter((tool): tool is ToolSummary => !!tool);
  }
  if (fields.agent_type) next.agent_type = fields.agent_type;
  if (fields.name !== undefined) next.name = fields.name;
  if (fields.description !== undefined) next.description = fields.description;
  if (fields.starters) next.starters = cleanStarters(fields.starters);
  if (fields.prompt)
    next.prompt =
      fields.prompt.kind === 'existing'
        ? { prompt_id: fields.prompt.id, pending: null }
        : {
            prompt_id: form.prompt.prompt_id,
            pending: {
              name: fields.prompt.name,
              content: fields.prompt.content,
            },
          };

  const changes: AgentDraftChange[] = [];
  AGENT_DRAFT_FIELDS.forEach((field) => {
    const value = next[field];
    if (value === undefined || same(field, value, form[field])) return;
    changes.push({ field, next: value, previous: form[field] } as never);
  });
  return changes;
}

/** Whether the form holds nothing a user typed or picked: "Draft", not "Improve". */
export function isAgentFormEmpty(form: AgentDraftForm): boolean {
  return (
    !form.name.trim() &&
    !form.description.trim() &&
    form.sources.length === 0 &&
    form.tools.length === 0 &&
    cleanStarters(form.starters).length === 0 &&
    form.prompt.pending === null &&
    (!form.prompt.prompt_id || form.prompt.prompt_id === 'default')
  );
}

/**
 * The agent recipe's `context`: the form as it is now.
 *
 * Args:
 *   agentId: The saved agent's id, or null for a new one.
 *   form: The form now.
 *
 * Returns:
 *   `{ agent_id, form }` as the drafter contract describes it.
 */
export function agentDraftContext(
  agentId: string | null,
  form: AgentDraftForm,
) {
  return {
    agent_id: agentId || null,
    form: {
      name: form.name,
      description: form.description,
      agent_type: form.agent_type,
      sources: form.sources,
      tools: form.tools.map((tool) => tool.id),
      prompt_id: form.prompt.prompt_id || null,
      pending_prompt: form.prompt.pending,
      starters: form.starters,
    },
  };
}

/** The form label of each drafted field (existing agent-form keys). */
export const AGENT_FIELD_LABEL_KEYS: Record<AgentDraftField, string> = {
  name: 'agents.form.labels.name',
  description: 'agents.form.labels.description',
  agent_type: 'agents.form.sections.agentType',
  sources: 'agents.form.labels.sources',
  tools: 'agents.form.sections.tools',
  prompt: 'agents.form.sections.prompt',
  starters: 'agents.form.sections.starters',
};

const DROPPED_REASONS = ['not_found', 'no_access', 'invalid'];

/**
 * The proposal summary's rows and lines: a reason per field, and what the
 * server left out.
 *
 * Args:
 *   proposal: The parsed proposal.
 *   t: The translator.
 *
 * Returns:
 *   `rows` for ProposalSummary and `dropped` lines.
 */
export function agentProposalSummary(
  proposal: AgentProposal,
  t: TFunction,
): { rows: ProposalReasonRow[]; dropped: string[] } {
  const labelOf = (field: string) =>
    field in AGENT_FIELD_LABEL_KEYS
      ? t(AGENT_FIELD_LABEL_KEYS[field as AgentDraftField])
      : field;
  const rows = proposal.reasons.map((reason, index) => ({
    key: `${reason.field}-${index}`,
    label: labelOf(reason.field),
    summary: reason.summary,
    detail: reason.detail ?? null,
  }));
  const dropped = proposal.dropped.map((item) =>
    t('drafter.agent.droppedLine', {
      field: labelOf(item.field),
      reason: t(
        `drafter.agent.droppedReasons.${
          DROPPED_REASONS.includes(item.reason ?? '') ? item.reason : 'other'
        }`,
      ),
      interpolation: { escapeValue: false },
    }),
  );
  return { rows, dropped };
}
