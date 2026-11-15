import { ArrowRightLeft } from 'lucide-react';
import { type ReactNode, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import type { MoveItemType } from '../../api/services/workspacesService';
import type { MenuOption } from '../../components/ui/dropdown-menu';
import type { WorkspaceItemFields } from '../itemOrigin';
import MoveToWorkspaceModal from './MoveToWorkspaceModal';
import {
  moveDirection,
  selectMoveCurrentId,
  selectMoveWorkspaces,
} from './moveTargets';

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

type Open = { item: MovableItem; onMoved?: () => void } | null;

/**
 * "Move to team…" / "Move to Personal…" for one kind of item: a ⋯ menu row
 * and the dialog it opens. An own item offers Move to team… when some team
 * takes it (the caller is Editor or above there); a team's item offers Move
 * to Personal… to the team's Admins. Shared items offer nothing.
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
  const { t } = useTranslation();
  const workspaces = useSelector(selectMoveWorkspaces);
  const currentId = useSelector(selectMoveCurrentId);
  const [open, setOpen] = useState<Open>(null);

  const menuOption = (
    item: MovableItem,
    { onMoved }: MoveMenuOptions = {},
  ): MenuOption | null => {
    const direction = moveDirection(item, workspaces, currentId);
    if (!direction) return null;
    return {
      icon: ArrowRightLeft,
      label: t(
        direction === 'in'
          ? 'workspace.menu.moveToTeam'
          : 'workspace.menu.moveToPersonal',
      ),
      onClick: () => setOpen({ item, onMoved }),
    };
  };

  const dialog = open ? (
    <MoveToWorkspaceModal
      subject={{ type: kind, id: open.item.id, name: open.item.name }}
      from={open.item.workspace ?? null}
      onClose={() => setOpen(null)}
      onMoved={open.onMoved}
    />
  ) : null;

  return { menuOption, dialog };
}

export { useMoveToWorkspace };
