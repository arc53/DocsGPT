import { FolderInput, Pencil, Trash2 } from 'lucide-react';
import { type ReactNode, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import ConfirmationModal from '../../modals/ConfirmationModal';
import { formatCount } from '../../utils/dateTimeUtils';
import { agentUseCount } from '../../utils/resourceUsage';
import { Alert, AlertDescription } from '../ui/alert';
import type { MenuOption } from '../ui/dropdown-menu';
import {
  folderDeleteConsequence,
  folderErrorMessage,
  folderRootLabel,
} from './folderCopy';
import FolderNameModal from './FolderNameModal';
import { selectFolders } from './foldersSlice';
import MoveToFolderModal from './MoveToFolderModal';
import type { Folder, FolderType } from './types';
import { useFolderActions } from './useFolderActions';

type Dialog = { mode: 'rename' | 'move' | 'delete'; folder: Folder } | null;

export type FolderMenu = {
  /** A folder's ⋯ items: Rename, Move to folder, then Delete after a rule. */
  menuOptions: (folder: Folder) => MenuOption[];
  /** The rename, move and delete dialogs; render once on the page. */
  dialogs: ReactNode;
};

/**
 * A folder's ⋯, the same on its tile and on its crumb row: Rename and Move
 * to folder open the shared dialogs, Delete confirms with what moves where
 * ("Its 2 agents move to My agents. Nothing is deleted.") and, for a source
 * folder agents read, which agents lose it.
 *
 * Args:
 *   type: The folders' type.
 *   onDeleted: After a delete, with the folder's parent (null: the root),
 *     so a page showing the folder can step out of it.
 */
export function useFolderMenu(
  type: FolderType,
  onDeleted?: (folder: Folder, parentId: string | null) => void,
): FolderMenu {
  const { t } = useTranslation();
  const actions = useFolderActions(type);
  const folders = useSelector(selectFolders(type));
  const [dialog, setDialog] = useState<Dialog>(null);

  const menuOptions = (folder: Folder): MenuOption[] => [
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
    {
      icon: Trash2,
      label: t('folders.delete'),
      onClick: () => setDialog({ mode: 'delete', folder }),
      variant: 'destructive',
      separatorBefore: true,
    },
  ];

  const close = () => setDialog(null);
  // The latest copy, so the counts are the server's after a reload.
  const folder = dialog
    ? (folders.find((f) => f.id === dialog.folder.id) ?? dialog.folder)
    : null;
  const parent = folder?.parent_id
    ? (folders.find((f) => f.id === folder.parent_id) ?? null)
    : null;
  const parentLabel = parent ? parent.name : folderRootLabel(t, type);

  const users = folder?.used_by;
  const userCount = agentUseCount(users);
  const names = (users?.agents ?? []).map((agent) => agent.name).join(', ');
  const usedWarning =
    type === 'source' && userCount > 0 ? (
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
        type={type}
        mode="rename"
        folder={dialog?.mode === 'rename' ? folder : null}
      />
      {dialog?.mode === 'move' && folder ? (
        <MoveToFolderModal
          open
          onOpenChange={(open) => !open && close()}
          type={type}
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
            ? folderDeleteConsequence(t, folder, type, parentLabel)
            : undefined
        }
        modalState={dialog?.mode === 'delete' ? 'ACTIVE' : 'INACTIVE'}
        setModalState={(state) => state === 'INACTIVE' && close()}
        submitLabel={t('folders.deleteFolder')}
        handleSubmit={async () => {
          if (!folder) return;
          await actions.remove(folder.id, parent?.id ?? null);
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
    </>
  );

  return { menuOptions, dialogs };
}
