import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';

import userService from '../api/services/userService';
import Search from '../assets/search.svg';
import Spinner from '../components/Spinner';
import {
  setConversation,
  updateConversationId,
} from '../conversation/conversationSlice';
import FolderNameModal from '../modals/FolderManagementModal';
import { ActiveState } from '../models/misc';
import {
  selectAgentFolders,
  selectSelectedAgent,
  selectToken,
  setAgentFolders,
  setSelectedAgent,
} from '../preferences/preferenceSlice';
import AgentCard from './AgentCard';
import { AgentSectionId, agentSectionsConfig } from './agents.config';
import FolderCard from './FolderCard';
import { AgentFilterTab, useAgentSearch } from './hooks/useAgentSearch';
import { useAgentsFetch } from './hooks/useAgentsFetch';
import { Agent, AgentFolder } from './types';

const FILTER_TABS: { id: AgentFilterTab; labelKey: string }[] = [
  { id: 'all', labelKey: 'agents.filters.all' },
  { id: 'template', labelKey: 'agents.filters.byDocsGPT' },
  { id: 'user', labelKey: 'agents.filters.byMe' },
  { id: 'shared', labelKey: 'agents.filters.shared' },
];

export default function AgentsList() {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const token = useSelector(selectToken);
  const selectedAgent = useSelector(selectSelectedAgent);
  const folders = useSelector(selectAgentFolders);
  const [folderModalState, setFolderModalState] = useState<ActiveState>('INACTIVE');

  const { isLoading, refetchFolders } = useAgentsFetch();

  const {
    searchQuery,
    setSearchQuery,
    activeFilter,
    setActiveFilter,
    filteredAgentsBySection,
    totalAgentsBySection,
    hasAnyAgents,
    hasFilteredResults,
    isDataLoaded,
  } = useAgentSearch();

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
    async (name: string) => {
      const response = await userService.createAgentFolder({ name }, token);
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
        await refetchFolders();
        return true;
      }
      return false;
    },
    [token, refetchFolders],
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

  const handleSubmitNewFolder = async (name: string) => {
    await handleCreateFolder(name);
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
    <div className="p-4 md:p-12">
      <h1 className="text-eerie-black mb-0 text-[32px] font-bold lg:text-[40px] dark:text-[#E0E0E0]">
        {t('agents.title')}
      </h1>
      <p className="dark:text-gray-4000 mt-5 max-w-lg text-[15px] leading-6 text-[#71717A]">
        {t('agents.description')}
      </p>

      <div className="mt-6 flex flex-col gap-4 pb-4">
        <div className="relative w-full max-w-md">
          <img
            src={Search}
            alt=""
            className="absolute top-1/2 left-4 h-5 w-5 -translate-y-1/2 opacity-40"
          />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={t('agents.searchPlaceholder')}
            className="h-[44px] w-full rounded-full border border-[#E5E5E5] bg-white py-2 pr-5 pl-11 text-sm shadow-[0_1px_4px_rgba(0,0,0,0.06)] transition-shadow outline-none placeholder:text-[#9CA3AF] focus:shadow-[0_2px_8px_rgba(0,0,0,0.1)] dark:border-[#3A3A3A] dark:bg-[#2C2C2C] dark:text-white dark:shadow-none dark:placeholder:text-[#6B7280]"
          />
        </div>

        <div className="flex flex-wrap gap-2">
          {FILTER_TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveFilter(tab.id)}
              className={`rounded-full px-4 py-2 text-sm transition-colors ${
                activeFilter === tab.id
                  ? 'bg-[#E0E0E0] text-[#18181B] dark:bg-[#4A4A4A] dark:text-white'
                  : 'bg-transparent text-[#71717A] hover:bg-[#F5F5F5] dark:text-[#949494] dark:hover:bg-[#383838]/50'
              }`}
            >
              {t(tab.labelKey)}
            </button>
          ))}
        </div>
      </div>

      {visibleSections.map((sectionConfig) => (
        <AgentSection
          key={sectionConfig.id}
          config={sectionConfig}
          filteredAgents={
            filteredAgentsBySection[sectionConfig.id as AgentSectionId]
          }
          totalAgents={totalAgentsBySection[sectionConfig.id as AgentSectionId]}
          searchQuery={searchQuery}
          isFilteredView={activeFilter !== 'all'}
          isLoading={isLoading[sectionConfig.id as AgentSectionId]}
          folders={sectionConfig.id === 'user' ? folders : null}
          folderModalState={sectionConfig.id === 'user' ? folderModalState : 'INACTIVE'}
          setFolderModalState={setFolderModalState}
          onCreateFolder={handleSubmitNewFolder}
          onDeleteFolder={handleDeleteFolder}
          onRenameFolder={handleRenameFolder}
        />
      ))}

      {showSearchEmptyState && (
        <div className="mt-12 flex flex-col items-center justify-center gap-2 text-[#71717A]">
          <p className="text-lg">{t('agents.noSearchResults')}</p>
          <p className="text-sm">{t('agents.tryDifferentSearch')}</p>
        </div>
      )}

      <FolderNameModal
        modalState={folderModalState}
        setModalState={setFolderModalState}
        mode="create"
        onSubmit={handleSubmitNewFolder}
      />
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
  folderModalState: ActiveState;
  setFolderModalState: (state: ActiveState) => void;
  onCreateFolder: (name: string) => void;
  onDeleteFolder: (id: string) => Promise<boolean>;
  onRenameFolder: (id: string, name: string) => void;
}

function AgentSection({
  config,
  filteredAgents,
  totalAgents,
  searchQuery,
  isFilteredView,
  isLoading,
  folders,
  setFolderModalState,
  onDeleteFolder,
  onRenameFolder,
}: AgentSectionProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const dispatch = useDispatch();
  const allAgents = useSelector(config.selectData);
  const [expandedFolderId, setExpandedFolderId] = useState<string | null>(null);

  const updateAgents = (updatedAgents: Agent[]) => {
    dispatch(config.updateAction(updatedAgents));
  };

  const unfolderedAgents = useMemo(() => {
    if (config.id !== 'user' || !folders) return filteredAgents;
    return filteredAgents.filter((a) => !a.folder_id);
  }, [filteredAgents, folders, config.id]);

  const getAgentsForFolder = (folderId: string) => {
    return filteredAgents.filter((a) => a.folder_id === folderId);
  };

  const handleToggleExpand = (folderId: string) => {
    setExpandedFolderId((prev) => (prev === folderId ? null : folderId));
  };

  const hasNoAgentsAtAll = !isLoading && totalAgents === 0;
  const isSearchingWithNoResults =
    !isLoading && searchQuery && filteredAgents.length === 0 && totalAgents > 0;

  if (isFilteredView && isSearchingWithNoResults) {
    return (
      <div className="mt-12 flex flex-col items-center justify-center gap-2 text-[#71717A]">
        <p className="text-lg">{t('agents.noSearchResults')}</p>
        <p className="text-sm">{t('agents.tryDifferentSearch')}</p>
      </div>
    );
  }

  if (isFilteredView && hasNoAgentsAtAll) {
    return (
      <div className="mt-12 flex flex-col items-center justify-center gap-3 text-[#71717A]">
        <p>{t(`agents.sections.${config.id}.emptyState`)}</p>
        {config.showNewAgentButton && (
          <button
            className="bg-purple-30 hover:bg-violets-are-blue rounded-full px-4 py-2 text-sm text-white"
            onClick={() => navigate('/agents/new')}
          >
            {t('agents.newAgent')}
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="mt-8 flex flex-col gap-4">
      <div className="flex w-full items-center justify-between">
        <div className="flex flex-col gap-2">
          <h2 className="text-[18px] font-semibold text-[#18181B] dark:text-[#E0E0E0]">
            {t(`agents.sections.${config.id}.title`)}
          </h2>
          <p className="text-[13px] text-[#71717A]">
            {t(`agents.sections.${config.id}.description`)}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {config.id === 'user' && (
            <button
              className="rounded-full border border-[#E5E5E5] bg-white px-4 py-2 text-sm text-[#18181B] hover:bg-[#F5F5F5] dark:border-[#3A3A3A] dark:bg-[#2C2C2C] dark:text-white dark:hover:bg-[#383838]"
              onClick={() => setFolderModalState('ACTIVE')}
            >
              {t('agents.folders.newFolder')}
            </button>
          )}
          {config.showNewAgentButton && (
            <button
              className="bg-purple-30 hover:bg-violets-are-blue rounded-full px-4 py-2 text-sm text-white"
              onClick={() => navigate('/agents/new')}
            >
              {t('agents.newAgent')}
            </button>
          )}
        </div>
      </div>

      <div className="flex flex-col gap-4">
        {isLoading ? (
          <div className="flex h-40 w-full items-center justify-center">
            <Spinner />
          </div>
        ) : (
          <>
            {config.id === 'user' && folders && folders.length > 0 && (
              <div className="flex flex-wrap gap-3">
                {folders.map((folder) => (
                  <FolderCard
                    key={folder.id}
                    folder={folder}
                    agentCount={getAgentsForFolder(folder.id).length}
                    onDelete={onDeleteFolder}
                    onRename={onRenameFolder}
                    isExpanded={expandedFolderId === folder.id}
                    onToggleExpand={handleToggleExpand}
                  />
                ))}
              </div>
            )}

            {config.id === 'user' &&
              expandedFolderId &&
              folders?.find((f) => f.id === expandedFolderId) && (
                <div className="flex flex-col gap-2">
                  <p className="text-sm text-[#71717A]">
                    {folders.find((f) => f.id === expandedFolderId)?.name}
                  </p>
                  {getAgentsForFolder(expandedFolderId).length > 0 ? (
                    <div className="grid grid-cols-1 gap-4 sm:flex sm:flex-wrap">
                      {getAgentsForFolder(expandedFolderId).map((agent) => (
                        <AgentCard
                          key={agent.id}
                          agent={agent}
                          agents={allAgents || []}
                          updateAgents={updateAgents}
                          section="user"
                        />
                      ))}
                    </div>
                  ) : (
                    <p className="text-sm text-[#71717A]">
                      {t('agents.folders.empty')}
                    </p>
                  )}
                </div>
              )}

            {unfolderedAgents.length > 0 ? (
              <div className="grid grid-cols-1 gap-4 sm:flex sm:flex-wrap">
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
            ) : hasNoAgentsAtAll && (!folders || folders.length === 0) ? (
              <div className="flex h-40 w-full flex-col items-center justify-center gap-3 text-[#71717A]">
                <p>{t(`agents.sections.${config.id}.emptyState`)}</p>
                {config.showNewAgentButton && (
                  <button
                    className="bg-purple-30 hover:bg-violets-are-blue ml-2 rounded-full px-4 py-2 text-sm text-white"
                    onClick={() => navigate('/agents/new')}
                  >
                    {t('agents.newAgent')}
                  </button>
                )}
              </div>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}
