import type { SponsorAudience } from '../sponsorConsent';
import type { AccessFields } from '../../utils/accessUtils';

export type ToolSummary = {
  id: string;
  name: string;
  display_name: string;
};

/** Why a sponsored item stopped running (`ResourceSponsor.reason`). */
export type ResourceSponsorReason =
  'sponsor_cannot_edit_agent' | 'sponsor_cannot_edit_resource';

/** A tool, source or prompt that runs with the editor's access who added it. */
export type ResourceSponsor = {
  /** `"<type>:<id>"`, the value `confirm_sponsor` takes. */
  key?: string;
  type: 'tool' | 'source' | 'prompt';
  id: string;
  /** The item's name, looked up whoever owns it. */
  name?: string | null;
  /** Null, with `label`, for someone the reader doesn't know. */
  user_id: string | null;
  /** The person's email when on file, else their user id. */
  label: string | null;
  state?: 'active' | 'inactive';
  /** Null while it runs; else whether the person lost the agent or the item. */
  reason?: ResourceSponsorReason | null;
  /** False once that person can no longer edit the agent, or own or edit the item. */
  active: boolean;
  /** The reader may take a stopped item over by confirming it on a save. */
  can_confirm?: boolean;
};

/** Why an attached item doesn't run (`ResourceState.reason`). */
export type ResourceStateReason =
  | 'deleted'
  | 'owner_lost_access'
  | ResourceSponsorReason
  | 'connection_needs_reconnect'
  | 'connection_removed'
  | 'connector_disabled';

/** Something to know about an item that runs (`ResourceState.note`). */
export type ResourceStateNote = 'per_user_account';

/**
 * A person the page names: their email when on file, else their user id.
 * Both are null for someone the reader doesn't know.
 */
export type ResourcePerson = { user_id: string | null; label: string | null };

/**
 * Whether an attached tool, source or prompt runs (`resource_states` on the
 * agent and workflow reads, for people who may edit them).
 */
export type ResourceState = {
  /** `"<type>:<id>"`, the value `confirm_sponsor` takes. */
  key: string;
  type: 'tool' | 'source' | 'prompt';
  id: string;
  /** Null when the reader may not see it. */
  name?: string | null;
  state: 'active' | 'stopped';
  /** Null while it runs. */
  reason: ResourceStateReason | null;
  /** `per_user_account`: it runs on each person's own account. */
  note?: ResourceStateNote | null;
  /** Who it ran with the access of, when someone else added it. */
  sponsor?: ResourcePerson | null;
  /** Someone other than the reader who can fix it, when the reader knows them. */
  contact?: ResourcePerson | null;
  /** Who can fix it (`resource_owner`), named or not. */
  contact_role?: 'resource_owner' | null;
  /**
   * The service of a connected tool, or of one a connection reason stopped.
   * `id` only when the reader may reconnect
   * it; the account's own name only for its owner.
   */
  connection?: {
    id: string | null;
    connector_key: string | null;
    name: string | null;
  } | null;
  /** The live sponsor a running item runs as; null for the owner. */
  runs_as?: ResourcePerson | null;
  /** A running connected tool's mode: the owner's account or each person's own. */
  credential_mode?: 'owner' | 'member' | null;
  /**
   * Whose saved credentials or owner-mode connection a running tool uses
   * (the tool's owner); both null when the reader may not see who.
   */
  account?: ResourcePerson | null;
  /** Its write actions on credentials its owner stored (the API write allowlist's). */
  owner_credential_writes?: string[];
  /** False when an admin turned off changes through its connector. */
  writes_allowed?: boolean;
  /** The reader may run it with their access by confirming on a save. */
  can_confirm?: boolean;
  /** The reader owns the connection that needs signing in again. */
  can_reconnect?: boolean;
};

export type Agent = {
  id?: string;
  name: string;
  slug?: string;
  description: string;
  image: string;
  source: string;
  sources?: string[];
  chunks: string;
  retriever: string;
  prompt_id: string;
  tools: string[];
  tool_details?: ToolSummary[];
  agent_type: string;
  status: string;
  key?: string;
  incoming_webhook_token?: string;
  pinned?: boolean;
  shared?: boolean;
  shared_token?: string;
  shared_metadata?: any;
  // Whether the current user owns this agent ('user') or only has access to
  // it because a team shared it with them ('team'). Owner-only actions (e.g.
  // sharing with a team) are gated on 'user'.
  ownership?: 'user' | 'team';
  team_access?: 'viewer' | 'editor' | null;
  /** The caller's role and the actions it allows (see `utils/accessUtils`). */
  access?: AccessFields['access'];
  allowed_actions?: AccessFields['allowed_actions'];
  // Owner-agnostic display names resolved server-side (GET /api/get_agent) so a
  // team member viewing a shared agent sees the owner's prompt/source names
  // instead of a blank prompt / "External KB" (the client can only resolve
  // names for resources the caller themselves owns).
  prompt_name?: string | null;
  source_details?: { id: string; name: string | null }[];
  // Resources the owner can't use that run as the editor who attached them
  // (GET /api/get_agent, callers who may view the config).
  resource_sponsors?: ResourceSponsor[];
  // Whether each attached tool, source and prompt runs, and why not
  // (GET /api/get_agent, callers who may edit the agent).
  resource_states?: ResourceState[];
  // Who reaches the agent's resources, sent when the caller may take one
  // over, so the take-over confirmation can say who it extends to.
  sponsor_audience?: SponsorAudience;
  created_at?: string;
  updated_at?: string;
  last_used_at?: string;
  json_schema?: object;
  limited_token_mode?: boolean;
  token_limit?: number;
  limited_request_mode?: boolean;
  request_limit?: number;
  models?: string[];
  default_model_id?: string;
  folder_id?: string;
  workflow?: string;
  allow_system_prompt_override?: boolean;
  config?: AgentConfig;
};

export type GuardrailStage = 'input' | 'retrieval' | 'tool_result' | 'output';

export type GuardrailAction = 'flag' | 'redact' | 'block';

export type GuardrailMode = 'monitor_only' | 'scan_all';

export type GuardrailControl = {
  check: string;
  stage: GuardrailStage;
  action: GuardrailAction;
  enabled: boolean;
  settings: Record<string, any>;
};

export type GuardrailsConfig = {
  enabled: boolean;
  mode: GuardrailMode;
  fail_open: boolean;
  timeout_ms: number;
  block_message: string;
  controls: GuardrailControl[];
};

export type AgentConfig = {
  guardrails?: GuardrailsConfig;
  /** `tool_id:action` writes on the owner's accounts API-key callers may run. */
  api_write_allowlist?: string[];
};

export type GuardrailCheckInfo = {
  name: string;
  label: string;
  description: string;
  stages: GuardrailStage[];
  supports_redaction: boolean;
  latency_hint_ms: number;
  remote: boolean;
  available: boolean;
};

export type GuardrailCatalog = {
  enabled: boolean;
  checks: GuardrailCheckInfo[];
  stages: GuardrailStage[];
  modes: GuardrailMode[];
  actions_by_stage: Record<GuardrailStage, GuardrailAction[]>;
  default_block_message: string;
  pii_entities: string[];
  default_pii_entities: string[];
  floor: GuardrailsConfig | null;
};

export type AgentFolder = {
  id: string;
  name: string;
  parent_id?: string | null;
  created_at?: string;
  updated_at?: string;
};

export * from './schedule';
export * from './workflow';

export type GuardrailEvent = {
  id: string;
  agent_id: string | null;
  message_id: string | null;
  request_id: string | null;
  stage: GuardrailStage;
  check_name: string;
  detector_type: string;
  action: GuardrailAction;
  outcome: 'triggered' | 'not_evaluated';
  category: string | null;
  score: number | null;
  match_count: number;
  detail: string | null;
  created_at: string;
};

export type GuardrailSummary = {
  breakdown: {
    check_name: string;
    stage: GuardrailStage;
    action: GuardrailAction;
    outcome: string;
    category: string | null;
    total: number;
  }[];
  totals: {
    blocked: number;
    flagged: number;
    redacted: number;
    not_evaluated: number;
  };
};
