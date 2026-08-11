import { ConfigRequirements } from '../../modals/types';

export type ChunkType = {
  doc_id: string;
  text: string;
  metadata: { [key: string]: string };
};

export type APIKeyData = {
  id: string;
  name: string;
  key: string;
  source: string;
  prompt_id: string;
  chunks: string;
};

export type LogEventType =
  | 'chat'
  | 'schedule'
  | 'webhook'
  | 'workflow'
  | 'system';

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
  // system + webhook events (stack_logs)
  endpoint?: string;
  stacks?: Record<string, any>[];
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
};
