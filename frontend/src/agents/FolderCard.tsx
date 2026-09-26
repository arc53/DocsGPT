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
      <Card
        variant="filled"
        interactive
        padding="default"
        role="button"
        tabIndex={0}
        className="relative flex-row items-center justify-between"
        onClick={() => onToggleExpand(folder.id)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onToggleExpand(folder.id);
          }
        }}
      >
        <div className="flex items-center gap-2 overflow-hidden">
          <CardTitle className="truncate">{folder.name}</CardTitle>
          <span className="text-muted-foreground shrink-0 text-xs">
            ({agentCount})
          </span>
        </div>
        <ActionMenu
          options={menuOptions}
          triggerLabel={t('agents.folders.menuAriaLabel', {
            folderName: folder.name,
            interpolation: { escapeValue: false },
          })}
          align="end"
          className="ml-2 shrink-0"
        />
      </Card>
      <ConfirmationModal
        message={t('agents.folders.deleteConfirm')}
        modalState={deleteConfirmation}
        setModalState={setDeleteConfirmation}
        submitLabel={t('convTile.delete')}
        handleSubmit={() => {
          onDelete(folder.id);
          setDeleteConfirmation('INACTIVE');
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
