import { SyntheticEvent, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import Edit from '../assets/edit.svg';
import Trash from '../assets/red-trash.svg';
import ThreeDots from '../assets/three-dots.svg';
import ContextMenu, { MenuOption } from '../components/ContextMenu';
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
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [deleteConfirmation, setDeleteConfirmation] =
    useState<ActiveState>('INACTIVE');
  const [renameModalState, setRenameModalState] =
    useState<ActiveState>('INACTIVE');
  const menuRef = useRef<HTMLDivElement>(null);

  const menuOptions: MenuOption[] = [
    {
      icon: Edit,
      label: t('agents.folders.rename'),
      onClick: (e: SyntheticEvent) => {
        e.stopPropagation();
        setRenameModalState('ACTIVE');
        setIsMenuOpen(false);
      },
      variant: 'primary',
      iconWidth: 14,
      iconHeight: 14,
    },
    {
      icon: Trash,
      label: t('agents.folders.delete'),
      onClick: (e: SyntheticEvent) => {
        e.stopPropagation();
        setDeleteConfirmation('ACTIVE');
        setIsMenuOpen(false);
      },
      variant: 'danger',
      iconWidth: 13,
      iconHeight: 13,
    },
  ];

  const handleRename = (newName: string) => {
    onRename(folder.id, newName);
  };

  return (
    <>
      <div
        className={`relative flex cursor-pointer items-center justify-between rounded-[1.2rem] px-4 py-3 sm:w-48 ${
          isExpanded ? 'bg-accent' : 'bg-muted hover:bg-accent'
        }`}
        onClick={() => onToggleExpand(folder.id)}
      >
        <div className="flex items-center gap-2 overflow-hidden">
          <span className="text-foreground truncate text-sm font-medium">
            {folder.name}
          </span>
          <span className="text-muted-foreground shrink-0 text-xs">
            ({agentCount})
          </span>
        </div>
        <div
          ref={menuRef}
          onClick={(e) => {
            e.stopPropagation();
            setIsMenuOpen(true);
          }}
          className="ml-2 shrink-0 cursor-pointer"
        >
          <img src={ThreeDots} alt="menu" className="h-4 w-4" />
          <ContextMenu
            isOpen={isMenuOpen}
            setIsOpen={setIsMenuOpen}
            options={menuOptions}
            anchorRef={menuRef}
            position="bottom-right"
            offset={{ x: 0, y: 0 }}
          />
        </div>
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
