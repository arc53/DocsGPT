import { ChevronRight } from 'lucide-react';
import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import { AgentFolder } from '../agents/types';
import userService from '../api/services/userService';
import FolderIcon from '../assets/folder.svg';
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '../components/ui/breadcrumb';
import { Button } from '../components/ui/button';
import {
  Command,
  CommandGroup,
  CommandItem,
  CommandList,
} from '../components/ui/command';
import { Input } from '../components/ui/input';
import { Modal } from '../components/ui/modal';
import { ActiveState } from '../models/misc';
import { selectToken, setAgentFolders } from '../preferences/preferenceSlice';

// cmdk keys rows by `value`: the root row needs a value no folder id can take,
// and the highlight starts on a value no row has, so nothing is highlighted
// until the pointer or the arrow keys move it.
const ROOT_ROW_VALUE = '__docsgpt-no-folder__';
const NO_HIGHLIGHT = '__docsgpt-no-highlight__';

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
  // The row cmdk highlights (pointer / arrow keys), apart from the chosen one.
  const [highlightedRow, setHighlightedRow] = useState(NO_HIGHLIGHT);

  const currentNavigationFolderId =
    folderPath.length > 0 ? folderPath[folderPath.length - 1] : null;

  useEffect(() => {
    if (modalState === 'ACTIVE') {
      fetchFolders();
      setSelectedFolderId(currentFolderId || null);
      setFolderPath([]);
      setHighlightedRow(NO_HIGHLIGHT);
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

  const showRootRow = Boolean(currentFolderId) && folderPath.length === 0;
  const hasRows = showRootRow || currentLevelFolders.length > 0;

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
      className="w-[800px] max-w-[90vw] p-0 sm:max-w-[90vw]"
      contentClassName="overflow-visible"
      hideTitle
      title={`${t('agents.folders.move')} "${agentName}" to`}
    >
      <div>
        <div className="px-6 pt-4">
          <h2 className="text-foreground mb-2 text-2xl leading-7 font-semibold">
            {t('agents.folders.move')} &quot;{agentName}&quot; to
          </h2>
        </div>
        <div className="bg-muted px-8 py-2">
          <Breadcrumb className="min-w-0">
            <BreadcrumbList className="flex-nowrap">
              {folderPath.length === 0 ? (
                <BreadcrumbItem className="min-w-0">
                  <BreadcrumbPage
                    title={t('agents.filters.byMe')}
                    className="max-w-[32ch]"
                  >
                    {t('agents.filters.byMe')}
                  </BreadcrumbPage>
                </BreadcrumbItem>
              ) : (
                <BreadcrumbItem>
                  <BreadcrumbLink asChild>
                    <button
                      type="button"
                      onClick={() => handleNavigateToPath(-1)}
                    >
                      {t('agents.filters.byMe')}
                    </button>
                  </BreadcrumbLink>
                </BreadcrumbItem>
              )}
              {breadcrumbItems.map((item, index) => (
                <Fragment key={item.id}>
                  <BreadcrumbSeparator />
                  {index === breadcrumbItems.length - 1 ? (
                    <BreadcrumbItem className="min-w-0">
                      <BreadcrumbPage
                        title={item.name}
                        className="max-w-[32ch]"
                      >
                        {item.name}
                      </BreadcrumbPage>
                    </BreadcrumbItem>
                  ) : (
                    <BreadcrumbItem>
                      <BreadcrumbLink asChild>
                        <button
                          type="button"
                          onClick={() => handleNavigateToPath(index)}
                        >
                          {item.name}
                        </button>
                      </BreadcrumbLink>
                    </BreadcrumbItem>
                  )}
                </Fragment>
              ))}
            </BreadcrumbList>
          </Breadcrumb>
        </div>
        <div className="border-border border-t px-5 py-1">
          {isLoading ? (
            <div className="flex h-[200px] items-center justify-center">
              <span className="text-muted-foreground text-sm">
                {t('modals.searchConversations.loading')}
              </span>
            </div>
          ) : hasRows ? (
            <Command
              tabIndex={0}
              value={highlightedRow}
              onValueChange={setHighlightedRow}
            >
              <CommandList
                label={t('agents.folders.moveToFolder')}
                className="max-h-60 min-h-50"
              >
                <CommandGroup>
                  {/* Option to move to root (no folder) - only show at root level */}
                  {showRootRow && (
                    <CommandItem
                      value={ROOT_ROW_VALUE}
                      keywords={[t('agents.folders.noFolder')]}
                      checked={selectedFolderId === null}
                      aria-checked={selectedFolderId === null}
                      onSelect={() => setSelectedFolderId(null)}
                    >
                      <span
                        className={
                          selectedFolderId === null
                            ? undefined
                            : 'text-muted-foreground'
                        }
                      >
                        {t('agents.folders.noFolder')}
                      </span>
                    </CommandItem>
                  )}

                  {currentLevelFolders.map((folder) => (
                    <CommandItem
                      key={folder.id}
                      value={folder.id}
                      keywords={[folder.name]}
                      checked={selectedFolderId === folder.id}
                      aria-checked={selectedFolderId === folder.id}
                      onSelect={() => setSelectedFolderId(folder.id)}
                      className="justify-between"
                    >
                      <span className="flex flex-1 items-center gap-2">
                        <img
                          src={FolderIcon}
                          alt=""
                          aria-hidden="true"
                          className="h-4 w-4"
                        />
                        <span className="truncate">{folder.name}</span>
                      </span>
                      {/* Check if folder has subfolders */}
                      {folders.some((f) => f.parent_id === folder.id) && (
                        <Button
                          type="button"
                          variant="ghost-muted"
                          size="icon-xs"
                          aria-label={t('agents.folders.openFolder')}
                          onClick={(e) => {
                            // Keep cmdk's row click from choosing the folder.
                            e.stopPropagation();
                            handleNavigateIntoFolder(folder.id);
                          }}
                          onKeyDown={(e) => {
                            // cmdk's root handles Enter by choosing the
                            // highlighted row and cancelling this button's
                            // click; stop it here so Enter drills in instead.
                            if (e.key === 'Enter') e.stopPropagation();
                          }}
                        >
                          <ChevronRight className="text-current" />
                        </Button>
                      )}
                    </CommandItem>
                  ))}
                </CommandGroup>
              </CommandList>
            </Command>
          ) : (
            <>
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
            </>
          )}
        </div>

        <div className="border-border flex items-center justify-between border-t px-8 py-4">
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
              shape="pill"
              autoFocus
            />
          ) : (
            <Button
              type="button"
              variant="outline-primary"
              size="field"
              shape="pill"
              onClick={(e) => {
                e.stopPropagation();
                setIsCreatingFolder(true);
                setTimeout(() => newFolderInputRef.current?.focus(), 0);
              }}
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
              shape="pill"
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
                shape="pill"
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
                shape="pill"
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
