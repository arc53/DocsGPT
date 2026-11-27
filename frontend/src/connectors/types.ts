import type { PausedFor } from '../payer/types';

export type ConnectorCategory =
  | 'files'
  | 'knowledge'
  | 'projects'
  | 'dev'
  | 'business'
  | 'messaging'
  | 'database'
  | 'search'
  | 'custom';

export type Capability = 'sync' | 'read' | 'write';

export type ConnectorAuthKind =
  'oauth' | 'mcp_oauth' | 'api_key' | 'none' | 'mcp';

/**
 * `paused`: a team's account the team can't use now (whoever connected it
 * left, lost the Admin role or was deactivated); `paused_for` says why.
 */
export type ConnectionStatus =
  | 'connected'
  | 'reconnect_needed'
  | 'disconnected'
  | 'error'
  | 'pending'
  | 'paused';

/** What a catalog card shows, worked out on the server. */
export type ConnectorCardState =
  | 'available'
  | 'connected'
  | 'reconnect'
  | 'needs_setup'
  | 'disabled'
  | 'custom'
  | 'paused';

export type CredentialMode = 'owner' | 'member';

export type CredentialField = {
  key: string;
  label: string;
  secret: boolean;
  required: boolean;
  /** A tool parameter this field sets for every call (Telegram's chat). */
  parameter?: string | null;
  /** English help under the field; translated when the locale has it. */
  hint?: string | null;
  /** Where the hint's `<link>…</link>` words point. */
  hint_url?: string | null;
  /** A regular expression the whole value must match; the server checks it too. */
  pattern?: string | null;
};

export type ConnectorDefinition = {
  key: string;
  name: string;
  description: string;
  icon: string;
  category: ConnectorCategory;
  auth_kind: ConnectorAuthKind;
  capabilities: Capability[];
  credential_fields: CredentialField[];
  setup_fields: CredentialField[];
  sync_ingestor: string | null;
  default_sync_frequency: string;
  tool_templates: string[];
  setup: { tools: 'auto' | 'ask' | 'off'; sync: 'auto' | 'ask' | 'off' };
  mcp_url: string | null;
  /** Its tool can also make changes, when a connection opts in (GitHub). */
  writes_opt_in?: boolean;
  publisher: 'built_in' | 'preset' | 'custom';
  docs_url: string | null;
  oauth_scopes: string[];
  /** Shown under this connector's card (one service offered two ways). */
  part_of?: string | null;
  /**
   * How a user can connect, preferred first. GitHub offers `oauth` (Sign in
   * with GitHub, once an admin sets up the GitHub App) before `api_key`.
   */
  sign_in_methods?: ConnectorAuthKind[];
  /**
   * The OAuth client id Google's own picker opens with. Set for Google
   * Drive with per-file access, where only Google's picker can choose files.
   */
  picker_client_id?: string | null;
  available: boolean;
  disabled: boolean;
  needs_setup: boolean;
  missing_settings: string[];
  connected_count: number;
  connection_count: number;
  status: ConnectionStatus | null;
  state: ConnectorCardState;
  credential_policy: 'choose' | CredentialMode;
  /** A connection may opt into changes: offered, and no admin forbade it. */
  writes_allowed?: boolean;
  /**
   * Query parameters an MCP preset's URL must carry, asked for before
   * sign-in (Supabase's project ref, which keeps it to one project).
   */
  url_parameters?: CredentialField[];
};

/** Whose a connection is: the caller's own, or a team's (`owner=team`). */
export type ConnectionOwner = 'personal' | 'team';

/**
 * What the caller may do with a connection. On a team's: `view` any member,
 * `sync` Editors, `manage` Admins, `pick` (browse the account to choose what
 * to sync) only whoever connected it, while they are an Admin.
 */
export type ConnectionAction = 'view' | 'sync' | 'manage' | 'pick';

/** Who connected a team's account; `label` is their email, else their id. */
export type ConnectedBy = { user_id: string; label: string };

/** Why a team's account is paused (`Pause.payload()` on the server). */
export type ConnectionPausedFor = Pick<
  PausedFor,
  'reason' | 'until' | 'left_team'
>;

/**
 * The team fields every connection payload carries. Optional for servers
 * from before team connections: read them through `teamConnections.ts`,
 * which treats a row without them as the caller's own.
 */
export type ConnectionTeamFields = {
  owner?: ConnectionOwner;
  /** The team that owns it; null on a personal connection. */
  team_id?: string | null;
  /** Null on a personal connection (and on a broken team row). */
  connected_by?: ConnectedBy | null;
  /** Set while a team's account is paused; then `status` is `paused`. */
  paused_for?: ConnectionPausedFor | null;
  allowed_actions?: ConnectionAction[];
  /** May browse the account now: `pick` allowed and not paused. */
  can_pick?: boolean;
};

export type Connection = ConnectionTeamFields & {
  id: string;
  connector_key: string;
  name: string;
  display_name: string | null;
  icon: string;
  account_label: string;
  /** What the owner calls the account; `account_label` stays its identity. */
  account_name?: string | null;
  auth_kind: ConnectorAuthKind | null;
  status: ConnectionStatus;
  server_url: string | null;
  last_error: string | null;
  created_at: string | null;
  updated_at: string | null;
  last_used_at: string | null;
  source_count: number;
  tool_count: number;
  /** The URL parameter values its preset needs, as last saved (a project ref). */
  url_parameters?: Record<string, string>;
};

export type ActionAccess = 'read' | 'write';
export type ActionPermission = 'always' | 'ask' | 'off';

export type ActionParameter = {
  name: string;
  description: string;
  type: string;
  required: boolean;
  /** Sent with `value` on every call; the AI never sees it. */
  fixed: boolean;
  value: string | number | boolean | null;
  /** Who fixed it: the tool's own setting, or the account (a default chat). */
  set_by?: 'tool' | 'account' | null;
};

/**
 * An MCP action's prompt-injection score, stored when its server's actions
 * were read while Admin › Guardrails warns on tool descriptions.
 */
export type ActionInjection = { p: number; scorer: string } | null;

export type ConnectionToolAction = {
  name: string;
  description: string;
  access: ActionAccess;
  permission: ActionPermission;
  parameters?: ActionParameter[];
  /** Its description's prompt-injection score, while Admin › Guardrails warns on them. */
  injection?: ActionInjection;
};

export type ConnectionTool = {
  id: string;
  name: string;
  display_name: string;
  status: boolean;
  credential_mode: CredentialMode;
  actions: ConnectionToolAction[];
};

export type ConnectionSource = {
  id: string;
  name: string;
  type: string;
  last_sync: string | null;
  sync_frequency: string;
  sync_state: 'active' | 'paused_reconnect';
  /** Its behaviour: `classic`, `wiki` (converted, edited in place), `graphrag`. */
  kind?: string;
};

/** A repository a GitHub connection can read, for the sync picker. */
export type GitHubRepository = {
  full_name: string;
  private: boolean;
  description: string;
  default_branch: string;
  updated_at: string | null;
  html_url: string;
};

/** A Linear team a Linear connection can sync, for the sync picker. */
export type LinearTeam = {
  id: string;
  /** The issue prefix, `ENG` in `ENG-123`. */
  key: string;
  name: string;
};

/** A Linear project a Linear connection can sync, for the sync picker. */
export type LinearProject = {
  id: string;
  name: string;
  state: string;
  /** Names of the teams it belongs to. */
  teams: string[];
};

export type ConnectionDetail = Connection & {
  sources: ConnectionSource[];
  tools: ConnectionTool[];
  /**
   * Whether its tool can make changes (GitHub's write endpoint); null when
   * the connector offers no such choice or the tool is not added yet.
   */
  writes?: boolean | null;
};

/**
 * `POST /api/connections/<id>/reconnect`. An OAuth answer's `replace` is true
 * when the caller is a team Admin other than whoever connected it: their own
 * account takes the connection over in place (same id, sources and tools).
 */
export type ReconnectResult =
  | {
      success: true;
      kind: 'oauth';
      replace: boolean;
      authorization_url: string;
      state: string;
    }
  | { success: true; kind: 'mcp_oauth'; server_url: string | null }
  | { success: true; kind: 'api_key'; connection: Connection }
  | {
      success: false;
      error?: string;
      code?: string;
      message?: string;
      /** `account_already_connected`: the team's row for that account. */
      connection_id?: string;
      paused_for?: ConnectionPausedFor | null;
    };
