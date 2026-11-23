import { can } from '../../utils/accessUtils';
import type { WorkspaceItemFields } from '../itemOrigin';
import { PERSONAL_WORKSPACE } from '../requestWorkspace';
import {
  roleAtLeast,
  type WorkspaceRow,
  type WorkspaceState,
} from '../workspaceSlice';

// Menus and the share dialog render inside pages whose tests build a store
// without the workspace slice; read such a store as Personal alone.
type RootLike = { workspace?: WorkspaceState };
const NO_WORKSPACES: WorkspaceRow[] = [];

/** The caller's workspaces, or none when the store has no workspace slice. */
export const selectMoveWorkspaces = (state: RootLike): WorkspaceRow[] =>
  state.workspace?.workspaces ?? NO_WORKSPACES;

/** The current workspace, Personal when the store has no workspace slice. */
export const selectMoveCurrentId = (state: RootLike): string =>
  state.workspace?.current ?? PERSONAL_WORKSPACE;

/** The teams an item can move into: those where the caller is Editor or above. */
export const moveTargets = (
  workspaces: WorkspaceRow[] | null | undefined,
): WorkspaceRow[] =>
  Array.isArray(workspaces)
    ? workspaces.filter(
        (row) => row.kind === 'team' && roleAtLeast(row.role, 'editor'),
      )
    : [];

/** An item as the move rules read it. */
export type MoveCandidate = WorkspaceItemFields & {
  allowed_actions?: string[];
};

/**
 * Which move an item offers: `in` (its owner takes it to a team where they
 * are Editor or above), `out` (a team Admin takes the team's item to their
 * own Personal), or null.
 *
 * The server's `allowed_actions` decide (`move_to_team`, `move_out`). A
 * folder carries none: an own folder moves in like an own item, and a team
 * folder moves out for the team's Admins and its Owner.
 *
 * Args:
 *   item: The item or folder.
 *   workspaces: The caller's workspaces, with their role in each team.
 *   currentId: The current workspace, for an item that doesn't say its own.
 *
 * Returns:
 *   The direction, or null when the item can't move.
 */
export function moveDirection(
  item: MoveCandidate,
  workspaces: WorkspaceRow[] | null | undefined,
  currentId: string | null | undefined,
): 'in' | 'out' | null {
  // Without the caller's workspaces there is no telling where it could go.
  if (!Array.isArray(workspaces) || item.origin === 'shared') return null;
  const teamId =
    item.workspace?.kind === 'team'
      ? (item.workspace.team_id ?? null)
      : item.workspace?.kind === 'personal'
        ? null
        : currentId && currentId !== PERSONAL_WORKSPACE
          ? currentId
          : null;
  if (teamId) {
    if (item.allowed_actions) return can(item, 'move_out') ? 'out' : null;
    const role = workspaces.find((row) => row.id === teamId)?.role;
    return roleAtLeast(role, 'admin') ? 'out' : null;
  }
  if (item.allowed_actions && !can(item, 'move_to_team')) return null;
  return moveTargets(workspaces).length > 0 ? 'in' : null;
}
