export type ToolSummary = {
  id: string;
  name: string;
  display_name: string;
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
  // Owner-agnostic display names resolved server-side (GET /api/get_agent) so a
  // team member viewing a shared agent sees the owner's prompt/source names
  // instead of a blank prompt / "External KB" (the client can only resolve
  // names for resources the caller themselves owns).
  prompt_name?: string | null;
  source_details?: { id: string; name: string | null }[];
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

export type GuardrailStage =
  'input' | 'retrieval' | 'tool_call' | 'tool_result' | 'output';

export type GuardrailAction = 'flag' | 'redact' | 'block' | 'require_approval';

export type GuardrailMode =
  'monitor_only' | 'background_scan' | 'dangerous_tools_only' | 'scan_all';

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
  moderation_categories: string[];
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
