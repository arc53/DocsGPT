import { FolderInput, Pencil, Trash2 } from 'lucide-react';
import { type ReactNode, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import ConfirmationModal from '../../modals/ConfirmationModal';
import { showActionToast } from '../../notifications/actionToastSlice';
import { formatCount } from '../../utils/dateTimeUtils';
import { agentUseCount } from '../../utils/resourceUsage';
import type { MovableItem } from '../../workspace/move/useMoveToWorkspace';
import { useMoveToWorkspace } from '../../workspace/move/useMoveToWorkspace';
import { Alert, AlertDescription } from '../ui/alert';
import { ActionMenu, type MenuOption } from '../ui/dropdown-menu';
import {
  folderDeleteConsequence,
  folderErrorMessage,
  folderRenamedMessage,
  folderRootLabel,
} from './folderCopy';
import FolderNameModal from './FolderNameModal';
import { selectFolderTree } from './foldersSlice';
import {
  selectCanEditFolders,
  selectFoldersInTeam,
  selectFolderWorkspaceId,
} from './folderWorkspace';
import MoveToFolderModal from './MoveToFolderModal';
import type { Folder, ItemKind } from './types';
import { useFolderActions } from './useFolderActions';

type Dialog = { mode: 'rename' | 'move' | 'delete'; folder: Folder } | null;

export type FolderMenu = {
  /**
   * A folder's ⋯ items: Rename, Move to folder, Move to team… (or Move to
   * Personal…), then Delete after a rule. Below Editor in a team only the
   * move between workspaces can remain (its hook decides).
   */
  menuOptions: (folder: Folder) => MenuOption[];
  /**
   * The open folder's ⋯ for its crumb row, or null when it would offer
   * nothing (a Viewer in a team the folder can't move out of).
   */
  crumbMenu: (folder: Folder) => ReactNode;
  /** The rename, move, delete and workspace-move dialogs; render once. */
  dialogs: ReactNode;
};

export type FolderMenuOptions = {
  /**
   * After the folder moved to another workspace, so the page can reload its
   * list (the folder tree reloads itself).
   */
  onMovedToWorkspace?: () => void;
};

/**
 * A folder's ⋯, the same on its tile and on its crumb row and on every page:
 * Rename and Move to folder open the shared dialogs, Move to team… /
 * Move to Personal… opens the workspace Move dialog, Delete confirms with
 * what moves where ("Its 2 agents move to My agents. Nothing is deleted.")
 * and, for a folder whose sources agents read, which agents lose it. A
 * delete that renamed folders says so in a toast.
 *
 * Args:
 *   kind: The page's kind (counted first in the delete confirm).
 *   onDeleted: After a delete, with the folder's parent (null: the root),
 *     so a page showing the folder can step out of it.
 *   options.onMovedToWorkspace: After a move to another workspace.
 */
export function useFolderMenu(
  kind: ItemKind,
  onDeleted?: (folder: Folder, parentId: string | null) => void,
  { onMovedToWorkspace }: FolderMenuOptions = {},
): FolderMenu {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const actions = useFolderActions(kind);
  const folders = useSelector(selectFolderTree).items;
  const canEdit = useSelector(selectCanEditFolders);
  const inTeam = useSelector(selectFoldersInTeam);
  const workspaceId = useSelector(selectFolderWorkspaceId);
  const moveToWorkspace = useMoveToWorkspace('folder');
  const [dialog, setDialog] = useState<Dialog>(null);

  // A folder lives in the workspace whose tree lists it.
  const movable = (folder: Folder): MovableItem => ({
    id: folder.id,
    name: folder.name,
    created_by: folder.created_by ?? null,
    workspace: inTeam
      ? { kind: 'team', team_id: workspaceId }
      : { kind: 'personal', team_id: null },
    origin: inTeam ? 'team' : 'own',
  });

  const menuOptions = (folder: Folder): MenuOption[] => {
    const moveOut = moveToWorkspace.menuOption(movable(folder), {
      onMoved: onMovedToWorkspace,
    });
    if (!canEdit) return moveOut ? [moveOut] : [];
    return [
      {
        icon: Pencil,
        label: t('folders.rename'),
        onClick: () => setDialog({ mode: 'rename', folder }),
      },
      {
        icon: FolderInput,
        label: t('folders.moveToFolder'),
        onClick: () => setDialog({ mode: 'move', folder }),
      },
      ...(moveOut ? [moveOut] : []),
      {
        icon: Trash2,
        label: t('folders.delete'),
        onClick: () => setDialog({ mode: 'delete', folder }),
        variant: 'destructive',
        separatorBefore: true,
      },
    ];
  };

  const crumbMenu = (folder: Folder): ReactNode => {
    const options = menuOptions(folder);
    if (options.length === 0) return null;
    return (
      <ActionMenu
        size="toolbar"
        options={options}
        triggerLabel={t('folders.menuLabel', {
          name: folder.name,
          interpolation: { escapeValue: false },
        })}
      />
    );
  };

  const close = () => setDialog(null);
  // The latest copy, so the counts are the server's after a reload.
  const folder = dialog
    ? (folders.find((f) => f.id === dialog.folder.id) ?? dialog.folder)
    : null;
  const parent = folder?.parent_id
    ? (folders.find((f) => f.id === folder.parent_id) ?? null)
    : null;
  const parentLabel = parent
    ? parent.name
    : folderRootLabel(t, kind, { team: inTeam });

  const users = folder?.used_by;
  const userCount = agentUseCount(users);
  const names = (users?.agents ?? []).map((agent) => agent.name).join(', ');
  // The folder's sources are read live whichever page it is deleted from.
  const usedWarning =
    userCount > 0 ? (
      <Alert variant="warning">
        <AlertDescription>
          {names
            ? t('folders.usedByWarning', {
                count: userCount,
                formatted: formatCount(userCount),
                names,
                interpolation: { escapeValue: false },
              })
            : t('folders.usedByWarningNoNames', {
                count: userCount,
                formatted: formatCount(userCount),
              })}
        </AlertDescription>
      </Alert>
    ) : null;

  const dialogs = (
    <>
      <FolderNameModal
        open={dialog?.mode === 'rename'}
        onOpenChange={(open) => !open && close()}
        kind={kind}
        mode="rename"
        folder={dialog?.mode === 'rename' ? folder : null}
      />
      {dialog?.mode === 'move' && folder ? (
        <MoveToFolderModal
          open
          onOpenChange={(open) => !open && close()}
          kind={kind}
          subject={{ kind: 'folder', folder }}
        />
      ) : null}
      <ConfirmationModal
        message={t('folders.deleteConfirm', {
          name: folder?.name ?? '',
          interpolation: { escapeValue: false },
        })}
        description={
          folder
            ? folderDeleteConsequence(t, folder, kind, parentLabel)
            : undefined
        }
        modalState={dialog?.mode === 'delete' ? 'ACTIVE' : 'INACTIVE'}
        setModalState={(state) => state === 'INACTIVE' && close()}
        submitLabel={t('folders.deleteFolder')}
        handleSubmit={async () => {
          if (!folder) return;
          const { renamed } = await actions.remove(
            folder.id,
            parent?.id ?? null,
          );
          const message = folderRenamedMessage(t, renamed);
          if (message)
            dispatch(showActionToast({ variant: 'success', message }));
          onDeleted?.(folder, parent?.id ?? null);
        }}
        error={(reason) =>
          folderErrorMessage(t, reason, 'folders.errors.deleteFailed')
        }
        cancelLabel={t('cancel')}
        variant="destructive"
      >
        {usedWarning}
      </ConfirmationModal>
      {moveToWorkspace.dialog}
    </>
  );

  return { menuOptions, crumbMenu, dialogs };
}
