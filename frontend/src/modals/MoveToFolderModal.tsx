import { useEffect, useState, useMemo } from 'react';
import { useSelector } from 'react-redux';
import { useTranslation } from 'react-i18next';

import userService from '../api/services/userService';
import FolderIcon from '../assets/folder.svg';
import { ActiveState } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import { AgentFolder } from '../agents/types';
import WrapperModal from './WrapperModal';

type MoveToFolderModalProps = {
  modalState: ActiveState;
  setModalState: (state: ActiveState) => void;
  agentName: string;
  agentId: string;
  currentFolderId?: string;
  onMoveSuccess: (folderId: string | null) => void;
};

export default function MoveToFolderModal({
  modalState,
  setModalState,
  agentName,
  agentId,
  currentFolderId,
  onMoveSuccess,
}: MoveToFolderModalProps) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const [folders, setFolders] = useState<AgentFolder[]>([]);
  const [selectedFolderId, setSelectedFolderId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isCreatingFolder, setIsCreatingFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState('');

  useEffect(() => {
    if (modalState === 'ACTIVE') {
      fetchFolders();
      setSelectedFolderId(currentFolderId || null);
    }
  }, [modalState]);

  const fetchFolders = async () => {
    setIsLoading(true);
    try {
      const response = await userService.getAgentFolders(token);
      if (response.ok) {
        const data = await response.json();
        setFolders(data.folders || []);
      }
    } catch (error) {
      console.error('Failed to fetch folders:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleCreateFolder = async () => {
    if (!newFolderName.trim()) return;
    try {
      const response = await userService.createAgentFolder(
        { name: newFolderName.trim() },
        token,
      );
      if (response.ok) {
        const data = await response.json();
        setFolders((prev) => [...prev, { id: data.id, name: data.name }]);
        setSelectedFolderId(data.id);
        setNewFolderName('');
        setIsCreatingFolder(false);
      }
    } catch (error) {
      console.error('Failed to create folder:', error);
    }
  };

  const handleMove = async () => {
    try {
      const response = await userService.moveAgentToFolder(
        { agent_id: agentId, folder_id: selectedFolderId },
        token,
      );
      if (response.ok) {
        onMoveSuccess(selectedFolderId);
        setModalState('INACTIVE');
      }
    } catch (error) {
      console.error('Failed to move agent:', error);
    }
  };

  const breadcrumbPath = useMemo(() => {
    const selectedFolder = folders.find((f) => f.id === selectedFolderId);
    if (selectedFolder) {
      return `By Me > ${selectedFolder.name}`;
    }
    return 'By Me';
  }, [folders, selectedFolderId]);

  if (modalState !== 'ACTIVE') return null;

  return (
    <WrapperModal close={() => setModalState('INACTIVE')}>
      <div className="w-[800px] max-w-[90vw]">
        <h2
          className="text-jet dark:text-bright-gray mb-2 font-semibold"
          style={{
            fontFamily: 'Inter, sans-serif',
            fontSize: '22px',
            lineHeight: '28px',
            letterSpacing: '0.15px',
          }}
        >
          {t('agents.folders.move')} "{agentName}" to
        </h2>

        <p className="mb-4 text-sm text-gray-500 dark:text-gray-400">
          {breadcrumbPath}
        </p>

        <div className="max-h-60 overflow-y-auto">
          {isLoading ? (
            <div className="flex h-20 items-center justify-center">
              <span className="text-sm text-gray-500">{t('loading')}...</span>
            </div>
          ) : (
            <div className="flex flex-col gap-1">
              {currentFolderId && (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setSelectedFolderId(null);
                  }}
                  className={`flex items-center gap-2 rounded-lg px-3 py-2 text-left text-sm ${
                    selectedFolderId === null
                      ? 'bg-[#7D54D1] text-white'
                      : 'hover:bg-gray-100 dark:hover:bg-[#383838]'
                  }`}
                >
                  <span
                    className={
                      selectedFolderId === null
                        ? 'text-white'
                        : 'text-gray-600 dark:text-gray-300'
                    }
                  >
                    {t('agents.folders.noFolder')}
                  </span>
                </button>
              )}
              {folders.map((folder) => (
                <button
                  key={folder.id}
                  onClick={(e) => {
                    e.stopPropagation();
                    setSelectedFolderId(folder.id);
                  }}
                  className={`flex items-center gap-2 rounded-lg px-3 py-2 text-left text-sm ${
                    selectedFolderId === folder.id
                      ? 'bg-[#7D54D1] text-white'
                      : 'hover:bg-gray-100 dark:hover:bg-[#383838]'
                  }`}
                >
                  <img
                    src={FolderIcon}
                    alt="folder"
                    className={`h-4 w-4 ${selectedFolderId === folder.id ? 'brightness-0 invert' : ''}`}
                  />
                  <span
                    className={`truncate ${
                      selectedFolderId === folder.id
                        ? 'text-white'
                        : 'text-[#18181B] dark:text-[#E0E0E0]'
                    }`}
                  >
                    {folder.name}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="mt-6 flex items-center justify-between border-t border-gray-200 pt-4 dark:border-[#3A3A3A]">
          <div>
            {isCreatingFolder ? (
              <div className="flex gap-2">
                <input
                  type="text"
                  value={newFolderName}
                  onChange={(e) => setNewFolderName(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleCreateFolder()}
                  onClick={(e) => e.stopPropagation()}
                  placeholder={t('agents.folders.folderName')}
                  autoFocus
                  className="rounded-lg border border-[#E5E5E5] bg-white px-3 py-2 text-sm outline-none dark:border-[#3A3A3A] dark:bg-[#2C2C2C] dark:text-white"
                />
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    handleCreateFolder();
                  }}
                  disabled={!newFolderName.trim()}
                  className="bg-purple-30 hover:bg-violets-are-blue rounded-lg px-3 py-2 text-sm text-white disabled:opacity-50"
                >
                  {t('agents.folders.createFolder')}
                </button>
              </div>
            ) : (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setIsCreatingFolder(true);
                }}
                className="text-purple-30 hover:text-violets-are-blue text-sm font-medium"
              >
                + {t('agents.folders.newFolder')}
              </button>
            )}
          </div>

          <div className="flex gap-2">
            <button
              onClick={(e) => {
                e.stopPropagation();
                setModalState('INACTIVE');
              }}
              className="dark:text-light-gray cursor-pointer rounded-3xl px-5 py-2 text-sm font-medium hover:bg-gray-100 dark:bg-transparent dark:hover:bg-[#767183]/50"
            >
              {t('cancel')}
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation();
                handleMove();
              }}
              disabled={selectedFolderId === currentFolderId}
              className="bg-purple-30 hover:bg-violets-are-blue rounded-3xl px-5 py-2 text-sm text-white disabled:opacity-50"
            >
              {t('agents.folders.move')}
            </button>
          </div>
        </div>
      </div>
    </WrapperModal>
  );
}

