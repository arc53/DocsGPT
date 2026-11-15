import type { ReactNode } from 'react';

import type { MenuOption } from '../../components/ui/dropdown-menu';
import type { MoveItemType } from '../../api/services/workspacesService';
import type { WorkspaceItemFields } from '../itemOrigin';

/** An item or folder a Move to team / Move to Personal option is built for. */
export type MovableItem = WorkspaceItemFields & {
  id: string;
  name: string;
  allowed_actions?: string[];
};

export type MoveMenuOptions = {
  /** Called after a move succeeds, so the page can reload its list. */
  onMoved?: () => void;
};

export type UseMoveToWorkspace = {
  /** The ⋯ menu row for this item, or null when it can't be moved. */
  menuOption: (
    item: MovableItem,
    options?: MoveMenuOptions,
  ) => MenuOption | null;
  /** The Move dialog, rendered once by the page. */
  dialog: ReactNode;
};

/**
 * "Move to team…" / "Move to Personal…" for one kind of item: a ⋯ menu row
 * and the dialog it opens. Offers nothing yet.
 *
 * Args:
 *   kind: The kind of item the page lists (`folder` for folder tiles).
 *
 * Returns:
 *   `menuOption(item, { onMoved })` and the `dialog` to render.
 */
export default function useMoveToWorkspace(
  kind: MoveItemType,
): UseMoveToWorkspace {
  void kind;
  return { menuOption: () => null, dialog: null };
}

export { useMoveToWorkspace };
