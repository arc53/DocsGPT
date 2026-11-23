/**
 * Where a model in `/api/models` comes from: the instance's catalog, the
 * caller's own custom models, or the team's (in a team workspace).
 */
export type ModelSource = 'builtin' | 'user' | 'team';
export type ModelApiFlavor = 'chat_completions' | 'responses';
export type ToolResultImages = 'native' | 'follow_up';
export type ReasoningEffort =
  'none' | 'minimal' | 'low' | 'medium' | 'high' | 'xhigh';

export interface AvailableModel {
  id: string;
  provider: string;
  display_name: string;
  description?: string;
  context_window: number;
  supported_attachment_types: string[];
  supports_tools: boolean;
  supports_structured_output: boolean;
  supports_streaming: boolean;
  enabled: boolean;
  source?: ModelSource;
}

export interface Model {
  id: string;
  value: string;
  provider: string;
  display_name: string;
  description?: string;
  context_window: number;
  supported_attachment_types: string[];
  supports_tools: boolean;
  supports_structured_output: boolean;
  supports_streaming: boolean;
  source?: ModelSource;
}

export interface CustomModelCapabilities {
  supports_tools: boolean;
  supports_structured_output: boolean;
  attachments: string[];
  context_window: number;
  api_flavor?: ModelApiFlavor;
  reasoning_effort?: ReasoningEffort;
  tool_result_images?: ToolResultImages;
}

/** Whose custom model it is: the caller's own, or the team's. */
export type CustomModelOwner = 'personal' | 'team';

/**
 * What the caller may do with a custom model: `view` it, `use` it in chats,
 * agents and workflows, `manage` it (edit, test, replace the key, delete).
 * On a team's model, Viewers and Editors get `view` and `use`, Admins and
 * the Owner all three.
 */
export type CustomModelAction = 'view' | 'use' | 'manage';

/** The person who added a team's model (named also after they left). */
export type CustomModelAddedBy = { user_id: string; label: string };

export interface CustomModel {
  id: string;
  upstream_model_id: string;
  display_name: string;
  description?: string;
  /** Only for someone who may `manage` it: absent for a team's Viewers and Editors. */
  base_url?: string;
  capabilities: CustomModelCapabilities;
  enabled: boolean;
  source: 'user' | 'team';
  owner?: CustomModelOwner;
  /** The owning team on a team's model; null on a person's own. */
  team_id?: string | null;
  /** Who added a team's model; null on a person's own. */
  created_by?: CustomModelAddedBy | null;
  allowed_actions?: CustomModelAction[];
}

export interface CreateCustomModelPayload {
  upstream_model_id: string;
  display_name: string;
  description?: string;
  base_url: string;
  api_key?: string;
  capabilities: CustomModelCapabilities;
  enabled: boolean;
  /**
   * Create only: `team` adds it for the team the workspace header names
   * (Admins and the Owner); left out, it is the caller's own.
   */
  owner?: CustomModelOwner;
}

/** The team's agents and workflows that named a deleted team model. */
export type CustomModelUsage = {
  agents: { id: string; name: string }[];
  workflows: { id: string; name: string }[];
};

/** `DELETE /api/user/models/<id>`; a team's model adds its `usage`. */
export type CustomModelDeleteResult = {
  success: boolean;
  usage?: CustomModelUsage;
};

export interface CustomModelTestResult {
  ok: boolean;
  error?: string;
  /** The refusal code when the server turned the test down (a role, a missing model). */
  code?: string;
}

/**
 * Why an agent import leaves a custom model off in a team: only Admins add
 * one with its key, and never through an access token.
 */
export type ImportModelRefusal =
  'custom_model_admin_required' | 'not_available_to_tokens';
