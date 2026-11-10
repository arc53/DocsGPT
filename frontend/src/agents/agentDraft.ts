import type { TFunction } from 'i18next';

import {
  type PromptCheck,
  type PromptEdit,
  readPromptChecks,
  readPromptEdits,
} from '../drafter/promptDraft';
import type { AgentGapRow } from '../drafter/drafterApi';
import type { ProposalReasonRow } from '../drafter/ProposalSummary';
import type { DrafterStarter } from '../drafter/starters';
import {
  joinList,
  NONE_OF_THESE,
  optionName,
} from '../settings/insights/format';
import { isLogLabel, type LogLabel } from '../settings/logsLinks';
import { formatCount } from '../utils/dateTimeUtils';
import { getToolDisplayName } from '../utils/toolUtils';
import { newTopicId } from './analyticsConfig';
import {
  ACTION_KEYS,
  DEFAULT_GUARDRAILS,
  defaultControlSettings,
  STAGE_KEYS,
} from './components/GuardrailsSection';
import { cleanStarters } from './starters';
import type {
  AnalyticsConfig,
  GuardrailAction,
  GuardrailControl,
  GuardrailsConfig,
  GuardrailStage,
  ToolSummary,
} from './types';

/**
 * A prompt's unsaved name and text, as the prompt view holds them; `id` is
 * the saved prompt they change (none for a new prompt).
 */
export type PromptDraft = { name: string; content: string; id?: string };

/** The agent's request and token limits, as the form holds them. */
export type AgentLimitsValue = {
  limited_request_mode: boolean;
  request_limit?: number;
  limited_token_mode: boolean;
  token_limit?: number;
};

/** The guided build's steps, in order (STEPS in agent_recipe.py). */
export const AGENT_BUILD_STEPS = [
  'basics',
  'knowledge',
  'prompt',
  'safety',
] as const;
export type AgentBuildStep = (typeof AGENT_BUILD_STEPS)[number];

/** The agent fields the drafter may fill, in the order a draft applies them. */
export const AGENT_DRAFT_FIELDS = [
  'sources',
  'tools',
  'agent_type',
  'name',
  'description',
  'starters',
  'prompt',
  'limits',
  'guardrails',
  'analytics',
] as const;
export type AgentDraftField = (typeof AGENT_DRAFT_FIELDS)[number];

/** The fields each step sets (STEP_FIELDS in agent_recipe.py). */
export const AGENT_STEP_FIELDS: Record<
  AgentBuildStep,
  readonly AgentDraftField[]
> = {
  basics: ['name', 'description'],
  knowledge: ['sources', 'tools', 'agent_type'],
  prompt: ['prompt', 'starters'],
  safety: ['limits', 'guardrails', 'analytics'],
};

const AGENT_TYPES = ['classic', 'research'];

/** A guardrail control a draft adds: which check runs where, and what it does. */
export type GuardrailControlToAdd = {
  check: string;
  stage: GuardrailStage;
  action: GuardrailAction;
};

/** `proposal.fields` of an agent draft (an omitted field is unchanged). */
export type AgentProposalFields = {
  name?: string;
  description?: string;
  agent_type?: string;
  sources?: string[];
  tools?: string[];
  prompt?:
    | { kind: 'existing'; id: string }
    /** A prompt it wrote; `checks` say what it does to the one it replaces. */
    | { kind: 'new'; name: string; content: string; checks: PromptCheck[] }
    /** Changes to the agent's own saved prompt, reviewed in the prompt view. */
    | { kind: 'edit'; id: string; edits: PromptEdit[]; checks: PromptCheck[] };
  starters?: string[];
  /** Request and token limits are either-or; `none` turns both off. */
  limits?: { mode: 'requests' | 'tokens'; value: number } | { mode: 'none' };
  /**
   * The controls of the menu checks to add, as the server reads them from
   * GUARDRAIL_MENU in agent_recipe.py.
   */
  guardrails?: { controls: GuardrailControlToAdd[] };
  /** Insights topics to add. */
  analytics?: { topics: { name: string; description: string }[] };
};

/** Where a gap's fix sends the user: a source to add a page to, or Logs. */
export type AgentGapLink =
  | { kind: 'source'; id: string; name: string }
  | { kind: 'logs'; label: LogLabel };

/**
 * One gap an improve proposal acts on: the summary row it came from (the
 * server's counts), a question it read, the fields its fix set, and what it
 * can't fix itself.
 */
export type AgentProposalGap = AgentGapRow & {
  /** One question the model read for it. */
  example: string;
  /** The proposal's fields its fix set. */
  fields: AgentDraftField[];
  /** What the user has to do ("Add a page… then sync the source."). */
  needs: string | null;
  links: AgentGapLink[];
};

export type AgentProposal = {
  message?: string;
  fields: AgentProposalFields;
  /** The gaps from Insights it acts on (improve mode); none otherwise. */
  gaps: AgentProposalGap[];
  reasons: { field: string; summary: string }[];
  notes: string[];
  dropped: { field: string; id?: string; reason?: string }[];
  /** The steps this proposal filled, in order (empty in improve mode). */
  steps: AgentBuildStep[];
  /** The first later step it left to do; null when none is left. */
  next_step: AgentBuildStep | null;
};

/** The form as a draft reads and writes it. */
export type AgentDraftForm = {
  name: string;
  description: string;
  agent_type: string;
  sources: string[];
  tools: ToolSummary[];
  starters: string[];
  /** The picked prompt's id. */
  prompt: string;
  limits: AgentLimitsValue;
  /** `config.guardrails`; undefined while the agent has none. */
  guardrails: GuardrailsConfig | undefined;
  /** `config.analytics`, read with its defaults. */
  analytics: AnalyticsConfig;
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
const isStep = (value: unknown): value is AgentBuildStep =>
  AGENT_BUILD_STEPS.includes(value as AgentBuildStep);

function parseLimits(raw: unknown): AgentProposalFields['limits'] {
  const limits = raw as Record<string, unknown> | undefined;
  if (limits?.mode === 'none') return { mode: 'none' };
  if (
    (limits?.mode === 'requests' || limits?.mode === 'tokens') &&
    Number.isInteger(limits.value) &&
    (limits.value as number) > 0
  )
    return { mode: limits.mode, value: limits.value as number };
  return undefined;
}

function parseGuardrails(raw: unknown): AgentProposalFields['guardrails'] {
  const controls = (raw as { controls?: unknown } | undefined)?.controls;
  if (!Array.isArray(controls)) return undefined;
  const parsed = controls.filter(
    (control): control is GuardrailControlToAdd =>
      !!control &&
      isString(control.check) &&
      !!control.check &&
      control.stage in STAGE_KEYS &&
      control.action in ACTION_KEYS,
  );
  return parsed.length > 0
    ? {
        controls: parsed.map(({ check, stage, action }) => ({
          check,
          stage,
          action,
        })),
      }
    : undefined;
}

function parseTopics(raw: unknown): AgentProposalFields['analytics'] {
  const topics = (raw as { topics?: unknown } | undefined)?.topics;
  if (!Array.isArray(topics)) return undefined;
  const parsed = topics
    .filter(
      (topic): topic is { name: string; description: string } =>
        !!topic &&
        isString(topic.name) &&
        !!topic.name.trim() &&
        isString(topic.description),
    )
    .map((topic) => ({
      name: topic.name.trim(),
      description: topic.description.trim(),
    }));
  return parsed.length > 0 ? { topics: parsed } : undefined;
}

const isCount = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value) && value >= 0;

function parseGapLinks(raw: unknown): AgentGapLink[] {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((link): AgentGapLink[] => {
    if (link?.kind === 'source' && isString(link.id) && link.id)
      return [
        {
          kind: 'source',
          id: link.id,
          name: isString(link.name) ? link.name : '',
        },
      ];
    if (link?.kind === 'logs' && isLogLabel(link.label))
      return [{ kind: 'logs', label: link.label }];
    return [];
  });
}

/** The proposal's gaps, each naming only fields the proposal sets. */
function parseGaps(
  raw: unknown,
  fields: AgentProposalFields,
): AgentProposalGap[] {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((gap): AgentProposalGap[] => {
    if (
      !gap ||
      !isString(gap.gap_type) ||
      !gap.gap_type ||
      !(gap.topic === null || gap.topic === undefined || isString(gap.topic))
    )
      return [];
    return [
      {
        topic: gap.topic || null,
        gap_type: gap.gap_type,
        expected: isCount(gap.expected) ? gap.expected : 0,
        turns: isCount(gap.turns) ? gap.turns : 0,
        previous: isCount(gap.previous) ? gap.previous : null,
        example: isString(gap.example) ? gap.example.trim() : '',
        fields: (stringList(gap.fields) ?? []).filter(
          (field): field is AgentDraftField =>
            field in fields &&
            AGENT_DRAFT_FIELDS.includes(field as AgentDraftField),
        ),
        needs:
          isString(gap.needs) && gap.needs.trim() ? gap.needs.trim() : null,
        links: parseGapLinks(gap.links),
      },
    ];
  });
}

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
      checks: readPromptChecks(prompt.checks),
    };
  else if (prompt?.kind === 'edit' && isString(prompt.id) && prompt.id) {
    const edits = readPromptEdits(prompt.edits);
    if (edits.length > 0)
      fields.prompt = {
        kind: 'edit',
        id: prompt.id,
        edits,
        checks: readPromptChecks(prompt.checks),
      };
  }
  const limits = parseLimits(rawFields.limits);
  if (limits) fields.limits = limits;
  const guardrails = parseGuardrails(rawFields.guardrails);
  if (guardrails) fields.guardrails = guardrails;
  const analytics = parseTopics(rawFields.analytics);
  if (analytics) fields.analytics = analytics;
  const list = (value: unknown) => (Array.isArray(value) ? value : []);
  return {
    message: isString(source.message) ? source.message : undefined,
    fields,
    gaps: parseGaps(source.gaps, fields),
    reasons: list(source.reasons)
      .filter(
        (reason): reason is AgentProposal['reasons'][number] =>
          !!reason && isString(reason.field) && isString(reason.summary),
      )
      .map(({ field, summary }) => ({ field, summary })),
    notes: list(source.notes).filter(isString),
    dropped: list(source.dropped).filter(
      (item): item is AgentProposal['dropped'][number] =>
        !!item && isString(item.field),
    ),
    steps: list(source.steps).filter(isStep),
    next_step: isStep(source.next_step) ? source.next_step : null,
  };
}

/**
 * A field's value in a comparable shape: tools by id in order, sources by id
 * in any order, starters as a save cleans them, limits with every key set.
 */
export function draftValueOf<K extends AgentDraftField>(
  field: K,
  value: AgentDraftForm[K],
): unknown {
  if (field === 'tools') return (value as ToolSummary[]).map((tool) => tool.id);
  if (field === 'sources') return [...(value as string[])].sort();
  if (field === 'starters') return cleanStarters(value as string[]);
  if (field === 'limits') {
    const limits = value as AgentLimitsValue;
    return {
      limited_request_mode: limits.limited_request_mode,
      request_limit: limits.request_limit ?? null,
      limited_token_mode: limits.limited_token_mode,
      token_limit: limits.token_limit ?? null,
    };
  }
  if (field === 'guardrails') return value ?? null;
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

/** The limits a proposal sets: one mode on with its value, or both off. */
function limitsOf(
  limits: NonNullable<AgentProposalFields['limits']>,
  now: AgentLimitsValue,
): AgentLimitsValue {
  if (limits.mode === 'none')
    return { ...now, limited_request_mode: false, limited_token_mode: false };
  return limits.mode === 'requests'
    ? {
        ...now,
        limited_request_mode: true,
        request_limit: limits.value,
        limited_token_mode: false,
      }
    : {
        ...now,
        limited_token_mode: true,
        token_limit: limits.value,
        limited_request_mode: false,
      };
}

/**
 * The guardrails with a proposal's controls added: switching on one the
 * check has at that stage but switched off (the form shows its stage picked
 * either way) and keeping one it runs, guardrails on, and Monitor only
 * unless the agent already enforces everywhere.
 */
function guardrailsWith(
  added: GuardrailControlToAdd[],
  now: GuardrailsConfig | undefined,
): GuardrailsConfig {
  const base = now ?? DEFAULT_GUARDRAILS;
  const controls: GuardrailControl[] = [...base.controls];
  added.forEach(({ check, stage, action }) => {
    const at = controls.findIndex(
      (c) => c.check.toLowerCase() === check && c.stage === stage,
    );
    if (at >= 0) {
      if (controls[at].enabled === false)
        controls[at] = { ...controls[at], enabled: true };
      return;
    }
    controls.push({
      check,
      stage,
      action,
      enabled: true,
      settings: defaultControlSettings(check, null),
    });
  });
  return {
    ...base,
    enabled: true,
    mode: base.mode === 'scan_all' ? 'scan_all' : 'monitor_only',
    controls,
  };
}

/** The Insights settings with a proposal's topics added, skipping a name it has. */
function analyticsWith(
  topics: NonNullable<AgentProposalFields['analytics']>['topics'],
  now: AnalyticsConfig,
): AnalyticsConfig {
  const taken = new Set(now.topics.map((topic) => topic.name.toLowerCase()));
  const added = topics.filter((topic) => {
    const key = topic.name.toLowerCase();
    if (taken.has(key)) return false;
    taken.add(key);
    return true;
  });
  if (added.length === 0) return now;
  return {
    ...now,
    topics: [
      ...now.topics,
      ...added.map((topic) => ({ ...topic, id: newTopicId(), overlap: false })),
    ],
  };
}

/**
 * Work out what a proposal changes on the form, field by field in the order
 * they apply (sources, tools, type, name, description, starters, prompt,
 * limits, guardrails, Insights). Fields the proposal leaves out, or sets to
 * what the form already holds, are not changes. A tool id the caller has no
 * row for is left out. A new prompt is no change either: the host opens it
 * in the prompt view, and the form's prompt changes once it is saved there.
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
  if (fields.prompt?.kind === 'existing') next.prompt = fields.prompt.id;
  if (fields.limits) next.limits = limitsOf(fields.limits, form.limits);
  if (fields.guardrails)
    next.guardrails = guardrailsWith(
      fields.guardrails.controls,
      form.guardrails,
    );
  if (fields.analytics)
    next.analytics = analyticsWith(fields.analytics.topics, form.analytics);

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
    (!form.prompt || form.prompt === 'default')
  );
}

/** Whether the agent's limits and safety were never set: no limit, guardrails off. */
export function isSafetyUnset(form: AgentDraftForm): boolean {
  return (
    !form.limits.limited_request_mode &&
    !form.limits.limited_token_mode &&
    !form.guardrails?.enabled
  );
}

/** What an improve row asks for, in the order the drawer offers them. */
export type ImproveSuggestion =
  | 'safety'
  | 'knowledge'
  | 'writePrompt'
  | 'starters'
  | 'shorter'
  | 'tightenPrompt';

/** Prompts every instance has: an agent on one has no prompt of its own. */
const BUILTIN_PROMPTS = ['default', 'creative', 'strict'];
/** Most improve rows the drawer offers. */
const MAX_IMPROVE_ROWS = 4;
/** A description longer than this is worth offering to shorten. */
const SHORTEN_FROM = 120;

/**
 * The improve drawer's rows for a filled agent: first what it lacks
 * (limits and safety while never set, something to answer from, a prompt
 * of its own, starters), then changes that fit what it has (a shorter
 * description, a tighter prompt). At most four.
 *
 * Args:
 *   form: The form now.
 *   options: Whether Finish setup applies, and whether the prompt view
 *     holds unsaved text (a prompt of its own).
 *
 * Returns:
 *   The rows, in order.
 */
export function improveSuggestions(
  form: AgentDraftForm,
  { safety, promptDraft }: { safety: boolean; promptDraft: boolean },
): ImproveSuggestion[] {
  const ownPrompt =
    promptDraft || (!!form.prompt && !BUILTIN_PROMPTS.includes(form.prompt));
  const rows: (ImproveSuggestion | false)[] = [
    safety && 'safety',
    form.sources.length === 0 && form.tools.length === 0 && 'knowledge',
    !ownPrompt && 'writePrompt',
    form.starters.length === 0 && 'starters',
    form.description.trim().length > SHORTEN_FROM && 'shorter',
    ownPrompt && 'tightenPrompt',
  ];
  return rows
    .filter((row): row is ImproveSuggestion => !!row)
    .slice(0, MAX_IMPROVE_ROWS);
}

/** The limit a save sends, as the recipe reads it. */
function limitsContext(limits: AgentLimitsValue) {
  if (limits.limited_request_mode && limits.request_limit)
    return { mode: 'requests', value: limits.request_limit };
  if (limits.limited_token_mode && limits.token_limit)
    return { mode: 'tokens', value: limits.token_limit };
  return { mode: 'none', value: null };
}

/**
 * Where an improve conversation started from in Insights: a gap (a drawer
 * row, the Docs gaps panel) or one conversation in Logs.
 */
export type AgentImproveFocus = {
  gap?: { topic: string | null; gap_type: string };
  conversation_id?: string;
};

/**
 * The agent recipe's `context`: the form as it is now, where the guided
 * build stands, and in improve mode the gap or conversation it started from.
 *
 * Args:
 *   agentId: The saved agent's id, or null for a new one.
 *   form: The form now.
 *   build: The running step (null in improve mode), what the user wrote
 *     in the finished steps, and the starting point the build began from.
 *   promptDraft: The prompt view's unsaved name and text, or null.
 *   focus: The gap or conversation an improve started from; only a saved
 *     agent outside a step sends it.
 *
 * Returns:
 *   `{ agent_id, step, earlier, starter, form }` as the drafter contract
 *   describes it, with `gap` and `conversation_id` when they apply.
 */
export function agentDraftContext(
  agentId: string | null,
  form: AgentDraftForm,
  build: {
    step: AgentBuildStep | null;
    earlier: string[];
    starter?: DrafterStarter | null;
  },
  promptDraft: PromptDraft | null,
  focus: AgentImproveFocus = {},
) {
  const guardrails = form.guardrails ?? DEFAULT_GUARDRAILS;
  const improving = !!agentId && build.step === null;
  return {
    agent_id: agentId || null,
    step: build.step,
    earlier: build.earlier,
    starter: build.starter ?? null,
    ...(improving && focus.gap ? { gap: focus.gap } : {}),
    ...(improving && focus.conversation_id
      ? { conversation_id: focus.conversation_id }
      : {}),
    form: {
      name: form.name,
      description: form.description,
      agent_type: form.agent_type,
      sources: form.sources,
      tools: form.tools.map((tool) => tool.id),
      prompt_id: form.prompt || null,
      prompt_draft: promptDraft,
      starters: form.starters,
      limits: limitsContext(form.limits),
      guardrails: {
        enabled: guardrails.enabled,
        mode: guardrails.mode,
        // The controls it runs, by stage: one switched off runs nothing, and
        // a check on at some stages only may still get the others.
        controls: guardrails.controls
          .filter((c) => c.enabled !== false)
          .map((c) => ({ check: c.check.toLowerCase(), stage: c.stage })),
      },
      analytics: {
        enabled: form.analytics.enabled,
        topics: form.analytics.topics.map(({ name, overlap }) => ({
          name,
          overlap,
        })),
        hidden_folders: form.analytics.hidden_folders,
      },
    },
  };
}

/** The form label of each drafted field. */
export const AGENT_FIELD_LABEL_KEYS: Record<AgentDraftField, string> = {
  name: 'agents.form.labels.name',
  description: 'agents.form.labels.description',
  agent_type: 'agents.form.sections.agentType',
  sources: 'agents.form.labels.sources',
  tools: 'agents.form.sections.tools',
  prompt: 'agents.form.sections.prompt',
  starters: 'agents.form.sections.starters',
  limits: 'drafter.agent.fields.limits',
  guardrails: 'agents.form.sections.guardrails',
  analytics: 'agents.form.sections.analytics',
};

/** Why the server left a part out; `other_step` is a field this step doesn't take. */
const DROPPED_REASONS = [
  'not_found',
  'no_access',
  'invalid',
  'not_allowed',
  'other_step',
];

/** How many words a prompt's text has, for "Wrote a new prompt · 131 words". */
const wordCount = (text: string): number =>
  text.trim() ? text.trim().split(/\s+/).length : 0;

/**
 * The proposal summary's rows and lines: a reason per changed field (a new
 * prompt, still unsaved in the prompt view, gets one row with its length,
 * and changes to a saved prompt one row with their count), and what the
 * server left out.
 *
 * Args:
 *   proposal: The parsed proposal.
 *   t: The translator.
 *   changed: The fields applying the draft changed; a reason for any other
 *     field (one the form already held, as Classic on a Classic agent) is
 *     left out. Omitted, every reason shows.
 *   fitting: How many of its changes to a saved prompt fit the text the
 *     view loaded (the review shows only those); omitted until then.
 *
 * Returns:
 *   `rows` for ProposalSummary and `dropped` lines.
 */
export function agentProposalSummary(
  proposal: AgentProposal,
  t: TFunction,
  changed?: readonly string[],
  fitting?: number,
): { rows: ProposalReasonRow[]; dropped: string[] } {
  const labelOf = (field: string) =>
    field in AGENT_FIELD_LABEL_KEYS
      ? t(AGENT_FIELD_LABEL_KEYS[field as AgentDraftField])
      : field;
  const written = proposal.fields.prompt;
  const reasons = proposal.reasons.filter(
    (reason) =>
      (!changed || changed.includes(reason.field)) &&
      !(written && written.kind !== 'existing' && reason.field === 'prompt'),
  );
  const rows = [
    ...(written?.kind === 'new'
      ? [
          {
            key: 'prompt-new',
            label: labelOf('prompt'),
            summary: t('drafter.agent.prompt.wrote', {
              count: wordCount(written.content),
            }),
          },
        ]
      : []),
    ...(written?.kind === 'edit' && fitting !== 0
      ? [
          {
            key: 'prompt-edits',
            label: labelOf('prompt'),
            summary: t('drafter.agent.prompt.changes', {
              count: fitting ?? written.edits.length,
            }),
          },
        ]
      : []),
    ...reasons.map((reason, index) => ({
      key: `${reason.field}-${index}`,
      label: labelOf(reason.field),
      summary: reason.summary,
    })),
  ];
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
  const unfit =
    written?.kind === 'edit' && fitting !== undefined
      ? written.edits.length - fitting
      : 0;
  if (unfit > 0)
    dropped.push(t('drafter.agent.prompt.unfit', { count: unfit }));
  return { rows, dropped };
}

/**
 * What a finished step holds now, in a few words, for its folded line
 * ("Basics: Shipping help desk"). Read from the form, so a later change
 * shows.
 *
 * Args:
 *   step: The step.
 *   form: The form now.
 *   t: The translator.
 *   promptName: The picked prompt's name.
 *
 * Returns:
 *   The step's result line.
 */
export function agentStepResult(
  step: AgentBuildStep,
  form: AgentDraftForm,
  t: TFunction,
  promptName: string,
): string {
  const parts: string[] = [];
  switch (step) {
    case 'basics':
      return form.name.trim() || t('drafter.agent.build.result.noName');
    case 'knowledge': {
      if (form.sources.length > 0)
        parts.push(t('drafter.counts.sources', { count: form.sources.length }));
      if (form.tools.length > 2)
        parts.push(t('drafter.counts.tools', { count: form.tools.length }));
      else form.tools.forEach((tool) => parts.push(getToolDisplayName(tool)));
      if (form.agent_type === 'research')
        parts.push(t('agents.form.agentTypes.research'));
      break;
    }
    case 'prompt': {
      if (promptName) parts.push(promptName);
      const starters = cleanStarters(form.starters).length;
      if (starters > 0)
        parts.push(
          t('drafter.agent.build.result.starters', { count: starters }),
        );
      break;
    }
    case 'safety': {
      const limits = limitsContext(form.limits);
      parts.push(
        limits.mode === 'none'
          ? t('drafter.agent.build.result.noLimit')
          : t(`drafter.agent.build.result.${limits.mode}`, {
              count: limits.value,
            }),
      );
      const guardrails = form.guardrails;
      const checks = new Set(guardrails?.controls.map((c) => c.check));
      if (guardrails?.enabled && checks.size > 0)
        parts.push(
          t('drafter.agent.build.result.checks', {
            count: checks.size,
            mode: t(
              guardrails.mode === 'scan_all'
                ? 'agents.form.guardrails.modes.scanAll'
                : 'agents.form.guardrails.modes.monitorOnly',
            ),
            interpolation: { escapeValue: false },
          }),
        );
      if (form.analytics.enabled && form.analytics.topics.length > 0)
        parts.push(
          t('drafter.agent.build.result.topics', {
            count: form.analytics.topics.length,
          }),
        );
      break;
    }
  }
  return parts.length > 0
    ? joinList(parts)
    : t('drafter.agent.build.result.none');
}

/** Most gap rows the improve drawer offers. */
export const MAX_GAP_ROWS = 3;

/** A gap type's name as Insights shows it ("Docs gap"). */
export const gapName = (t: TFunction, gapType: string): string =>
  optionName((key) => t(key), 'gap_type', gapType);

/** A topic as Insights shows it: the catch-all reads "None of these". */
const topicName = (t: TFunction, topic: string): string =>
  topic === NONE_OF_THESE
    ? t('settings.analytics.insights.panels.noneOfThese')
    : topic;

/** A gap row's title: its topic, or the gap's name for an agent without topics. */
export const gapTitle = (t: TFunction, row: AgentGapRow): string =>
  row.topic ? topicName(t, row.topic) : gapName(t, row.gap_type);

/**
 * A gap row's line, from the data alone: "Docs gap · 23 of 160 questions",
 * then the change once the previous window was labelled (" · up from 19").
 *
 * Args:
 *   t: The translator.
 *   row: The summary row (or a proposal's gap, which carries its counts).
 *
 * Returns:
 *   The line, worded like the Insights page.
 */
export function gapLine(t: TFunction, row: AgentGapRow): string {
  const parts = [
    t('drafter.agent.insights.gapLine', {
      gap: gapName(t, row.gap_type),
      expected: formatCount(Math.round(row.expected)),
      count: row.turns,
      formatted: formatCount(row.turns),
      interpolation: { escapeValue: false },
    }),
  ];
  if (row.previous !== null) {
    const now = Math.round(row.expected);
    const before = Math.round(row.previous);
    if (now !== before)
      parts.push(
        t(
          now > before
            ? 'drafter.agent.insights.upFrom'
            : 'drafter.agent.insights.downFrom',
          { previous: formatCount(before) },
        ),
      );
  }
  return parts.join(' · ');
}

/**
 * What a gap row sends: "Fix the Docs gap in Returns & claims", or "Fix:
 * Docs gap" for an agent without topics.
 */
export function gapRequest(
  t: TFunction,
  row: Pick<AgentGapRow, 'topic' | 'gap_type'>,
): string {
  const gap = gapName(t, row.gap_type);
  return row.topic
    ? t('drafter.agent.insights.fixIn', {
        gap,
        topic: topicName(t, row.topic),
        interpolation: { escapeValue: false },
      })
    : t('drafter.agent.insights.fix', {
        gap,
        interpolation: { escapeValue: false },
      });
}
