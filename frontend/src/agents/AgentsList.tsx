import { Search } from 'lucide-react';
import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate, useSearchParams } from 'react-router-dom';

import userService from '../api/services/userService';
import Spinner from '../components/Spinner';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import {
  setConversation,
  updateConversationId,
} from '../conversation/conversationSlice';
import ImportAgentModal from '../modals/ImportAgentModal';
import {
  selectAgentFolders,
  selectSelectedAgent,
  selectToken,
  setAgentFolders,
  setSelectedAgent,
} from '../preferences/preferenceSlice';
import AgentCard from './AgentCard';
import { AgentSectionId, agentSectionsConfig } from './agents.config';
import AgentTypeModal from './components/AgentTypeModal';
import FolderCard from './FolderCard';
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '../components/ui/breadcrumb';
import { CurrentSectionHeader } from '../navigation/SectionPageHeader';
import SectionPills from '../navigation/SectionPills';
import { useAgentSearch } from './hooks/useAgentSearch';
import { agentsListPath, filterFromPath } from './paths';
import { useAgentsFetch } from './hooks/useAgentsFetch';
import { Agent, AgentFolder } from './types';

export default function AgentsList() {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const token = useSelector(selectToken);
  const selectedAgent = useSelector(selectSelectedAgent);
  const folders = useSelector(selectAgentFolders);
  const [folderPath, setFolderPath] = useState<string[]>(() => {
    const folderIdFromUrl = searchParams.get('folder');
    return folderIdFromUrl ? [folderIdFromUrl] : [];
  });
  const [showAgentTypeModal, setShowAgentTypeModal] = useState(false);
  const [modalFolderId, setModalFolderId] = useState<string | null>(null);

  // Sync folder path with URL
  useEffect(() => {
    const currentFolderInUrl = searchParams.get('folder');
    const currentFolderId =
      folderPath.length > 0 ? folderPath[folderPath.length - 1] : null;

    if (currentFolderId !== currentFolderInUrl) {
      const newUrl = currentFolderId
        ? agentsListPath(currentFolderId)
        : agentsListPath();
      navigate(newUrl, { replace: true });
    }
  }, [folderPath, searchParams, navigate]);

  const { isLoading, refetchFolders, refetchUserAgents } = useAgentsFetch();

  // The list's filter is a route, so it is linkable and survives a reload;
  // the sidebar nav (and the pill row below `lg`) does the navigating.
  const activeFilter = filterFromPath(location.pathname);

  const {
    searchQuery,
    setSearchQuery,
    filteredAgentsBySection,
    totalAgentsBySection,
    hasAnyAgents,
    hasFilteredResults,
    isDataLoaded,
  } = useAgentSearch(activeFilter);

  useEffect(() => {
    dispatch(setConversation([]));
    dispatch(
      updateConversationId({
        query: { conversationId: null },
      }),
    );
    if (selectedAgent) dispatch(setSelectedAgent(null));
  }, []);

  const handleCreateFolder = useCallback(
    async (name: string, parentId?: string) => {
      const response = await userService.createAgentFolder(
        { name, parent_id: parentId },
        token,
      );
      if (response.ok) {
        await refetchFolders();
        return true;
      }
      return false;
    },
    [token, refetchFolders],
  );

  const handleDeleteFolder = useCallback(
    async (folderId: string) => {
      const response = await userService.deleteAgentFolder(folderId, token);
      if (response.ok) {
        await Promise.all([refetchFolders(), refetchUserAgents()]);
        return true;
      }
      return false;
    },
    [token, refetchFolders, refetchUserAgents],
  );

  const handleRenameFolder = useCallback(
    async (folderId: string, newName: string) => {
      const response = await userService.updateAgentFolder(
        folderId,
        { name: newName },
        token,
      );
      if (response.ok) {
        dispatch(
          setAgentFolders(
            (folders || []).map((f) =>
              f.id === folderId ? { ...f, name: newName } : f,
            ),
          ),
        );
      }
    },
    [token, folders, dispatch],
  );

  const handleSubmitNewFolder = async (name: string, parentId?: string) => {
    await handleCreateFolder(name, parentId);
  };

  const visibleSections = agentSectionsConfig.filter((config) => {
    if (activeFilter !== 'all') {
      return config.id === activeFilter;
    }
    const sectionId = config.id as AgentSectionId;
    const hasAgentsInSection = totalAgentsBySection[sectionId] > 0;
    const hasFilteredAgents = filteredAgentsBySection[sectionId].length > 0;
    const sectionDataLoaded = isDataLoaded[sectionId];

    if (!sectionDataLoaded) return true;
    if (searchQuery) return hasFilteredAgents;
    if (config.id === 'user') return true;
    return hasAgentsInSection;
  });

  const showSearchEmptyState =
    searchQuery &&
    hasAnyAgents &&
    !hasFilteredResults &&
    activeFilter === 'all';

  return (
    <div className="h-full overflow-auto p-4 md:p-12">
      <div className="mx-auto w-full max-w-6xl">
        <CurrentSectionHeader />
        <p className="text-muted-foreground mt-5 text-sm leading-6">
          {t('agents.description')}
        </p>

        <SectionPills className="mt-6" />

        <div className="mt-6 flex flex-col gap-4 pb-4">
          <div className="w-full max-w-md">
            <Input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              label={t('agents.searchPlaceholder')}
              labelBgClassName="bg-background"
              className="rounded-full"
              leftIcon={
                <Search
                  className="text-muted-foreground size-4"
                  strokeWidth={1.75}
                />
              }
            />
          </div>
        </div>

        {visibleSections.map((sectionConfig) => (
          <AgentSection
            key={sectionConfig.id}
            config={sectionConfig}
            filteredAgents={
              filteredAgentsBySection[sectionConfig.id as AgentSectionId]
            }
            totalAgents={
              totalAgentsBySection[sectionConfig.id as AgentSectionId]
            }
            searchQuery={searchQuery}
            isFilteredView={activeFilter !== 'all'}
            isLoading={isLoading[sectionConfig.id as AgentSectionId]}
            folders={sectionConfig.id === 'user' ? folders : null}
            folderPath={sectionConfig.id === 'user' ? folderPath : []}
            onFolderPathChange={
              sectionConfig.id === 'user' ? setFolderPath : undefined
            }
            onCreateFolder={handleSubmitNewFolder}
            onDeleteFolder={handleDeleteFolder}
            onRenameFolder={handleRenameFolder}
            setModalFolderId={setModalFolderId}
            setShowAgentTypeModal={setShowAgentTypeModal}
          />
        ))}

        {showSearchEmptyState && (
          <div className="text-muted-foreground mt-12 flex flex-col items-center justify-center gap-2">
            <p className="text-lg">{t('agents.noSearchResults')}</p>
            <p className="text-sm">{t('agents.tryDifferentSearch')}</p>
          </div>
        )}

        <AgentTypeModal
          isOpen={showAgentTypeModal}
          onClose={() => setShowAgentTypeModal(false)}
          folderId={modalFolderId}
        />
      </div>
    </div>
  );
}

interface AgentSectionProps {
  config: (typeof agentSectionsConfig)[number];
  filteredAgents: Agent[];
  totalAgents: number;
  searchQuery: string;
  isFilteredView: boolean;
  isLoading: boolean;
  folders: AgentFolder[] | null;
  folderPath: string[];
  onFolderPathChange?: (path: string[]) => void;
  onCreateFolder: (name: string, parentId?: string) => void;
  onDeleteFolder: (id: string) => Promise<boolean>;
  onRenameFolder: (id: string, name: string) => void;
  setModalFolderId: (folderId: string | null) => void;
  setShowAgentTypeModal: (show: boolean) => void;
}

function AgentSection({
  config,
  filteredAgents,
  totalAgents,
  searchQuery,
  isFilteredView,
  isLoading,
  folders,
  folderPath,
  onFolderPathChange,
  onCreateFolder,
  onDeleteFolder,
  onRenameFolder,
  setModalFolderId,
  setShowAgentTypeModal,
}: AgentSectionProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const dispatch = useDispatch();
  const allAgents = useSelector(config.selectData);
  const [isCreatingFolder, setIsCreatingFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState('');
  const [showImportModal, setShowImportModal] = useState(false);
  const newFolderInputRef = useRef<HTMLInputElement>(null);

  const currentFolderId =
    folderPath.length > 0 ? folderPath[folderPath.length - 1] : null;

  const setFolderPath = useCallback(
    (updater: string[] | ((prev: string[]) => string[])) => {
      if (!onFolderPathChange) return;
      if (typeof updater === 'function') {
        onFolderPathChange(updater(folderPath));
      } else {
        onFolderPathChange(updater);
      }
    },
    [onFolderPathChange, folderPath],
  );

  const updateAgents = (updatedAgents: Agent[]) => {
    dispatch(config.updateAction(updatedAgents));
  };

  const currentFolderDescendantIds = useMemo(() => {
    if (config.id !== 'user' || !folders || currentFolderId === null)
      return null;

    const getDescendants = (folderId: string): string[] => {
      const children = folders.filter((f) => f.parent_id === folderId);
      return children.flatMap((child) => [
        child.id,
        ...getDescendants(child.id),
      ]);
    };

    return new Set([currentFolderId, ...getDescendants(currentFolderId)]);
  }, [folders, currentFolderId, config.id]);

  const folderHasMatchingAgents = useCallback(
    (folderId: string): boolean => {
      const directMatches = filteredAgents.some(
        (a) => a.folder_id === folderId,
      );
      if (directMatches) return true;
      const childFolders = (folders || []).filter(
        (f) => f.parent_id === folderId,
      );
      return childFolders.some((f) => folderHasMatchingAgents(f.id));
    },
    [filteredAgents, folders],
  );

  // Get folders at the current level (root or inside current folder)
  const currentLevelFolders = useMemo(() => {
    if (config.id !== 'user' || !folders) return [];
    const foldersAtLevel = folders.filter(
      (f) => (f.parent_id || null) === currentFolderId,
    );
    if (searchQuery) {
      return foldersAtLevel.filter((f) => folderHasMatchingAgents(f.id));
    }
    return foldersAtLevel;
  }, [
    folders,
    currentFolderId,
    config.id,
    searchQuery,
    folderHasMatchingAgents,
  ]);

  const unfolderedAgents = useMemo(() => {
    if (config.id !== 'user' || !folders) return filteredAgents;

    if (searchQuery) {
      // When searching at root: return ALL filtered agents
      if (currentFolderId === null) {
        return filteredAgents;
      }
      // When searching inside a folder: return agents in current folder OR any descendant
      return filteredAgents.filter(
        (a) => currentFolderDescendantIds?.has(a.folder_id ?? '') ?? false,
      );
    }

    // No search: show agents that belong to the current folder level only
    return filteredAgents.filter(
      (a) => (a.folder_id || null) === currentFolderId,
    );
  }, [
    filteredAgents,
    folders,
    config.id,
    currentFolderId,
    searchQuery,
    currentFolderDescendantIds,
  ]);

  const getAgentsForFolder = (folderId: string) => {
    return filteredAgents.filter((a) => a.folder_id === folderId);
  };

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

  const handleSubmitNewFolder = (name: string) => {
    onCreateFolder(name, currentFolderId || undefined);
  };

  // Must stay above the empty-state returns below: a hook after an early
  // return is skipped on the render that takes it, which React rejects with
  // "rendered fewer hooks than expected". Reachable now that each filter is
  // its own route — landing straight on an empty one renders once while the
  // data loads, then again once it arrives empty.
  const breadcrumbItems = useMemo(() => {
    if (!folders || folderPath.length === 0) return [];
    return folderPath.map((folderId) => {
      const folder = folders.find((f) => f.id === folderId);
      return { id: folderId, name: folder?.name || '' };
    });
  }, [folders, folderPath]);

  const hasNoAgentsAtAll = !isLoading && totalAgents === 0;
  const isSearchingWithNoResults =
    !isLoading && searchQuery && filteredAgents.length === 0 && totalAgents > 0;

  if (isFilteredView && isSearchingWithNoResults) {
    return (
      <div className="text-muted-foreground mt-12 flex flex-col items-center justify-center gap-2">
        <p className="text-lg">{t('agents.noSearchResults')}</p>
        <p className="text-sm">{t('agents.tryDifferentSearch')}</p>
      </div>
    );
  }

  if (isFilteredView && hasNoAgentsAtAll) {
    return (
      <div className="text-muted-foreground mt-12 flex flex-col items-center justify-center gap-3">
        <p>{t(`agents.sections.${config.id}.emptyState`)}</p>
        {config.showNewAgentButton && (
          <Button
            type="button"
            className="rounded-full text-white"
            onClick={() => {
              setModalFolderId(null);
              setShowAgentTypeModal(true);
            }}
          >
            {t('agents.newAgent')}
          </Button>
        )}
      </div>
    );
  }

  return (
    <div className="mt-8 flex flex-col gap-4">
      <div className="flex w-full flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-col gap-2">
          {config.id === 'user' && breadcrumbItems.length > 0 ? (
            // Drilling into a folder is a trail, not a back button — the
            // sidebar's back is the only thing that means "leave".
            <Breadcrumb>
              <BreadcrumbList className="text-foreground gap-2 text-lg font-semibold sm:gap-2">
                <BreadcrumbItem>
                  <BreadcrumbLink asChild>
                    <button
                      type="button"
                      onClick={() => handleNavigateToPath(-1)}
                    >
                      {t(`agents.sections.${config.id}.title`)}
                    </button>
                  </BreadcrumbLink>
                </BreadcrumbItem>
                {breadcrumbItems.map((item, index) => (
                  <Fragment key={item.id}>
                    <BreadcrumbSeparator />
                    <BreadcrumbItem>
                      {index === breadcrumbItems.length - 1 ? (
                        <BreadcrumbPage>{item.name}</BreadcrumbPage>
                      ) : (
                        <BreadcrumbLink asChild>
                          <button
                            type="button"
                            onClick={() => handleNavigateToPath(index)}
                          >
                            {item.name}
                          </button>
                        </BreadcrumbLink>
                      )}
                    </BreadcrumbItem>
                  </Fragment>
                ))}
              </BreadcrumbList>
            </Breadcrumb>
          ) : (
            <h2 className="text-foreground text-lg font-semibold">
              {t(`agents.sections.${config.id}.title`)}
            </h2>
          )}
          <p className="text-muted-foreground text-sm">
            {t(`agents.sections.${config.id}.description`)}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {config.id === 'user' &&
            (isCreatingFolder ? (
              <Input
                ref={newFolderInputRef}
                type="text"
                value={newFolderName}
                onChange={(e) => setNewFolderName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && newFolderName.trim()) {
                    handleSubmitNewFolder(newFolderName.trim());
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
                className="w-28 sm:w-auto"
                autoFocus
              />
            ) : (
              <Button
                type="button"
                variant="outline"
                className="bg-card shrink-0 rounded-full whitespace-nowrap"
                onClick={() => {
                  setIsCreatingFolder(true);
                  setTimeout(() => newFolderInputRef.current?.focus(), 0);
                }}
              >
                {t('agents.folders.newFolder')}
              </Button>
            ))}
          {config.id === 'user' && (
            <Button
              type="button"
              variant="outline"
              className="bg-card shrink-0 rounded-full whitespace-nowrap"
              onClick={() => setShowImportModal(true)}
            >
              {t('agents.importAgent')}
            </Button>
          )}
          {config.showNewAgentButton && (
            <Button
              type="button"
              className="shrink-0 rounded-full whitespace-nowrap text-white"
              onClick={() => {
                setModalFolderId(currentFolderId);
                setShowAgentTypeModal(true);
              }}
            >
              {t('agents.newAgent')}
            </Button>
          )}
        </div>
      </div>
      <ImportAgentModal
        modalState={showImportModal ? 'ACTIVE' : 'INACTIVE'}
        setModalState={(state) => setShowImportModal(state === 'ACTIVE')}
      />

      <div className="flex flex-col gap-4">
        {isLoading ? (
          <div className="flex h-40 w-full items-center justify-center">
            <Spinner />
          </div>
        ) : (
          <>
            {/* Show subfolders at current level */}
            {config.id === 'user' && currentLevelFolders.length > 0 && (
              <div className="grid grid-cols-2 gap-3 sm:flex sm:flex-wrap">
                {currentLevelFolders.map((folder) => (
                  <FolderCard
                    key={folder.id}
                    folder={folder}
                    agentCount={getAgentsForFolder(folder.id).length}
                    onDelete={onDeleteFolder}
                    onRename={onRenameFolder}
                    isExpanded={false}
                    onToggleExpand={handleNavigateIntoFolder}
                  />
                ))}
              </div>
            )}

            {/* Show agents at current level */}
            {unfolderedAgents.length > 0 ? (
              <div className="grid grid-cols-2 gap-3 sm:flex sm:flex-wrap">
                {unfolderedAgents.map((agent) => (
                  <AgentCard
                    key={agent.id}
                    agent={agent}
                    agents={allAgents || []}
                    updateAgents={updateAgents}
                    section={config.id}
                  />
                ))}
              </div>
            ) : hasNoAgentsAtAll && currentLevelFolders.length === 0 ? (
              <div className="text-muted-foreground flex h-40 w-full flex-col items-center justify-center gap-3">
                <p>
                  {currentFolderId
                    ? t('agents.folders.empty')
                    : t(`agents.sections.${config.id}.emptyState`)}
                </p>
                {config.showNewAgentButton && !currentFolderId && (
                  <Button
                    type="button"
                    className="ml-2 rounded-full text-white"
                    onClick={() => {
                      setModalFolderId(currentFolderId);
                      setShowAgentTypeModal(true);
                    }}
                  >
                    {t('agents.newAgent')}
                  </Button>
                )}
              </div>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}
