import type { WorkspaceRow } from '../../workspace/workspaceSlice';
import { workspaceHeader } from '../../workspace/requestWorkspace';
import apiClient from '../client';
import endpoints from '../endpoints';

/** What can be moved between workspaces. */
export type MoveItemType = 'agent' | 'source' | 'tool' | 'prompt' | 'folder';

/** A move's request body, for the plan and for applying it. */
export type MoveRequest = {
  to: { workspace: string; folder_id?: string | null };
  items: { type: MoveItemType; id: string }[];
  /** The plan's fingerprint; apply only. */
  fingerprint?: string;
};

type Named = { type: MoveItemType | 'model'; id: string; name: string };

export type MoveWithReason = 'used_by_agent' | 'in_folder' | 'same_workflow';

export type CannotMoveReason =
  | 'connection_account'
  | 'connector_synced'
  | 'custom_model'
  | 'remote_device'
  | 'not_yours'
  | 'in_knowledge_folder'
  | 'credentials_unreadable';

export type CannotMoveEffect = 'removed_from_holder' | 'stays';

export type PersonRef = { user_id: string; label?: string | null };

export type OutsideAccess = {
  api_key: boolean;
  public_link: boolean;
  webhook: boolean;
  paid_by?: PersonRef | string | null;
};

/** The plan `POST /api/workspace_moves/plan` answers with. */
export type MovePlan = {
  to: {
    workspace: {
      kind: 'personal' | 'team';
      team_id: string | null;
      name: string;
    };
    folder: { id: string; name: string; path: string } | null;
  };
  items: Named[];
  moves_with: (Named & {
    via: { type: MoveItemType; id: string };
    reason: MoveWithReason;
  })[];
  cannot_move: (Named & {
    reason: CannotMoveReason;
    effect: CannotMoveEffect;
  })[];
  access: {
    gains: { total: number; viewers: number; editors: number; admins: number };
    loses: { user_id: string; label?: string | null; via?: string | null }[];
  };
  kept: {
    schedules: { id: string; agent_id: string; paid_by?: PersonRef | null }[];
    outside_access?: OutsideAccess | null;
  };
  borrowing_agents: { id: string; name: string; published?: boolean }[];
  borrowing_others?: number;
  needs_admin: { id: string; name: string }[];
  conversations_switched: number;
  renames: {
    type: MoveItemType;
    id: string;
    from: string;
    to: string;
    field?: string;
  }[];
  fingerprint: string;
};

/** The codes a refused plan or move answers with. */
export type MoveErrorCode =
  | 'move_plan_changed'
  | 'move_would_borrow'
  | 'move_needs_admin'
  | 'credentials_unreadable'
  | 'credentials_unavailable'
  | 'nothing_to_move'
  | 'fingerprint_required'
  | 'folder_too_deep'
  | 'already_in_workspace'
  | 'invalid_request'
  | 'workspace_role_required'
  | 'not_a_person'
  | 'workspace_not_found'
  | 'not_found'
  | 'folder_not_found'
  | 'move_failed';

/** A refusal's whole body: `plan` on a changed plan, `agents`/`others`/`tools` on the others. */
export type MoveErrorBody = {
  success?: false;
  error?: string;
  message?: string;
  plan?: MovePlan;
  agents?: { id: string; name: string }[];
  others?: number;
  tools?: { id: string; name: string }[];
  [key: string]: unknown;
};

export type MoveResult =
  | { ok: true; status: number; plan: MovePlan }
  | {
      ok: false;
      status: number;
      error: MoveErrorCode | string;
      message: string;
      body: MoveErrorBody;
    };

const readBody = async (
  response: Response,
): Promise<(MoveErrorBody & { moved?: MovePlan }) | null> => {
  try {
    const body: unknown = await response.json();
    return body && typeof body === 'object' ? (body as MoveErrorBody) : null;
  } catch {
    return null;
  }
};

/**
 * A plan or apply response as data: the plan on success, else the refusal's
 * code (`move_failed` when the body says none) and its body.
 */
const moveResult = async (
  response: Response,
  key: 'plan' | 'moved',
): Promise<MoveResult> => {
  const body = await readBody(response);
  if (response.ok && body?.success !== false) {
    return {
      ok: true,
      status: response.status,
      plan: body?.[key] as MovePlan,
    };
  }
  return {
    ok: false,
    status: response.status,
    error: typeof body?.error === 'string' ? body.error : 'move_failed',
    message: typeof body?.message === 'string' ? body.message : '',
    body: body ?? {},
  };
};

const workspacesService = {
  /**
   * Personal and every team the caller is in, with the caller's role in each.
   * Rejects when the list can't be read.
   */
  list: async ({
    token,
  }: {
    token: string | null;
  }): Promise<WorkspaceRow[]> => {
    const response: Response = await apiClient.get(
      endpoints.USER.WORKSPACES,
      token,
    );
    if (!response.ok)
      throw new Error(`Failed to load workspaces (${response.status})`);
    const body = await response.json();
    return Array.isArray(body?.workspaces) ? body.workspaces : [];
  },

  /**
   * Plans a move: what comes along, what can't, who gains or loses access.
   * Changes nothing.
   *
   * Args:
   *   body: The target and the items.
   *   options.token: The session token.
   *   options.workspace: Send the request for this workspace instead of the
   *     current one.
   */
  planMove: async (
    body: MoveRequest,
    { token, workspace }: { token: string | null; workspace?: string },
  ): Promise<MoveResult> =>
    moveResult(
      await apiClient.post(
        endpoints.USER.WORKSPACE_MOVE_PLAN,
        body,
        token,
        workspace ? workspaceHeader(workspace) : {},
      ),
      'plan',
    ),

  /**
   * Applies a planned move; `body.fingerprint` must be the plan's. A changed
   * plan answers `move_plan_changed` with the fresh one in `body.plan`.
   */
  applyMove: async (
    body: MoveRequest,
    { token }: { token: string | null },
  ): Promise<MoveResult> =>
    moveResult(
      await apiClient.post(endpoints.USER.WORKSPACE_MOVES, body, token),
      'moved',
    ),
};

export default workspacesService;
