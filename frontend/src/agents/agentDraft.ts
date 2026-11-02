import type { TFunction } from 'i18next';

import type { ProposalReasonRow } from '../drafter/ProposalSummary';
import { getToolDisplayName } from '../utils/toolUtils';
import { newTopicId } from './analyticsConfig';
import {
  DEFAULT_GUARDRAILS,
  defaultControlSettings,
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

/** A prompt's unsaved name and text, as the prompt view holds them. */
export type PromptDraft = { name: string; content: string };

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

/**
 * The guardrail checks the safety step offers and the controls each adds
 * (GUARDRAIL_MENU in agent_recipe.py).
 */
export const GUARDRAIL_MENU: Record<
  string,
  readonly (readonly [GuardrailStage, GuardrailAction])[]
> = {
  pii: [
    ['input', 'redact'],
    ['output', 'redact'],
  ],
  injection: [['input', 'block']],
  groundedness: [['output', 'flag']],
  secrets: [['output', 'redact']],
};

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
  /** Request and token limits are either-or; `none` turns both off. */
  limits?: { mode: 'requests' | 'tokens'; value: number } | { mode: 'none' };
  /** GUARDRAIL_MENU checks to add. */
  guardrails?: { checks: string[] };
  /** Insights topics to add. */
  analytics?: { topics: { name: string; description: string }[] };
};

export type AgentProposal = {
  message?: string;
  fields: AgentProposalFields;
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
  const limits = parseLimits(rawFields.limits);
  if (limits) fields.limits = limits;
  const checks = stringList(
    (rawFields.guardrails as { checks?: unknown } | undefined)?.checks,
  )?.filter((check) => check in GUARDRAIL_MENU);
  if (checks?.length) fields.guardrails = { checks };
  const analytics = parseTopics(rawFields.analytics);
  if (analytics) fields.analytics = analytics;
  const list = (value: unknown) => (Array.isArray(value) ? value : []);
  return {
    message: isString(source.message) ? source.message : undefined,
    fields,
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
 * The guardrails with a proposal's checks added: each check's controls from
 * GUARDRAIL_MENU, skipping a stage the check already runs at, guardrails on,
 * and Monitor only unless the agent already enforces everywhere.
 */
function guardrailsWith(
  checks: string[],
  now: GuardrailsConfig | undefined,
): GuardrailsConfig {
  const base = now ?? DEFAULT_GUARDRAILS;
  const controls: GuardrailControl[] = [...base.controls];
  checks.forEach((check) =>
    GUARDRAIL_MENU[check].forEach(([stage, action]) => {
      if (controls.some((c) => c.check === check && c.stage === stage)) return;
      controls.push({
        check,
        stage,
        action,
        enabled: true,
        settings: defaultControlSettings(check, null),
      });
    }),
  );
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
    next.guardrails = guardrailsWith(fields.guardrails.checks, form.guardrails);
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

/** The limit a save sends, as the recipe reads it. */
function limitsContext(limits: AgentLimitsValue) {
  if (limits.limited_request_mode && limits.request_limit)
    return { mode: 'requests', value: limits.request_limit };
  if (limits.limited_token_mode && limits.token_limit)
    return { mode: 'tokens', value: limits.token_limit };
  return { mode: 'none', value: null };
}

/**
 * The agent recipe's `context`: the form as it is now, and where the guided
 * build stands.
 *
 * Args:
 *   agentId: The saved agent's id, or null for a new one.
 *   form: The form now.
 *   build: The running step (null in improve mode) and what the user wrote
 *     in the finished steps.
 *   promptDraft: The prompt view's unsaved name and text, or null.
 *
 * Returns:
 *   `{ agent_id, step, earlier, form }` as the drafter contract describes it.
 */
export function agentDraftContext(
  agentId: string | null,
  form: AgentDraftForm,
  build: { step: AgentBuildStep | null; earlier: string[] },
  promptDraft: PromptDraft | null,
) {
  const guardrails = form.guardrails ?? DEFAULT_GUARDRAILS;
  return {
    agent_id: agentId || null,
    step: build.step,
    earlier: build.earlier,
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
        checks: [
          ...new Set(guardrails.controls.map((c) => c.check.toLowerCase())),
        ],
      },
      analytics: {
        enabled: form.analytics.enabled,
        topics: form.analytics.topics.map((topic) => topic.name),
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

const DROPPED_REASONS = ['not_found', 'no_access', 'invalid', 'not_allowed'];

/** How many words a prompt's text has, for "Wrote a new prompt · 131 words". */
const wordCount = (text: string): number =>
  text.trim() ? text.trim().split(/\s+/).length : 0;

/**
 * The proposal summary's rows and lines: a reason per changed field (a new
 * prompt, still unsaved in the prompt view, gets one row with its length),
 * and what the server left out.
 *
 * Args:
 *   proposal: The parsed proposal.
 *   t: The translator.
 *   changed: The fields applying the draft changed; a reason for any other
 *     field (one the form already held, as Classic on a Classic agent) is
 *     left out. Omitted, every reason shows.
 *
 * Returns:
 *   `rows` for ProposalSummary and `dropped` lines.
 */
export function agentProposalSummary(
  proposal: AgentProposal,
  t: TFunction,
  changed?: readonly string[],
): { rows: ProposalReasonRow[]; dropped: string[] } {
  const labelOf = (field: string) =>
    field in AGENT_FIELD_LABEL_KEYS
      ? t(AGENT_FIELD_LABEL_KEYS[field as AgentDraftField])
      : field;
  const written = proposal.fields.prompt;
  const reasons = proposal.reasons.filter(
    (reason) =>
      (!changed || changed.includes(reason.field)) &&
      !(written?.kind === 'new' && reason.field === 'prompt'),
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
      return form.name.trim() || t('agents.pageHeader.fallbackName');
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
    ? parts.join(', ')
    : t('drafter.agent.build.result.none');
}
