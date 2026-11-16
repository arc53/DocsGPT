import { useEffect, useMemo, useState } from 'react';
import { ArrowRight, FolderOpen } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useLocation, useNavigate } from 'react-router-dom';

import SkeletonLoader from '../components/SkeletonLoader';
import { Button } from '../components/ui/button';
import { EmptyState } from '../components/ui/empty-state';
import { folderCountLine } from '../components/folders/folderCopy';
import FolderCrumbRow from '../components/folders/FolderCrumbRow';
import FolderNameModal from '../components/folders/FolderNameModal';
import { selectFolderList } from '../components/folders/foldersSlice';
import FolderTile from '../components/folders/FolderTile';
import {
  canCreateIn,
  childFolders,
  folderPath,
  folderShowsOn,
  formatFolderPath,
  matchingFolders,
  searchParentName,
  subtreeIds,
  type FolderTree,
} from '../components/folders/folderTree';
import NewFolderButton from '../components/folders/NewFolderButton';
import type { Folder } from '../components/folders/types';
import {
  type FolderMenu,
  useFolderMenu,
} from '../components/folders/useFolderMenu';
import { useFolderParam } from '../components/folders/useFolderParam';
// Safe on a store without the workspace slice (read as Personal): Personal,
// or Editor and up in a team, may create; whether the workspace is a team.
import {
  selectCanEditFolders as selectCanCreate,
  selectFoldersInTeam as selectInTeam,
} from '../components/folders/folderWorkspace';
import {
  setConversation,
  updateConversationId,
} from '../conversation/conversationSlice';
import ImportAgentModal from '../modals/ImportAgentModal';
import {
  selectAgents,
  selectSelectedAgent,
  setAgents,
  setSelectedAgent,
} from '../preferences/preferenceSlice';
import WorkspaceLine from '../workspace/WorkspaceLine';
import AgentCard from './AgentCard';
import {
  AgentSectionId,
  agentSectionsConfig,
  PERSONAL_ONLY_SECTIONS,
} from './agents.config';
import AgentTypeModal from './components/AgentTypeModal';
import SectionShell from '../navigation/SectionShell';
import PageToolbar from '../components/PageToolbar';
import SearchInput from '../components/SearchInput';
import SectionPills from '../navigation/SectionPills';
import {
  type AgentFilterTab,
  filterAgentsByQuery,
  useAgentSearch,
} from './hooks/useAgentSearch';
import { agentsFilterPath, filterFromPath } from './paths';
import { Pagination, pageRangeParams } from '../components/ui/pagination';
import { useGridColumns } from '../hooks/useGridColumns';
import { SHORT_LIST_PAGE_SIZE, useClientPage } from '../hooks/usePageState';
import { formatCount } from '../utils/dateTimeUtils';
import { useAgentsFetch } from './hooks/useAgentsFetch';
import { Agent } from './types';

const TILE_GRID =
  'grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4';

/**
 * The filter a route asks for, as this workspace reads it: the old Team
 * address is Shared with you in Personal and the team's agents in a team, and
 * a team, where nothing is shared in, shows everything for Shared with you
 * and Discovered.
 */
export function workspaceFilter(
  filter: AgentFilterTab,
  inTeam: boolean,
): Exclude<AgentFilterTab, 'team'> {
  if (filter === 'team') return inTeam ? 'user' : 'sharedWithYou';
  if (inTeam && PERSONAL_ONLY_SECTIONS.includes(filter as AgentSectionId))
    return 'all';
  return filter;
}

/**
 * The locale block of a section's copy: in a team the workspace's agents are
 * the team's, so `user` reads from `team` ("Agents").
 */
const sectionCopy = (id: AgentSectionId, inTeam: boolean): string =>
  id === 'user' && inTeam ? 'team' : id;

/** The folders an agents list shows: those holding agents, or nothing yet. */
const agentFolders = (tree: FolderTree, folders: Folder[]): Folder[] =>
  folders.filter((folder) => folderShowsOn(tree, folder, 'agent'));

/** "Customer-facing › EU" for an agent filed in a folder the list knows. */
const folderLabelOf = (tree: FolderTree, agent: Agent): string | undefined =>
  agent.folder_id && tree.byId.has(agent.folder_id)
    ? formatFolderPath(folderPath(tree, agent.folder_id))
    : undefined;

export default function AgentsList() {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const location = useLocation();
  const selectedAgent = useSelector(selectSelectedAgent);
  const folderList = useSelector(selectFolderList('agent'));
  const inTeam = useSelector(selectInTeam);
  const { folderId, folder, trail, tree, openFolder } = useFolderParam('agent');
  const [showAgentTypeModal, setShowAgentTypeModal] = useState(false);
  const [modalFolderId, setModalFolderId] = useState<string | null>(null);
  const [newFolderParent, setNewFolderParent] = useState<
    string | null | undefined
  >(undefined);
  const [showImportModal, setShowImportModal] = useState(false);

  // The list's filter is a route, so it is linkable and survives a reload;
  // the sidebar nav (and the pill row below `lg`) does the navigating.
  const activeFilter = workspaceFilter(
    filterFromPath(location.pathname),
    inTeam,
  );

  const { isLoading, refetchFolders, refetchUserAgents } = useAgentsFetch();
  const folderMenu = useFolderMenu(
    'agent',
    () => {
      // The folder's agents moved to its parent: their filings changed.
      refetchUserAgents();
    },
    // Its agents went with it to the other workspace.
    { onMovedToWorkspace: () => void refetchUserAgents() },
  );

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

  // Opening a folder (or leaving one) starts a fresh search there.
  useEffect(() => {
    setSearchQuery('');
  }, [folderId, setSearchQuery]);

  const openNewAgent = (targetFolderId: string | null) => {
    setModalFolderId(targetFolderId);
    setShowAgentTypeModal(true);
  };

  const inFolder = folderId !== null;

  const matchedFolders = (query: string) =>
    agentFolders(tree, matchingFolders(tree, query));

  const visibleSections = agentSectionsConfig.filter((config) => {
    // Nothing is shared into a team: no Shared with you, no Discovered.
    if (inTeam && PERSONAL_ONLY_SECTIONS.includes(config.id)) return false;
    if (activeFilter !== 'all') {
      return config.id === activeFilter;
    }
    const sectionId = config.id as AgentSectionId;
    const hasAgentsInSection = totalAgentsBySection[sectionId] > 0;
    const hasFilteredAgents = filteredAgentsBySection[sectionId].length > 0;
    const sectionDataLoaded = isDataLoaded[sectionId];

    if (!sectionDataLoaded) return true;
    if (searchQuery) {
      // A folder whose name matches keeps My agents on screen.
      if (config.id === 'user')
        return hasFilteredAgents || matchedFolders(searchQuery).length > 0;
      return hasFilteredAgents;
    }
    if (config.id === 'user') return true;
    return hasAgentsInSection;
  });

  const showSearchEmptyState =
    searchQuery &&
    hasAnyAgents &&
    !hasFilteredResults &&
    matchedFolders(searchQuery).length === 0 &&
    activeFilter === 'all';

  const sectionActions = {
    onNewFolder: (parentId: string | null) => setNewFolderParent(parentId),
    onImport: () => setShowImportModal(true),
    onNewAgent: openNewAgent,
    onAgentsMoved: () => void refetchUserAgents(),
  };

  return (
    <SectionShell>
      <p className="text-muted-foreground text-sm leading-6">
        {t('agents.description')}
      </p>
      <WorkspaceLine kind="agents" />

      <SectionPills className="mt-6" />

      <div className="mt-6">
        <PageToolbar
          search={
            <SearchInput
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              label={
                folder
                  ? t('folders.searchIn', {
                      name: folder.name,
                      interpolation: { escapeValue: false },
                    })
                  : t('agents.searchPlaceholder')
              }
            />
          }
        />
      </div>

      {inFolder ? (
        <AgentFolderView
          folderId={folderId}
          folder={folder}
          trail={trail}
          tree={tree}
          foldersLoaded={folderList.loaded}
          foldersFailed={folderList.failed}
          agentsLoading={isLoading.user}
          searchQuery={searchQuery}
          openFolder={openFolder}
          folderMenu={folderMenu}
          onRetryFolders={refetchFolders}
          {...sectionActions}
        />
      ) : (
        visibleSections.map((sectionConfig) => (
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
            inTeam={inTeam}
            isFilteredView={activeFilter !== 'all'}
            isLoading={isLoading[sectionConfig.id as AgentSectionId]}
            tree={tree}
            foldersFailed={folderList.failed && !folderList.loaded}
            onRetryFolders={refetchFolders}
            openFolder={openFolder}
            folderMenu={folderMenu}
            {...sectionActions}
          />
        ))
      )}

      {!inFolder && showSearchEmptyState && <NoSearchResults />}

      {folderMenu.dialogs}
      <FolderNameModal
        open={newFolderParent !== undefined}
        onOpenChange={(open) => !open && setNewFolderParent(undefined)}
        kind="agent"
        mode="create"
        parentId={newFolderParent ?? null}
      />
      <ImportAgentModal
        modalState={showImportModal ? 'ACTIVE' : 'INACTIVE'}
        setModalState={(state) => setShowImportModal(state === 'ACTIVE')}
      />
      <AgentTypeModal
        isOpen={showAgentTypeModal}
        onClose={() => setShowAgentTypeModal(false)}
        folderId={modalFolderId}
      />
    </SectionShell>
  );
}

/** No agent matches the search: one block for the page and a filtered view. */
function NoSearchResults() {
  const { t } = useTranslation();
  return (
    <EmptyState
      size="sm"
      illustration="none"
      title={t('agents.noSearchResults')}
      description={t('agents.tryDifferentSearch')}
    />
  );
}

/** The folder list failed to load: in place of the folder tiles. */
function FoldersLoadError({ onRetry }: { onRetry: () => void }) {
  const { t } = useTranslation();
  return (
    <EmptyState
      size="sm"
      illustration="none"
      tone="destructive"
      title={t('folders.errors.loadFailed')}
      onRetry={onRetry}
    />
  );
}

type SectionActions = {
  onNewFolder: (parentId: string | null) => void;
  onImport: () => void;
  onNewAgent: (folderId: string | null) => void;
  /** An agent moved to another workspace: reload the list it left. */
  onAgentsMoved: () => void;
};

/**
 * The My agents buttons: New folder · Import · New agent. Below Editor in a
 * team none is drawn (New folder hides itself).
 */
function UserSectionButtons({
  folderId,
  atDepthLimit = false,
  onNewFolder,
  onImport,
  onNewAgent,
}: Omit<SectionActions, 'onAgentsMoved'> & {
  folderId: string | null;
  atDepthLimit?: boolean;
}) {
  const { t } = useTranslation();
  const canCreate = useSelector(selectCanCreate);
  if (!canCreate) return null;
  return (
    <>
      <NewFolderButton
        atDepthLimit={atDepthLimit}
        onClick={() => onNewFolder(folderId)}
      />
      <Button
        type="button"
        variant="outline"
        size="field"
        shape="pill"
        onClick={onImport}
      >
        {t('agents.importAgent')}
      </Button>
      <Button
        type="button"
        size="field"
        shape="pill"
        onClick={() => onNewAgent(folderId)}
      >
        {t('agents.newAgent')}
      </Button>
    </>
  );
}

/**
 * A grid of folder tiles that open the folder, each with its ⋯. A search
 * lists folders from several levels: `parentNameOf` names where a nested one
 * sits ("In Carriers").
 */
function FolderGrid({
  folders,
  openFolder,
  folderMenu,
  parentNameOf,
}: {
  folders: Folder[];
  openFolder: (id: string) => void;
  folderMenu: FolderMenu;
  parentNameOf?: (folder: Folder) => string | undefined;
}) {
  if (folders.length === 0) return null;
  return (
    <div className={TILE_GRID}>
      {folders.map((folder) => (
        <FolderTile
          key={folder.id}
          folder={folder}
          kind="agent"
          onOpen={(f) => openFolder(f.id)}
          menuOptions={folderMenu.menuOptions(folder)}
          parentName={parentNameOf?.(folder)}
        />
      ))}
    </div>
  );
}

type AgentFolderViewProps = SectionActions & {
  folderId: string;
  folder: Folder | null;
  trail: Folder[];
  tree: FolderTree;
  foldersLoaded: boolean;
  foldersFailed: boolean;
  agentsLoading: boolean;
  searchQuery: string;
  openFolder: (id: string | null) => void;
  folderMenu: FolderMenu;
  onRetryFolders: () => void;
};

/**
 * An open agent folder: the crumb row (My agents › … › folder, the buttons,
 * the folder's ⋯ last) and its count line, then its folders and its agents,
 * own and shared with the caller alike (filing is the caller's). Nothing else
 * from the page renders. A search covers the folder and its subfolders, flat,
 * folders first.
 */
function AgentFolderView({
  folderId,
  folder,
  trail,
  tree,
  foldersLoaded,
  foldersFailed,
  agentsLoading,
  searchQuery,
  openFolder,
  folderMenu,
  onRetryFolders,
  onNewFolder,
  onImport,
  onNewAgent,
  onAgentsMoved,
}: AgentFolderViewProps) {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const allAgents = useSelector(selectAgents);
  const canCreate = useSelector(selectCanCreate);

  const query = searchQuery.trim();
  const subtree = useMemo(() => subtreeIds(tree, folderId), [tree, folderId]);
  const folders = agentFolders(
    tree,
    query
      ? matchingFolders(tree, query, subtree).filter((f) => f.id !== folderId)
      : childFolders(tree, folderId),
  );
  const agents = useMemo(() => {
    const list = allAgents ?? [];
    if (query)
      return filterAgentsByQuery(list, query).filter(
        (agent) => agent.folder_id && subtree.has(agent.folder_id),
      );
    return list.filter((agent) => agent.folder_id === folderId);
  }, [allAgents, query, subtree, folderId]);

  const {
    page,
    setPage,
    pageItems: pagedAgents,
  } = useClientPage(agents, SHORT_LIST_PAGE_SIZE, `${query}|${folderId}`);

  if (!foldersLoaded) {
    return (
      <div className="mt-8 flex flex-col gap-4">
        {foldersFailed ? (
          <FoldersLoadError onRetry={onRetryFolders} />
        ) : (
          <div className={TILE_GRID}>
            <SkeletonLoader component="agentCards" count={4} />
          </div>
        )}
      </div>
    );
  }
  // An unknown folder: useFolderParam sends the page back to the root.
  if (!folder) return null;

  const empty = !query && folders.length === 0 && agents.length === 0;

  return (
    <div className="mt-8 flex flex-col gap-4">
      <FolderCrumbRow
        kind="agent"
        trail={trail}
        onNavigate={openFolder}
        meta={folderCountLine(t, folder, 'agent')}
        actions={
          <UserSectionButtons
            folderId={folderId}
            atDepthLimit={!canCreateIn(tree, folderId)}
            onNewFolder={onNewFolder}
            onImport={onImport}
            onNewAgent={onNewAgent}
          />
        }
        menu={folderMenu.crumbMenu(folder)}
      />
      {agentsLoading ? (
        <div className={TILE_GRID}>
          <SkeletonLoader component="agentCards" count={4} />
        </div>
      ) : empty ? (
        <EmptyState
          size="sm"
          icon={FolderOpen}
          title={t('folders.emptyTitle')}
          description={canCreate ? t('agents.folders.emptyHint') : undefined}
          action={
            canCreate ? (
              <Button
                type="button"
                shape="pill"
                onClick={() => onNewAgent(folderId)}
              >
                {t('agents.newAgent')}
              </Button>
            ) : undefined
          }
        />
      ) : query && folders.length === 0 && agents.length === 0 ? (
        <NoSearchResults />
      ) : (
        <>
          <FolderGrid
            folders={folders}
            openFolder={openFolder}
            folderMenu={folderMenu}
            parentNameOf={
              query
                ? (found) => searchParentName(tree, found, folderId)
                : undefined
            }
          />
          {agents.length > 0 ? (
            <>
              <div className={TILE_GRID}>
                {pagedAgents.map((agent) => (
                  <AgentCard
                    key={agent.id}
                    agent={agent}
                    agents={allAgents || []}
                    updateAgents={(updated) => dispatch(setAgents(updated))}
                    section={
                      agent.origin === 'shared' ? 'sharedWithYou' : 'user'
                    }
                    folderLabel={query ? folderLabelOf(tree, agent) : undefined}
                    onMovedToWorkspace={onAgentsMoved}
                  />
                ))}
              </div>
              <Pagination
                page={page}
                pageSize={SHORT_LIST_PAGE_SIZE}
                total={agents.length}
                onPageChange={setPage}
                rangeLabel={(range) =>
                  t('agents.pageRange', pageRangeParams(range))
                }
              />
            </>
          ) : null}
        </>
      )}
    </div>
  );
}

type AgentSectionProps = SectionActions & {
  config: (typeof agentSectionsConfig)[number];
  filteredAgents: Agent[];
  totalAgents: number;
  searchQuery: string;
  inTeam: boolean;
  isFilteredView: boolean;
  isLoading: boolean;
  tree: FolderTree;
  foldersFailed: boolean;
  onRetryFolders: () => void;
  openFolder: (id: string | null) => void;
  folderMenu: FolderMenu;
};

function AgentSection({
  config,
  filteredAgents,
  totalAgents,
  searchQuery,
  inTeam,
  isFilteredView,
  isLoading,
  tree,
  foldersFailed,
  onRetryFolders,
  openFolder,
  folderMenu,
  onNewFolder,
  onImport,
  onNewAgent,
  onAgentsMoved,
}: AgentSectionProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const dispatch = useDispatch();
  const allAgents = useSelector(config.selectData);
  const canCreate = useSelector(selectCanCreate);
  const isUser = config.id === 'user';
  // The agents the caller can file: theirs and the ones shared with them.
  const fileable = isUser || config.id === 'sharedWithYou';
  const query = searchQuery.trim();
  const copy = `agents.sections.${sectionCopy(config.id, inTeam)}`;
  const title =
    config.id === 'sharedWithYou'
      ? t('workspace.page.sharedWithYou')
      : t(`${copy}.title`);
  const offerNewAgent = config.showNewAgentButton && canCreate;

  const updateAgents = (updatedAgents: Agent[]) => {
    dispatch(config.updateAction(updatedAgents));
  };

  // My agents at the root: the top-level folders that hold agents (or
  // nothing yet), then the agents in no folder (an agent filed in a folder
  // the list doesn't know counts as in none); Shared with you also leaves
  // out the ones the caller filed. A search is flat: folders whose name
  // matches, then every matching agent wherever it is filed.
  const folders = isUser
    ? agentFolders(
        tree,
        query ? matchingFolders(tree, query) : childFolders(tree, null),
      )
    : [];
  const shownList = useMemo(() => {
    if (!fileable || query) return filteredAgents;
    return filteredAgents.filter(
      (agent) => !agent.folder_id || !tree.byId.has(agent.folder_id),
    );
  }, [filteredAgents, fileable, query, tree]);

  // Must stay above the empty-state returns below: a hook after an early
  // return is skipped on the render that takes it, which React rejects with
  // "rendered fewer hooks than expected". Reachable now that each filter is
  // its own route — landing straight on an empty one renders once while the
  // data loads, then again once it arrives empty.
  // The All view shows two full rows per section and links to the
  // section's own page for the rest; that page (and a search or a folder)
  // shows everything, 48 per page.
  const columns = useGridColumns();
  const capped = !isFilteredView && !query;
  const cap = columns * 2;
  const {
    page: agentsPage,
    setPage: setAgentsPage,
    pageItems: pagedAgents,
  } = useClientPage(shownList, SHORT_LIST_PAGE_SIZE, query);
  const shownAgents = capped ? shownList.slice(0, cap) : pagedAgents;
  const moreThanCap = capped && shownList.length > cap;

  const hasNoAgentsAtAll = !isLoading && totalAgents === 0;
  const isSearchingWithNoResults =
    !isLoading &&
    query &&
    filteredAgents.length === 0 &&
    folders.length === 0 &&
    totalAgents > 0;

  if (isFilteredView && isSearchingWithNoResults) {
    return <NoSearchResults />;
  }

  // My agents keeps its header even when empty: New folder and Import are
  // there, and so is a folder load error with Retry (an empty folder must
  // not vanish without a word). The section's empty state stands below.
  if (isFilteredView && hasNoAgentsAtAll && folders.length === 0 && !isUser) {
    return (
      <EmptyState
        size="sm"
        illustration="none"
        title={t(`${copy}.emptyState`)}
        action={
          offerNewAgent ? (
            <Button type="button" shape="pill" onClick={() => onNewAgent(null)}>
              {t('agents.newAgent')}
            </Button>
          ) : undefined
        }
      />
    );
  }

  return (
    <div className="mt-8 flex flex-col gap-4" data-agent-section={config.id}>
      <div className="flex w-full flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-col gap-2">
          <div className="flex items-baseline gap-3">
            <h2 className="text-foreground text-lg font-semibold">{title}</h2>
            {moreThanCap && (
              <Button
                type="button"
                variant="link"
                size="inline"
                onClick={() => navigate(agentsFilterPath(config.id))}
              >
                {t('agents.showAll', {
                  count: shownList.length,
                  formatted: formatCount(shownList.length),
                })}
                <ArrowRight aria-hidden />
              </Button>
            )}
          </div>
          <p className="text-muted-foreground text-sm">
            {t(`${copy}.description`)}
          </p>
        </div>
        {isUser && (
          <div className="flex items-center gap-2">
            <UserSectionButtons
              folderId={null}
              onNewFolder={onNewFolder}
              onImport={onImport}
              onNewAgent={onNewAgent}
            />
          </div>
        )}
      </div>

      <div className="flex flex-col gap-4">
        {isUser && foldersFailed ? (
          <FoldersLoadError onRetry={onRetryFolders} />
        ) : null}
        {isLoading ? (
          <div className={TILE_GRID}>
            <SkeletonLoader component="agentCards" count={4} />
          </div>
        ) : (
          <>
            <FolderGrid
              folders={folders}
              openFolder={openFolder}
              folderMenu={folderMenu}
              parentNameOf={
                query
                  ? (found) => searchParentName(tree, found, null)
                  : undefined
              }
            />

            {shownList.length > 0 ? (
              <>
                <div className={TILE_GRID}>
                  {shownAgents.map((agent) => (
                    <AgentCard
                      key={agent.id}
                      agent={agent}
                      agents={allAgents || []}
                      updateAgents={updateAgents}
                      section={config.id}
                      folderLabel={
                        query ? folderLabelOf(tree, agent) : undefined
                      }
                      onMovedToWorkspace={onAgentsMoved}
                    />
                  ))}
                </div>
                {!capped && (
                  <Pagination
                    page={agentsPage}
                    pageSize={SHORT_LIST_PAGE_SIZE}
                    total={shownList.length}
                    onPageChange={setAgentsPage}
                    rangeLabel={(range) =>
                      t('agents.pageRange', pageRangeParams(range))
                    }
                  />
                )}
              </>
            ) : hasNoAgentsAtAll && folders.length === 0 ? (
              <EmptyState
                size="sm"
                illustration="none"
                title={t(`${copy}.emptyState`)}
                action={
                  offerNewAgent ? (
                    <Button
                      type="button"
                      shape="pill"
                      onClick={() => onNewAgent(null)}
                    >
                      {t('agents.newAgent')}
                    </Button>
                  ) : undefined
                }
              />
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}
