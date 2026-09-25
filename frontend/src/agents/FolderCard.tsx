import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Pencil, Trash2 } from 'lucide-react';

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
  isExpanded: boolean;
  onToggleExpand: (folderId: string) => void;
};

export default function FolderCard({
  folder,
  agentCount,
  onDelete,
  onRename,
  isExpanded,
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
      <div
        role="button"
        tabIndex={0}
        aria-pressed={isExpanded}
        className={`focus-visible:ring-ring/50 focus-visible:border-ring relative flex cursor-pointer items-center justify-between rounded-2xl px-4 py-3 outline-none focus-visible:ring-3 sm:w-48 ${
          isExpanded ? 'bg-accent' : 'bg-muted hover:bg-accent'
        }`}
        onClick={() => onToggleExpand(folder.id)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onToggleExpand(folder.id);
          }
        }}
      >
        <div className="flex items-center gap-2 overflow-hidden">
          <span className="text-foreground truncate text-sm font-medium">
            {folder.name}
          </span>
          <span className="text-muted-foreground shrink-0 text-xs">
            ({agentCount})
          </span>
        </div>
        <ActionMenu
          options={menuOptions}
          triggerLabel={t('agents.folders.menuAriaLabel', {
            folderName: folder.name,
            defaultValue: 'Folder actions',
          })}
          align="end"
          className="ml-2 shrink-0"
        />
      </div>
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
        variant="danger"
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
