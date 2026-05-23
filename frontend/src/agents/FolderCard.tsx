import { SyntheticEvent, useState } from 'react';
import { useTranslation } from 'react-i18next';

import Edit from '../assets/edit.svg';
import Trash from '../assets/red-trash.svg';
import ThreeDots from '../assets/three-dots.svg';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '../components/ui/dropdown-menu';
import ConfirmationModal from '../modals/ConfirmationModal';
import FolderNameModal from '../modals/FolderManagementModal';
import { ActiveState } from '../models/misc';
import { AgentFolder } from './types';

type FolderMenuOption = {
  icon: string;
  label: string;
  onClick: (event: SyntheticEvent) => void;
  variant: 'default' | 'destructive';
  iconWidth?: number;
  iconHeight?: number;
};

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

  const menuOptions: FolderMenuOption[] = [
    {
      icon: Edit,
      label: t('agents.folders.rename'),
      onClick: (e: SyntheticEvent) => {
        e.stopPropagation();
        setRenameModalState('ACTIVE');
      },
      variant: 'default',
      iconWidth: 14,
      iconHeight: 14,
    },
    {
      icon: Trash,
      label: t('agents.folders.delete'),
      onClick: (e: SyntheticEvent) => {
        e.stopPropagation();
        setDeleteConfirmation('ACTIVE');
      },
      variant: 'destructive',
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
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              onClick={(e) => e.stopPropagation()}
              className="ml-2 shrink-0 cursor-pointer"
              aria-label={t('agents.folders.rename')}
            >
              <img src={ThreeDots} alt="menu" className="h-4 w-4" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="min-w-[144px]">
            {menuOptions.map((option, index) => (
              <DropdownMenuItem
                key={index}
                variant={option.variant}
                onSelect={(event) => {
                  option.onClick(event as unknown as SyntheticEvent);
                }}
              >
                <img
                  src={option.icon}
                  alt=""
                  width={option.iconWidth ?? 16}
                  height={option.iconHeight ?? 16}
                />
                <span>{option.label}</span>
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
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
