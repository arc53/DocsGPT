import type { WorkflowProgress } from '../../activity/types';
import { ConfigRequirements } from '../../modals/types';
import type { Access } from '../../utils/accessUtils';

/**
 * A chunk's prompt-injection review state (`get_chunks`): the sha256 of its
 * text (what a review is keyed by), the cached score (null before it was
 * scored), `high` (p ≥ 0.9), `suspected` (p ≥ 0.5) or null, and whether the
 * source's owner marked it safe.
 */
export type ChunkInjection = {
  content_hash: string;
  p: number | null;
  level: 'high' | 'suspected' | null;
  allowed: boolean;
};

export type ChunkType = {
  doc_id: string;
  text: string;
  /** Null while the operator has the prompt-injection model off. */
  injection?: ChunkInjection | null;
  /**
   * Chunk metadata as the vector store recorded it. Values are strings for
   * most backends, but numbers (`token_count`) survive the round trip on the
   * JSON-typed ones, so consumers must handle both.
   */
  metadata: {
    title?: string;
    source?: string;
    token_count?: number | string;
    [key: string]: number | string | undefined;
  };
};

export type LogEventType =
  'chat' | 'schedule' | 'webhook' | 'workflow' | 'system' | 'search' | 'graph';

/** Counts rolled up from a trace's spans; every field may be absent. */
export type TraceCounts = {
  llm_calls?: number;
  tool_calls?: number;
  retrieval_calls?: number;
  retrieval_ms?: number;
  input_tokens?: number;
  output_tokens?: number;
  errors?: number;
};

/** The id a Logs row's traces are looked up by. */
export type TraceRef = {
  field: 'id' | 'request_id' | 'message_id' | 'activity_id' | 'workflow_run_id';
  value: string;
};

/** Trace summary attached to a Logs row (merged over its rounds). */
export type LogTraceSummary = {
  ref: TraceRef;
  count: number;
  duration_ms: number;
  status?: string;
  started_at?: string;
  summary: TraceCounts;
};

export type TraceSpanKind =
  | 'agent'
  | 'llm'
  | 'tool'
  | 'retrieval'
  | 'search'
  | 'embedding'
  | 'rerank'
  | 'guardrail'
  | 'decision'
  | 'step';

export type TraceSpan = {
  id: string;
  parent_id: string | null;
  kind: TraceSpanKind | string;
  name: string;
  status: string;
  offset_ms: number;
  duration_ms: number;
  attributes: Record<string, unknown>;
  preview?: Record<string, unknown>;
  error?: string;
};

export type Trace = {
  id: string;
  request_id?: string | null;
  message_id?: string | null;
  source: string;
  name?: string | null;
  status: string;
  started_at: string;
  duration_ms: number;
  span_count: number;
  dropped_spans: number;
  summary: TraceCounts;
  spans: TraceSpan[];
  otel_trace_id?: string | null;
};

export type LogData = {
  id: string;
  event_type?: LogEventType;
  action: string;
  level: 'info' | 'error' | 'warning';
  user: string;
  question: string;
  timestamp: string;
  // chat events (user_logs)
  response?: string;
  sources?: Record<string, any>[];
  tool_calls?: Record<string, any>[];
  agent_id?: string;
  attachments?: string[];
  request_id?: string;
  message_id?: string;
  /** The request's passthrough values (an embedding page's user id, say). */
  passthrough?: Record<string, string | number | boolean | null> | null;
  /** The answer's rating, read from its message. */
  feedback?: { text: string; timestamp?: string } | null;
  // system + webhook events (stack_logs)
  endpoint?: string;
  stacks?: Record<string, any>[];
  activity_id?: string;
  // search + graph events (request_traces)
  source?: string;
  duration_ms?: number;
  // Present when the row has a stored execution trace.
  trace?: LogTraceSummary;
  // workflow events (workflow_runs)
  workflow_name?: string;
  result?: Record<string, any>;
  steps?: Record<string, any>[];
  // schedule events (schedule_runs)
  status?: string;
  trigger_source?: string;
  schedule_name?: string;
  instruction?: string;
  output?: string;
  error?: string;
  error_type?: string;
  prompt_tokens?: number;
  generated_tokens?: number;
  conversation_id?: string;
  scheduled_for?: string;
  started_at?: string;
  finished_at?: string;
  // A run still going: listed at its start time until its finished row
  // replaces it (answers, scheduled, workflow and webhook runs).
  running?: boolean;
  /**
   * A chat row's conversation labels that clear the filter threshold:
   * `docs_gap`, `not_answered`, `frustrated`, `asks_human`,
   * `negative_reaction`, `negative_sentiment`, `tag:<id>`.
   */
  labels?: string[];
  /** A running answer: who asked (`api`, `shared` or the owner's own `chat`). */
  origin?: 'api' | 'shared' | 'chat';
  workflow_progress?: WorkflowProgress | null;
};

export type ParameterGroupType = {
  type: 'object';
  properties: {
    [key: string]: {
      type: 'string' | 'integer';
      description: string;
      value: string | number;
      filled_by_llm: boolean;
      required?: boolean;
      // A saved secret header / query value: the server sends `value: ""`
      // and this flag; an empty value on save keeps the stored one.
      has_value?: boolean;
    };
  };
};

export type UserToolType = {
  id: string;
  name: string;
  displayName: string;
  customName?: string;
  description: string;
  status: boolean;
  // True for built-in default chat tools — managed via the opt-out list,
  // not a user_tools row; not deletable. ``scheduler`` is dual-registered
  // (both ``default`` and ``builtin``).
  default?: boolean;
  // True for agent-selectable builtins (e.g. ``scheduler``) — hidden
  // from the Add-Tool modal; surfaced to the agent picker. May coexist
  // with ``default`` for dual-registered tools.
  builtin?: boolean;
  // True for builtins shown only in the workflow-node tool picker
  // (e.g. ``read_document``) — hidden from the classic agent picker.
  workflow_only?: boolean;
  // Whether the current user owns this tool ('user') or only has access to
  // it via a team share ('team'). Owner-only actions are gated on 'user'.
  ownership?: 'user' | 'team';
  // Access level when shared via a team: 'viewer' (use) or 'editor' (edit
  // actions; secrets stay owner-only). Null/absent for tools the caller owns.
  team_access?: 'viewer' | 'editor' | null;
  // The connection whose account or credentials the tool runs with.
  connection_id?: string | null;
  // Whether team members use the owner's account or their own.
  credential_mode?: 'owner' | 'member';
  // Caller's role and what it may do (`utils/accessUtils` `can`).
  access?: Access | null;
  allowed_actions?: string[];
  // Whether the tool joins the caller's own agentless chats: the owner's
  // `status`, or a grantee's personal preference (default off).
  in_chat?: boolean;
  // A team through which a shared tool reaches the caller.
  shared_via?: string | null;
  // The owner's email or name, when the server can resolve it.
  owner_label?: string | null;
  config: {
    [key: string]: any;
  };
  configRequirements?: ConfigRequirements;
  actions: {
    name: string;
    description: string;
    parameters: {
      properties: {
        [key: string]: {
          type: string;
          description: string;
          filled_by_llm: boolean;
          value: string;
          required?: boolean;
        };
      };
      additionalProperties: boolean;
      required: string[];
      type: string;
    };
    active: boolean;
    require_approval?: boolean;
    // Read or write, set on tools that come from a connection.
    access?: 'read' | 'write';
    // An MCP action's description score, while Admin › Guardrails warns on them.
    injection?: { p: number; scorer: string } | null;
  }[];
};

export type APIActionType = {
  name: string;
  url: string;
  description: string;
  method: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH' | 'HEAD' | 'OPTIONS';
  query_params: ParameterGroupType;
  headers: ParameterGroupType;
  body: ParameterGroupType;
  active: boolean;
  require_approval?: boolean;
  body_content_type?:
    | 'application/json'
    | 'application/x-www-form-urlencoded'
    | 'multipart/form-data'
    | 'text/plain'
    | 'application/xml'
    | 'application/octet-stream';
  body_encoding_rules?: {
    [key: string]: {
      style?: 'form' | 'spaceDelimited' | 'pipeDelimited' | 'deepObject';
      explode?: boolean;
    };
  };
};

export type APIToolType = {
  id: string;
  name: string;
  displayName: string;
  customName?: string;
  description: string;
  status: boolean;
  config: { actions: { [key: string]: APIActionType } };
  configRequirements?: ConfigRequirements;
  access?: Access | null;
  allowed_actions?: string[];
  ownership?: 'user' | 'team';
  team_access?: 'viewer' | 'editor' | null;
};

/** One option of an insights label: its expected count and rate with a 95% range. */
export type InsightOption = {
  expected: number;
  rate: number;
  low: number;
  high: number;
};

export type InsightTier = 'dashboard' | 'estimated' | 'experimental';

/** A label's totals over the window: `n` is what each rate is a share of. */
export type InsightLabelTotals = {
  tier: InsightTier;
  n: number;
  options: Record<string, InsightOption>;
  /**
   * `answer_status` only: its `n` and rates are over requests (labelled
   * turns less their "not a request" mass, `n_requests`), out of `n_turns`.
   */
  n_requests?: number;
  n_turns?: number;
};

/** One time bucket of the insights series: expected counts per option. */
export type InsightSeriesBucket = {
  /** The bucket's key in `bucket_unit`; a week's first day in the window. */
  bucket: string;
  /** A week's last day in the window. */
  bucket_end?: string;
  labels: Record<string, { n: number; options: Record<string, number> }>;
};

/** The series' unit: the filter's own, or one step coarser while its buckets hold few answers. */
export type InsightBucketUnit = 'minute' | 'hour' | 'day' | 'week';

/** POST /api/get_conversation_insights. */
export type ConversationInsights = {
  success: boolean;
  /** The server switch is on and, on an agent's page, the agent's analytics too. */
  enabled: boolean;
  /** The server switch alone. */
  available: boolean;
  coverage: {
    turns: number;
    labelled_turns: number;
    replies: number;
    labelled_replies: number;
    conversations: number;
    labelled_conversations: number;
    /** Unlabelled answers inside the labelling window: the sweep still labels them. */
    unlabelled_recent_turns: number;
    /** Unlabelled answers older than the labelling window: never labelled without a backfill. */
    unlabelled_older_turns: number;
    /**
     * Answers whose labelling failed for good, in neither unlabelled count:
     * not retried until the model or its questions change. Absent from an
     * older server, which reads as none.
     */
    failed_turns?: number;
  };
  /** How many days back the sweep labels (`ANALYTICS_BACKFILL_DAYS`). */
  backfill_days: number;
  /** The labelling window's start, as an ISO time. */
  labelling_from: string;
  /** Message counts by language code, plus `other`. */
  languages: Record<string, number>;
  /** Labels whose share of weaker languages is high enough to say so. */
  language_warnings: string[];
  /** On an agent's page: the options of its topic question (none under two). */
  one_pick: string[];
  /** On an agent's page: its topics that can overlap; totals under `tag:<id>`. */
  overlapping: { id: string; name: string }[];
  totals: Record<string, InsightLabelTotals>;
  /**
   * Answer status, reaction and sentiment over the period of the same length
   * before the window. Absent from an older server.
   */
  previous?: Record<string, InsightLabelTotals>;
  /** Absent from an older server, whose series is in the filter's own unit. */
  bucket_unit?: InsightBucketUnit;
  series: InsightSeriesBucket[];
};

export type DocsGapsGroup = 'page' | 'source' | 'topic';

export type DocsGapExample = {
  message_id: string;
  conversation_id: string;
  /** The question's first 200 characters. */
  prompt: string;
  p: number;
  timestamp: string;
};

/** One group of POST /api/get_docs_gaps: expected gaps and the share of its questions. */
export type DocsGapRow = {
  key: string | null;
  name: string | null;
  /** By page: the source the page came from; null otherwise or when unknown. */
  source: string | null;
  expected_gaps: number;
  turns: number;
  rate: number;
  low: number;
  high: number;
  previous_expected: number;
  examples: DocsGapExample[];
};

/** GET /api/analytics/topics: one of an agent's topics and the Logs `label` that filters by it. */
export type AgentTopic = {
  /** `topic:<name>` for one that doesn't overlap, `tag:<id>` for one that can. */
  label: string;
  name: string;
  overlap: boolean;
};
