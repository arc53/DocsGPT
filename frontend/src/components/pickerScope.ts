import type { TFunction } from 'i18next';
import { useCallback, useMemo } from 'react';
import { useSelector } from 'react-redux';

import { PERSONAL_WORKSPACE } from '../workspace/requestWorkspace';
import { selectFolderWorkspaceId } from './folders/folderWorkspace';
import {
  type FolderTree,
  folderPath,
  formatFolderPath,
} from './folders/folderTree';

/** Where an item or a holder (an agent, a workflow) lives. */
export type ItemWorkspace =
  { kind: 'personal' | 'team'; team_id?: string | null } | null | undefined;

/** An item filed in the workspace's folder tree (tools, prompts, sources). */
export type FiledItem = {
  folder_id?: string | null;
  folder_path?: { id: string; name: string }[] | null;
};

/** The agent or workflow a picker is opened from, and the group it heads. */
export type HolderFolder = { id: string; heading: string };

/**
 * The workspace id of an item's `workspace` field: `personal`, a team id,
 * or null when the field is missing (an older server, a preset).
 */
export function workspaceIdOf(workspace: ItemWorkspace): string | null {
  if (!workspace) return null;
  if (workspace.kind === 'team') return workspace.team_id ?? null;
  return PERSONAL_WORKSPACE;
}

/**
 * Whether a listed row belongs to a workspace. A row that names no
 * workspace (a preset prompt, a built-in tool) belongs to every one.
 *
 * Args:
 *   row: A list row.
 *   workspaceId: `personal` or a team id.
 *
 * Returns:
 *   False only for a row that names another workspace.
 */
export function belongsToWorkspace(row: object, workspaceId: string): boolean {
  const workspace = (row as { workspace?: ItemWorkspace }).workspace;
  if (!workspace) return true;
  return workspaceIdOf(workspace) === workspaceId;
}

/**
 * A picker's rows for the current workspace. The lists come from the
 * workspace the requests named, and a switch resets them, but a list can
 * still hold rows from before (a slow answer, a page that kept a copy);
 * those never show. While the holder lives in another workspace than the
 * lists (a team agent opened from Personal, before the page follows it),
 * only rows that name no workspace show.
 *
 * Args:
 *   rows: The list as loaded; null while it hasn't loaded.
 *   workspaceId: The workspace the app is in.
 *   holderWorkspaceId: The workspace the agent or workflow lives in; left
 *     out or null when unknown (a new one lives where the app is).
 *
 * Returns:
 *   The rows a picker may list.
 */
export function scopeToWorkspace<T extends object>(
  rows: readonly T[] | null | undefined,
  workspaceId: string,
  holderWorkspaceId?: string | null,
): T[] {
  const list = rows ?? [];
  const elsewhere =
    Boolean(holderWorkspaceId) && holderWorkspaceId !== workspaceId;
  return list.filter((row) =>
    elsewhere
      ? !(row as { workspace?: ItemWorkspace }).workspace
      : belongsToWorkspace(row, workspaceId),
  );
}

export type PickerScope = {
  /** The workspace the app is in. */
  workspaceId: string;
  /** The holder lives in another workspace than the lists. */
  holderElsewhere: boolean;
  /** A list as a picker may show it (`scopeToWorkspace`). */
  scope: <T extends object>(rows: readonly T[] | null | undefined) => T[];
};

/**
 * The current workspace and how a picker trims its lists to it.
 *
 * Args:
 *   holderWorkspace: The `workspace` of the agent or workflow being
 *     edited; left out for a new one or a chat.
 *
 * Returns:
 *   The workspace id, whether the holder lives elsewhere, and `scope`.
 */
export function usePickerScope(holderWorkspace?: ItemWorkspace): PickerScope {
  const workspaceId = useSelector(selectFolderWorkspaceId);
  const holderId = workspaceIdOf(holderWorkspace);
  const scope = useCallback(
    <T extends object>(rows: readonly T[] | null | undefined) =>
      scopeToWorkspace(rows, workspaceId, holderId),
    [workspaceId, holderId],
  );
  return useMemo(
    () => ({
      workspaceId,
      holderElsewhere: holderId !== null && holderId !== workspaceId,
      scope,
    }),
    [workspaceId, holderId, scope],
  );
}

/**
 * The folder an item is filed in, as one line ("Carriers › Rates"): from
 * its own trail, else from the tree.
 *
 * Args:
 *   item: A filed item.
 *   tree: The workspace's folder tree, when the item carries no trail.
 *
 * Returns:
 *   The trail, or null for an item in no folder.
 */
export function folderTrailOf(
  item: FiledItem,
  tree?: FolderTree,
): string | null {
  if (!item.folder_id) return null;
  if (item.folder_path && item.folder_path.length > 0)
    return item.folder_path.map((folder) => folder.name).join(' › ');
  const path = tree ? folderPath(tree, item.folder_id) : [];
  return path.length > 0 ? formatFolderPath(path) : null;
}

/**
 * A picker's rows split for a holder filed in a folder: the rows filed in
 * that folder, the rows filed in any other folder, and the rest, each in
 * the list's order. With no holder folder every row is in `rest`.
 *
 * Args:
 *   rows: The rows.
 *   holderFolderId: The holder's folder, or null.
 *
 * Returns:
 *   `holder`, `filed` and `rest`.
 */
export function splitByHolderFolder<T extends FiledItem>(
  rows: readonly T[],
  holderFolderId: string | null | undefined,
): { holder: T[]; filed: T[]; rest: T[] } {
  if (!holderFolderId) return { holder: [], filed: [], rest: [...rows] };
  const holder: T[] = [];
  const filed: T[] = [];
  const rest: T[] = [];
  rows.forEach((row) => {
    if (row.folder_id === holderFolderId) holder.push(row);
    else if (row.folder_id) filed.push(row);
    else rest.push(row);
  });
  return { holder, filed, rest };
}

/**
 * The holder's folder as a picker's first group: "In Carriers, this
 * agent's folder".
 *
 * Args:
 *   t: The translator.
 *   tree: The workspace's folder tree.
 *   folderId: The holder's folder, or null.
 *   holder: An agent or a workflow.
 *
 * Returns:
 *   The folder's id and the group's heading; null when the holder is in
 *   no folder, or one the tree doesn't hold.
 */
export function holderFolderOf(
  t: TFunction,
  tree: FolderTree,
  folderId: string | null | undefined,
  holder: 'agent' | 'workflow',
): HolderFolder | null {
  const folder = folderId ? tree.byId.get(folderId) : undefined;
  if (!folder) return null;
  return {
    id: folder.id,
    heading: t(
      holder === 'agent'
        ? 'workspace.pickers.inAgentFolder'
        : 'workspace.pickers.inWorkflowFolder',
      { folder: folder.name, interpolation: { escapeValue: false } },
    ),
  };
}
