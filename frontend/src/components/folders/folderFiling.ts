import type { ItemOrigin } from '../../workspace/itemOrigin';

/** The fields of an item that decide whether it can be filed here. */
export type FileableItem = {
  origin?: ItemOrigin | null;
  allowed_actions?: string[] | null;
};

/**
 * Whether an item's ⋯ offers Move to folder in the current workspace. A
 * team's folders hold only the team's own items, and a team's item is never
 * filed in a personal folder (it is pinned instead), so the item's origin
 * must match the tree. An item that lists `allowed_actions` must also allow
 * `move_folder`.
 *
 * Args:
 *   item: The item, with its `origin` and `allowed_actions`.
 *   isTeam: The current workspace is a team.
 *
 * Returns:
 *   True when Move to folder belongs in its menu.
 */
export function canMoveToFolder(item: FileableItem, isTeam: boolean): boolean {
  if (item.allowed_actions && !item.allowed_actions.includes('move_folder'))
    return false;
  // No origin: an API older than workspaces, where everything is one's own.
  const origin = item.origin ?? 'own';
  return isTeam ? origin === 'team' : origin !== 'team';
}
