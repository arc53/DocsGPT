import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import { AgentFolder } from '../agents/types';
import userService from '../api/services/userService';
import ChevronRight from '../assets/chevron-right.svg';
import FolderIcon from '../assets/folder.svg';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Modal } from '../components/ui/modal';
import { ActiveState } from '../models/misc';
import { selectToken, setAgentFolders } from '../preferences/preferenceSlice';

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
  const dispatch = useDispatch();
  const token = useSelector(selectToken);
  const [folders, setFolders] = useState<AgentFolder[]>([]);
  const [selectedFolderId, setSelectedFolderId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isCreatingFolder, setIsCreatingFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState('');
  const newFolderInputRef = useRef<HTMLInputElement>(null);
  // Track navigation path for nested folders
  const [folderPath, setFolderPath] = useState<string[]>([]);

  const currentNavigationFolderId =
    folderPath.length > 0 ? folderPath[folderPath.length - 1] : null;

  useEffect(() => {
    if (modalState === 'ACTIVE') {
      fetchFolders();
      setSelectedFolderId(currentFolderId || null);
      setFolderPath([]);
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

  // Get folders at the current navigation level
  const currentLevelFolders = useMemo(() => {
    return folders.filter(
      (f) => (f.parent_id || null) === currentNavigationFolderId,
    );
  }, [folders, currentNavigationFolderId]);

  // Build breadcrumb items
  const breadcrumbItems = useMemo(() => {
    return folderPath.map((folderId) => {
      const folder = folders.find((f) => f.id === folderId);
      return { id: folderId, name: folder?.name || '' };
    });
  }, [folders, folderPath]);

  const handleNavigateIntoFolder = (folderId: string) => {
    setFolderPath((prev) => [...prev, folderId]);
  };

  const handleNavigateToPath = (index: number) => {
    if (index < 0) {
      setFolderPath([]);
    } else {
      setFolderPath((prev) => prev.slice(0, index + 1));
    }
  };

  const handleCreateFolder = async (name: string) => {
    try {
      const response = await userService.createAgentFolder(
        { name, parent_id: currentNavigationFolderId || undefined },
        token,
      );
      if (response.ok) {
        const data = await response.json();
        const newFolder = {
          id: data.id,
          name: data.name,
          parent_id: currentNavigationFolderId,
        };
        setFolders((prev) => {
          const updatedFolders = [...prev, newFolder];
          dispatch(setAgentFolders(updatedFolders));
          return updatedFolders;
        });
        setSelectedFolderId(data.id);
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

  return (
    <Modal
      open={modalState === 'ACTIVE'}
      onOpenChange={(o) => !o && setModalState('INACTIVE')}
      size="md"
      className="w-[800px] max-w-[90vw] p-0! sm:max-w-[90vw]"
      contentClassName="overflow-visible"
      hideTitle
      title={`${t('agents.folders.move')} "${agentName}" to`}
    >
      <div>
        <div className="px-6 pt-4">
          <h2 className="text-foreground dark:text-foreground mb-2 text-2xl leading-7 font-semibold tracking-[0.15px]">
            {t('agents.folders.move')} &quot;{agentName}&quot; to
          </h2>
        </div>
        <div className="bg-muted dark:bg-muted text-muted-foreground flex items-center gap-1 px-8 py-2 text-xs font-semibold">
          <Button
            type="button"
            variant="ghost"
            onClick={() => handleNavigateToPath(-1)}
            className={`hover:text-foreground h-auto px-0 py-0 text-xs font-semibold hover:bg-transparent dark:hover:text-white ${folderPath.length > 0 ? 'opacity-70' : ''}`}
          >
            {t('agents.filters.byMe')}
          </Button>
          {breadcrumbItems.map((item, index) => (
            <span key={item.id} className="flex items-center gap-1">
              <svg
                className="mx-1"
                width="5"
                height="10"
                viewBox="0 0 5 10"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
              >
                <path
                  d="M0.134367 9.15687C0.0914459 9.20458 0.0578918 9.2607 0.0356192 9.32203C0.0133471 9.38335 0.00279279 9.44869 0.00455995 9.5143C0.00632664 9.57992 0.0203805 9.64452 0.045918 9.70443C0.0714555 9.76434 0.107977 9.81837 0.153397 9.86346C0.198817 9.90854 0.252247 9.94378 0.310635 9.96718C0.369022 9.99057 0.431225 10.0017 0.493692 9.9998C0.556159 9.99794 0.617665 9.98318 0.674701 9.95636C0.731736 9.92954 0.783183 9.89118 0.826104 9.84347L4.86996 5.34611C4.95347 5.25333 5 5.13049 5 5.00281C5 4.87513 4.95347 4.75229 4.86996 4.65951L0.826103 0.161649C0.783465 0.112896 0.73203 0.0735287 0.674785 0.045833C0.617539 0.0181364 0.555626 0.00266495 0.49264 0.000314153C0.429653 -0.00203665 0.36685 0.00878279 0.307878 0.0321411C0.248906 0.0555004 0.19494 0.0909342 0.149116 0.136384C0.103292 0.181836 0.0665217 0.236396 0.0409428 0.296899C0.0153638 0.357402 0.00148499 0.422641 0.000112656 0.488825C-0.00125968 0.55501 0.00990166 0.620821 0.0329486 0.682436C0.0559961 0.744051 0.0904695 0.800243 0.134366 0.847745L3.86994 5.00281L0.134367 9.15687Z"
                  fill="currentColor"
                />
              </svg>
              {index === breadcrumbItems.length - 1 ? (
                <span>{item.name}</span>
              ) : (
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => handleNavigateToPath(index)}
                  className="hover:text-foreground h-auto px-0 py-0 text-xs font-semibold opacity-70 hover:bg-transparent dark:hover:text-white"
                >
                  {item.name}
                </Button>
              )}
            </span>
          ))}
        </div>
        <div className="dark:border-border max-h-60 min-h-[200px] overflow-y-auto border-t border-gray-200">
          {isLoading ? (
            <div className="flex h-[200px] items-center justify-center">
              <span className="text-muted-foreground text-sm">
                {t('loading')}...
              </span>
            </div>
          ) : (
            <div className="flex w-full flex-col">
              {/* Option to move to root (no folder) - only show at root level */}
              {currentFolderId && folderPath.length === 0 && (
                <Button
                  type="button"
                  variant="ghost"
                  onClick={(e) => {
                    e.stopPropagation();
                    setSelectedFolderId(null);
                  }}
                  className={`dark:border-border h-auto w-full justify-start gap-2 rounded-none border-b border-gray-200 px-8 py-2 text-left text-sm ${
                    selectedFolderId === null
                      ? 'bg-primary hover:bg-primary text-white hover:text-white'
                      : 'bg-muted hover:bg-accent dark:bg-muted'
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
                </Button>
              )}

              {currentLevelFolders.map((folder) => (
                <Button
                  key={folder.id}
                  type="button"
                  variant="ghost"
                  onClick={() => setSelectedFolderId(folder.id)}
                  className={`dark:border-border h-auto w-full justify-between rounded-none border-b border-gray-200 px-8 py-2 text-left text-sm ${
                    selectedFolderId === folder.id
                      ? 'bg-primary hover:bg-primary text-white hover:text-white'
                      : 'bg-muted hover:bg-accent dark:bg-muted'
                  }`}
                >
                  <span className="flex flex-1 items-center gap-2">
                    <img
                      src={FolderIcon}
                      alt="folder"
                      className={`h-4 w-4 ${selectedFolderId === folder.id ? 'brightness-0 invert' : ''}`}
                    />
                    <span
                      className={`truncate ${selectedFolderId === folder.id ? 'text-white' : 'text-foreground'}`}
                    >
                      {folder.name}
                    </span>
                  </span>
                  {/* Check if folder has subfolders */}
                  {folders.some((f) => f.parent_id === folder.id) && (
                    <span
                      role="button"
                      tabIndex={0}
                      onClick={(e) => {
                        e.stopPropagation();
                        handleNavigateIntoFolder(folder.id);
                      }}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.stopPropagation();
                          handleNavigateIntoFolder(folder.id);
                        }
                      }}
                      className="hover:bg-accent ml-2 flex h-6 w-6 items-center justify-center rounded-full"
                    >
                      <img
                        src={ChevronRight}
                        alt="expand"
                        className={`h-3 w-3 ${selectedFolderId === folder.id ? 'brightness-0 invert' : ''}`}
                      />
                    </span>
                  )}
                </Button>
              ))}
              {currentLevelFolders.length === 0 && folderPath.length > 0 && (
                <div className="text-muted-foreground flex h-[200px] items-center justify-center text-sm">
                  {t('agents.folders.noSubfolders')}
                </div>
              )}
              {currentLevelFolders.length === 0 &&
                folderPath.length === 0 &&
                !currentFolderId && (
                  <div className="text-muted-foreground flex h-[200px] items-center justify-center text-sm">
                    {t('agents.folders.noFolders')}
                  </div>
                )}
            </div>
          )}
        </div>

        <div className="dark:border-border flex items-center justify-between border-t border-gray-200 px-8 py-4">
          {isCreatingFolder ? (
            <Input
              ref={newFolderInputRef}
              type="text"
              value={newFolderName}
              onChange={(e) => setNewFolderName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && newFolderName.trim()) {
                  handleCreateFolder(newFolderName.trim());
                  setNewFolderName('');
                  setIsCreatingFolder(false);
                } else if (e.key === 'Escape') {
                  setNewFolderName('');
                  setIsCreatingFolder(false);
                }
              }}
              onBlur={() => {
                if (!newFolderName.trim()) {
                  setIsCreatingFolder(false);
                }
              }}
              placeholder={t('agents.folders.newFolder')}
              className="border-primary text-primary placeholder:text-primary/60 dark:placeholder:text-primary/60 dark:text-primary dark:border-primary h-auto rounded-full px-6 py-2 text-sm font-medium"
              autoFocus
            />
          ) : (
            <Button
              type="button"
              variant="outline"
              onClick={(e) => {
                e.stopPropagation();
                setIsCreatingFolder(true);
                setTimeout(() => newFolderInputRef.current?.focus(), 0);
              }}
              className="border-primary text-primary hover:bg-primary/10 hover:text-primary h-auto rounded-full bg-transparent px-6 py-2 text-sm font-medium"
            >
              {t('agents.folders.newFolder')}
            </Button>
          )}

          <div className="flex gap-2">
            <Button
              type="button"
              variant="ghost"
              onClick={(e) => {
                e.stopPropagation();
                if (isCreatingFolder) {
                  setNewFolderName('');
                  setIsCreatingFolder(false);
                } else {
                  setModalState('INACTIVE');
                }
              }}
              className="dark:text-foreground h-auto rounded-3xl px-5 py-2 text-sm font-medium"
            >
              {t('cancel')}
            </Button>
            {isCreatingFolder ? (
              <Button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  if (newFolderName.trim()) {
                    handleCreateFolder(newFolderName.trim());
                    setNewFolderName('');
                    setIsCreatingFolder(false);
                  }
                }}
                disabled={!newFolderName.trim()}
                className="h-auto rounded-3xl px-5 py-2 text-sm text-white"
              >
                {t('agents.folders.createFolder')}
              </Button>
            ) : (
              <Button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  handleMove();
                }}
                className="h-auto rounded-3xl px-5 py-2 text-sm text-white"
              >
                {t('agents.folders.move')}
              </Button>
            )}
          </div>
        </div>
      </div>
    </Modal>
  );
}
