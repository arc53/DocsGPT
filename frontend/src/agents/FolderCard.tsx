import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Pencil, Trash2 } from 'lucide-react';

import { Card, CardTitle } from '../components/ui/card';
import { ActionMenu, type MenuOption } from '../components/ui/dropdown-menu';
import ConfirmationModal from '../modals/ConfirmationModal';
import FolderNameModal from '../modals/FolderManagementModal';
import { ActiveState } from '../models/misc';

import { AgentFolder } from './types';

type FolderCardProps = {
  folder: AgentFolder;
  agentCount: number;
  onDelete: (folderId: string) => Promise<boolean>;
  onRename: (folderId: string, newName: string) => void;
  onToggleExpand: (folderId: string) => void;
};

export default function FolderCard({
  folder,
  agentCount,
  onDelete,
  onRename,
  onToggleExpand,
}: FolderCardProps) {
  const { t } = useTranslation();
  const [deleteConfirmation, setDeleteConfirmation] =
    useState<ActiveState>('INACTIVE');
  const [renameModalState, setRenameModalState] =
    useState<ActiveState>('INACTIVE');

  const menuOptions: MenuOption[] = [
    {
      icon: Pencil,
      label: t('agents.folders.rename'),
      onClick: () => setRenameModalState('ACTIVE'),
    },
    {
      icon: Trash2,
      label: t('agents.folders.delete'),
      onClick: () => setDeleteConfirmation('ACTIVE'),
      variant: 'destructive',
    },
  ];

  const handleRename = (newName: string) => {
    onRename(folder.id, newName);
  };

  return (
    <>
      {/* DESIGN "A clickable card that holds a link": a stretched button
          opens the folder; the menu is a sibling above it, never inside. */}
      <Card
        variant="filled"
        interactive="within"
        className="flex-row items-center justify-between"
      >
        <button
          type="button"
          onClick={() => onToggleExpand(folder.id)}
          className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 text-left outline-none after:absolute after:inset-0 after:rounded-2xl"
        >
          <CardTitle className="truncate" title={folder.name}>
            {folder.name}
          </CardTitle>
          <span className="text-muted-foreground shrink-0 text-xs">
            ({agentCount})
          </span>
        </button>
        <div className="relative z-10 ml-2 shrink-0">
          <ActionMenu
            options={menuOptions}
            triggerLabel={t('agents.folders.menuAriaLabel', {
              folderName: folder.name,
              interpolation: { escapeValue: false },
            })}
            align="end"
          />
        </div>
      </Card>
      <ConfirmationModal
        message={t('agents.folders.deleteConfirm')}
        modalState={deleteConfirmation}
        setModalState={setDeleteConfirmation}
        submitLabel={t('convTile.delete')}
        handleSubmit={async () => {
          if (!(await onDelete(folder.id))) {
            throw new Error('Failed to delete folder');
          }
        }}
        cancelLabel={t('cancel')}
        variant="destructive"
      />
      <FolderNameModal
        modalState={renameModalState}
        setModalState={setRenameModalState}
        mode="rename"
        initialName={folder.name}
        onSubmit={handleRename}
      />
    </>
  );
}
