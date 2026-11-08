import {
  Cloud,
  Folder as FolderIcon,
  FolderOpen,
  HardDrive,
  Network,
  RefreshCw,
  X,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate, useSearchParams } from 'react-router-dom';

import FilterSelect from '../components/FilterSelect';
import { folderCountLine } from '../components/folders/folderCopy';
import FolderCrumbRow from '../components/folders/FolderCrumbRow';
import FolderNameModal from '../components/folders/FolderNameModal';
import { selectFolderList } from '../components/folders/foldersSlice';
import FolderTile from '../components/folders/FolderTile';
import {
  canCreateIn,
  childFolders,
  folderPath,
  matchingFolders,
  subtreeIds,
} from '../components/folders/folderTree';
import NewFolderButton from '../components/folders/NewFolderButton';
import type { Folder } from '../components/folders/types';
import { useFolderActions } from '../components/folders/useFolderActions';
import { useFolderMenu } from '../components/folders/useFolderMenu';
import { useFolderParam } from '../components/folders/useFolderParam';
import type { Crumb } from '../components/tree/PathHeader';
import { SourceFolderTrail } from '../components/tree/folderTrail';
import PageToolbar from '../components/PageToolbar';
import RoleMeta from '../components/RoleMeta';
import SearchInput from '../components/SearchInput';
import SkeletonLoader from '../components/SkeletonLoader';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import {
  Card,
  CardDescription,
  CardFooter,
  CardTitle,
} from '../components/ui/card';
import { MetaItem, MetaLine } from '../components/ui/meta-line';
import { sourceIcon } from '../components/sourcePickerItems';
import { ActionMenu } from '../components/ui/dropdown-menu';
import { EmptyState } from '../components/ui/empty-state';
import { IconButton } from '../components/ui/icon-button';
import { Pagination, pageRangeParams } from '../components/ui/pagination';
import { SectionHeader } from '../components/ui/section-header';

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '../components/ui/tooltip';
import { useDebouncedValue, useLoaderState } from '../hooks';
import { usePageParam, usePageSize } from '../hooks/usePageState';
import { useUrlFilter } from '../hooks/useUrlFilter';
import {
  ActiveState,
  Doc,
  DocumentsProps,
  type KnowledgeDoc,
  type SourceListScope,
  type UsageFilter,
} from '../models/misc';
import type { SSEEvent } from '../notifications/notificationsSlice';
import { getDocs, getDocsWithPagination } from '../preferences/preferenceApi';
import {
  selectSourceDocs,
  selectToken,
  setPaginatedDocuments,
  setSourceDocs,
} from '../preferences/preferenceSlice';
import Upload from '../upload/Upload';
import {
  KNOWLEDGE_LINK_PARAMS,
  type KnowledgeLink,
  readKnowledgeLink,
} from './knowledgeLink';
import { cn } from '../lib/utils';
import { can, isOwner } from '../utils/accessUtils';
import { formatRelative } from '../utils/dateTimeUtils';
import { agentUseCount } from '../utils/resourceUsage';
import FileTree from '../components/FileTree';
import ConnectorTree from '../components/ConnectorTree';
import WebsiteTree from '../components/WebsiteTree';
import ConnectorIcon from '../connectors/ConnectorIcon';
import { useSignInAgain } from '../connectors/SignInAgainNotice';
import {
  connectionNeedsSignIn,
  loadConnectors,
  selectConnections,
  selectConnectorsLoaded,
  selectStartedSyncs,
  syncForgotten,
} from '../connectors/connectorsSlice';
import {
  firstIngestState,
  partitionStartedSyncs,
  STARTED_SYNC_GIVE_UP_MS,
  startedSyncAge,
  syncIdsKey,
} from '../connectors/startedSyncs';
import type { AppDispatch } from '../store';
import Chunks from '../components/Chunks';
import WikiViewer from '../components/WikiViewer';
import GraphSourceView from '../components/graph/GraphSourceView';
import { buildPct } from '../components/graph/useGraphBuild';
import { clearGraphBuild, selectGraphBuilds } from './graphBuildSlice';
import {
  connectionLabel,
  sourceCardLine,
  connectionOf,
  formatTokens,
  IngestBadge,
  ingestState,
} from './sourceDetails';
import { SourceKindToggle } from './SourceKindFilter';
import {
  canSyncSource,
  isGraphSource,
  isSyncedSource,
  isWikiSource,
  SOURCE_KINDS,
  type SourceKindFilter,
  syncNowIsPrimary,
} from './sourceKinds';
import UsedByAgents from './UsedByAgents';
import { type AcceptedSync, useSourceActions } from './useSourceActions';

const NO_EVENTS: SSEEvent[] = [];
const selectEvents = (state: {
  notifications?: { recentEvents?: SSEEvent[] };
}) => state.notifications?.recentEvents ?? NO_EVENTS;

/**
 * A knowledge-list source in the paginated listing's shape, so a source view
 * opened from it picks the same view as from its card: `isNested` from
 * `is_nested`, and `website` and `files` as given (absent from an older
 * backend, which then opens a website in the file view).
 */
function asListedDoc(doc: KnowledgeDoc): Doc {
  const { is_nested: isNested, ...rest } = doc;
  return {
    ...rest,
    isNested: doc.isNested ?? isNested,
    website: doc.website ?? null,
    files: doc.files ?? null,
  };
}

// A sync with no word on its first ingest (live events off, or the stream
// resumed past the event) is looked for on the lists instead: from 2 minutes
// after it started, every 30 s, until STARTED_SYNC_GIVE_UP_MS.
const POLL_AFTER_MS = 2 * 60_000;
const POLL_EVERY_MS = 30_000;

/** The usage filter's values, as the listing takes them; All first. */
const USAGE_FILTERS = [
  'all',
  'in_use',
  'unused',
] as const satisfies readonly UsageFilter[];
/** The usage filter's labels, shared with Tools and Prompts. */
const USAGE_LABELS: Record<UsageFilter, string> = {
  all: 'settings.usage.filters.all',
  in_use: 'settings.usage.filters.inUse',
  unused: 'settings.usage.filters.unused',
};

/** Multiples of 12, so a full page fills the 1-, 2-, 3- or 4-column grid. */
const SOURCE_PAGE_SIZES = [12, 24, 48];

/** Six rows of the 4-column desktop grid; 12 on narrower screens. */
const defaultSourcePageSize = (): number =>
  typeof window.matchMedia === 'function' &&
  window.matchMedia('(min-width: 1024px)').matches
    ? 24
    : 12;

export default function Sources({
  paginatedDocuments,
  handleDeleteDocument,
}: DocumentsProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const dispatch = useDispatch<AppDispatch>();
  const token = useSelector(selectToken);
  const connections = useSelector(selectConnections);
  // Signing in again reloads the connections, which lifts the pause.
  const { reconnect, modals: signInModals } = useSignInAgain();
  const connectorsLoaded = useSelector(selectConnectorsLoaded);

  useEffect(() => {
    if (!connectorsLoaded) dispatch(loadConnectors({ token }));
  }, [connectorsLoaded, dispatch, token]);

  // The open folder (`?folder=`), its trail and the caller's folder tree.
  const folderList = useSelector(selectFolderList('source'));
  const { folderId, folder, trail, tree, openFolder } =
    useFolderParam('source');
  const folderActions = useFolderActions('source');
  useEffect(() => {
    if (!folderList.loaded && !folderList.loading) void folderActions.reload();
  }, []);
  const hasFolders = folderList.items.length > 0;
  const inFolder = folderId !== null;

  // A search belongs to the folder it was typed in: opening another folder
  // starts with none, at once (no debounce), so the folder's list is read
  // once. "Search all knowledge" carries it to the root.
  const [search, setSearch] = useState<{
    folderId: string | null;
    term: string;
  }>({ folderId: null, term: '' });
  // A search carried to the root by "Search all knowledge" (see below).
  const carriedSearch = useRef<string | null>(null);
  const searchTerm =
    search.folderId === folderId
      ? search.term
      : folderId === null
        ? (carriedSearch.current ?? '')
        : '';
  const setSearchTerm = (term: string) => setSearch({ folderId, term });
  useEffect(() => {
    if (folderId !== null || carriedSearch.current === null) return;
    setSearch({ folderId: null, term: carriedSearch.current });
    carriedSearch.current = null;
  }, [folderId]);
  const debouncedTerm = useDebouncedValue(searchTerm, 500);
  // Clearing the search applies at once; typing waits for the pause.
  const debouncedSearchTerm = searchTerm.trim() ? debouncedTerm : '';
  const [modalState, setModalState] = useState<ActiveState>('INACTIVE');
  const [loading, setLoading] = useLoaderState(false);
  // The last page load failed: an error with Retry, not "no sources".
  const [loadFailed, setLoadFailed] = useState(false);
  const [sortField, setSortField] = useState<'date' | 'tokens'>('date');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  // Pagination: the page lives in the URL, the size on this device.
  const [currentPage, setCurrentPage] = usePageParam('page');
  const [rowsPerPage, setRowsPerPage] = usePageSize(
    'DocsGPTPageSize:sources',
    SOURCE_PAGE_SIZES,
    defaultSourcePageSize(),
  );
  const [totalDocuments, setTotalDocuments] = useState<number>(0);
  // The kind and usage filters live in the address beside the page; a
  // change starts on page 1.
  const [kind, setKind] = useUrlFilter(SOURCE_KINDS, {
    name: 'kind',
    clears: ['page'],
  });
  const [usage, setUsage] = useUrlFilter(USAGE_FILTERS, {
    name: 'usage',
    clears: ['page'],
  });
  // The server's counts per kind and per usage (each with the other filter
  // and the search applied); null from an older backend.
  const [kindCounts, setKindCounts] = useState<Record<
    SourceKindFilter,
    number
  > | null>(null);
  const [usageCounts, setUsageCounts] = useState<Record<
    UsageFilter,
    number
  > | null>(null);

  const [actionMenuDocId, setActionMenuDocId] = useState<string | null>(null);

  const currentDocuments = paginatedDocuments ?? [];
  const [documentToView, setDocumentToView] = useState<Doc>();
  // A citation's "Open in Knowledge" (see knowledgeLink.ts): the source opens
  // on the cited chunk or wiki page, once. The source comes from this page
  // or the app's knowledge list, so the view gets the caller's real access;
  // one in neither is out of reach and just leaves the list showing.
  const knowledge = useSelector(selectSourceDocs);
  const [searchParams, setSearchParams] = useSearchParams();
  const [viewLink, setViewLink] = useState<KnowledgeLink | null>(null);
  // A sync started this session is listed once its first ingest finishes.
  // Until then it shows as a card of its own, and the wizard's Open in
  // Knowledge, which can come before the source exists, waits for it.
  const startedSyncs = useSelector(selectStartedSyncs);
  const events = useSelector(selectEvents);
  const linkedId = searchParams.get('source');
  const linkedSyncState =
    linkedId && startedSyncs.some((sync) => sync.id === linkedId)
      ? (firstIngestState(events, linkedId) ?? 'indexing')
      : null;
  // The finished syncs whose lists have been read again.
  const [reloaded, setReloaded] = useState<string[]>([]);
  const reloading = useRef(new Set<string>());
  const isListed = (id: string) =>
    !!paginatedDocuments?.some((d) => d.id === id) ||
    !!knowledge?.some((d) => d.id === id);
  // Started but not listed. A finished one still missing after the reload
  // (one the caller can't list) is no longer shown as indexing.
  const unlistedSyncs = partitionStartedSyncs(
    startedSyncs,
    isListed,
    events,
  ).unlisted.filter(
    (sync) => !(sync.state === 'completed' && reloaded.includes(sync.id)),
  );
  // A link that waited opens only if the user hasn't opened another source.
  const waitedFor = useRef<string | null>(null);
  const dropLink = () =>
    setSearchParams(
      (params) => {
        const next = new URLSearchParams(params);
        KNOWLEDGE_LINK_PARAMS.forEach((key) => next.delete(key));
        return next;
      },
      { replace: true },
    );
  useEffect(() => {
    const link = readKnowledgeLink(searchParams);
    if (!link) return;
    const listed =
      paginatedDocuments?.find((d) => d.id === link.sourceId) ??
      knowledge?.find((d) => d.id === link.sourceId);
    if (!listed && knowledge == null) return; // the list is still loading
    if (
      !listed &&
      (linkedSyncState === 'indexing' ||
        (linkedSyncState === 'completed' && !reloaded.includes(link.sourceId)))
    ) {
      // Still indexing, or finished and the lists are being read again.
      waitedFor.current = link.sourceId;
      return;
    }
    dropLink();
    const waited = waitedFor.current === link.sourceId;
    waitedFor.current = null;
    if (!listed) return;
    const linked = asListedDoc(listed);
    setDocumentToView((open) => (waited && open ? open : linked));
    setViewLink(link);
  }, [searchParams, knowledge, paginatedDocuments, linkedSyncState, reloaded]);
  // Opening another source while the link waits spends it: the waited-for
  // source then just appears on the list when it's ready.
  useEffect(() => {
    const waiting = waitedFor.current;
    if (!waiting || !documentToView || documentToView.id === waiting) return;
    waitedFor.current = null;
    dropLink();
  }, [documentToView]);
  // A refreshed page carries the open source's new state (converted to a
  // wiki, a finished graph build), and the view follows it.
  useEffect(() => {
    setDocumentToView((doc) => {
      const fresh = doc?.id
        ? paginatedDocuments?.find((d) => d.id === doc.id)
        : undefined;
      return doc && fresh ? { ...doc, ...fresh } : doc;
    });
  }, [paginatedDocuments]);
  // The last sync started from a menu or Source settings; the open website
  // view waits for it when it is its own (see WebsiteTree's `sync`). Leaving
  // the view drops it, so opening the source later doesn't wait again.
  const [startedSync, setStartedSync] = useState<
    (AcceptedSync & { sourceId: string }) | null
  >(null);
  // Only a website view waits for a started sync (and says when it ended):
  // its page list, or the graph view around it. Only there is its Sync now
  // off meanwhile.
  const viewWaits =
    !!documentToView?.website &&
    (isGraphSource(documentToView) || !!documentToView.isNested);
  const viewSync =
    viewWaits && startedSync?.sourceId === documentToView?.id
      ? startedSync
      : null;
  const settleSync = (settled: AcceptedSync) =>
    setStartedSync((current) => (current === settled ? null : current));
  // The website view whose page change or sync is in flight (it says so
  // through onBusyChange): its Sync now is off too, so a sync doesn't queue
  // behind a change and refuse as busy.
  const [busyViewId, setBusyViewId] = useState<string | null>(null);
  const reportBusy = (id: string) => (busy: boolean) =>
    setBusyViewId((current) => (busy ? id : current === id ? null : current));
  // Bumped when the open source's settings are saved (see WebsiteTree).
  const [settingsVersion, setSettingsVersion] = useState(0);
  const closeDocument = () => {
    setDocumentToView(undefined);
    setViewLink(null);
    setStartedSync(null);
    setBusyViewId(null);
  };
  // A source opened inside a folder reads `Knowledge › Carriers › source`:
  // the Knowledge crumb leaves for the root, a folder crumb for that folder.
  const leaveToRoot = () => {
    closeDocument();
    if (folderId) openFolder(null);
  };
  const folderCrumbs: Crumb[] = trail.map((step) => ({
    label: step.name,
    onSelect: () => {
      closeDocument();
      if (step.id !== folderId) openFolder(step.id);
    },
  }));
  // Graph-build progress is SSE-driven (graphBuildSlice), so the "building"
  // badge survives closing the modal and reflects the real backend state.
  const graphBuilds = useSelector(selectGraphBuilds);

  // A search or a filter lists flat: every folder at the root, the open
  // folder's whole subtree inside one. Otherwise the root lists the sources
  // in no folder and a folder its own; the counts cover the subtree.
  const searching = debouncedSearchTerm.trim() !== '';
  const filtered = kind !== 'all' || usage !== 'all';
  const flat = searching || filtered;
  const listScope: SourceListScope | undefined = folderId
    ? { folder: folderId, direct: !flat }
    : flat
      ? undefined
      : { folder: 'root', direct: true };

  // Each page request's number: only the latest one's answer is shown, so a
  // filter, search or page clicked while one loads isn't overwritten by it.
  const latestRequest = useRef(0);
  const refreshDocs = useCallback(
    (field?: 'date' | 'tokens', pageNumber?: number, rows?: number) => {
      const page = pageNumber ?? currentPage;
      const rowsPerPg = rows ?? rowsPerPage;

      // If field is undefined, (Pagination or Search) use the current sortField
      const newSortField = field ?? sortField;

      // If field is undefined, (Pagination or Search) use the current sortOrder
      const newSortOrder =
        field === sortField
          ? sortOrder === 'asc'
            ? 'desc'
            : 'asc'
          : sortOrder;

      // If field is defined, update the sortField and sortOrder
      if (field) {
        setSortField(newSortField);
        setSortOrder(newSortOrder);
      }

      const request = ++latestRequest.current;
      const isLatest = () => request === latestRequest.current;
      setLoading(true);
      getDocsWithPagination(
        newSortField,
        newSortOrder,
        page,
        rowsPerPg,
        debouncedSearchTerm,
        token,
        { kind, usage, ...(listScope ? { scope: listScope } : {}) },
      )
        .then((data) => {
          if (!isLatest()) return;
          setLoadFailed(data === null);
          if (data === null) return;
          dispatch(setPaginatedDocuments(data.docs));
          setTotalDocuments(data.totalDocuments);
          setKindCounts(data.kindCounts ?? null);
          setUsageCounts(data.usageCounts ?? null);
          // The server clamps a page past the end (the last card on the
          // last page was deleted); follow it.
          if (data.currentPage !== page) setCurrentPage(data.currentPage);
        })
        .catch((error) => console.error(error))
        .finally(() => {
          if (isLatest()) setLoading(false);
        });
    },
    [
      currentPage,
      rowsPerPage,
      sortField,
      sortOrder,
      debouncedSearchTerm,
      kind,
      usage,
      listScope?.folder,
      listScope?.direct,
      setCurrentPage,
    ],
  );

  /**
   * Updates one source in place (a saved schedule or config): its card, the
   * app's knowledge list and an open view of it, without reloading the grid.
   */
  const patchDoc = (id: string, patch: Partial<Doc>) => {
    const apply = (list: Doc[]) =>
      list.map((d) => (d.id === id ? { ...d, ...patch } : d));
    if (paginatedDocuments)
      dispatch(setPaginatedDocuments(apply(paginatedDocuments)));
    if (knowledge) dispatch(setSourceDocs(apply(knowledge)));
    setDocumentToView((doc) => (doc?.id === id ? { ...doc, ...patch } : doc));
  };

  const actions = useSourceActions({
    onView: (doc) => setDocumentToView(doc),
    onDelete: (doc) =>
      handleDeleteDocument(
        currentDocuments.findIndex((d) => d.id === doc.id),
        doc,
      ),
    // A delete refetches the page, so the total stays right and a page left
    // empty steps back (the server clamps it; refreshDocs follows). Deleting
    // the open source returns to the list.
    onDeleted: (doc) => {
      if (documentToView?.id === doc.id) closeDocument();
      refreshDocs();
      // A filed source counted in its folder.
      if (doc.folder_id) void folderActions.reload();
    },
    // An open source (one opened from a citation may be off this page)
    // follows its own reingest, wiki conversion or graph enable. The
    // knowledge list is read again too: Needs attention comes from it.
    onChanged: () => {
      if (documentToView?.id) {
        refreshOpenSource(documentToView.id);
        return;
      }
      refreshDocs();
      void reloadKnowledge();
    },
    onPatched: (id, patch) => {
      patchDoc(id, patch);
      // The open view reads what it keeps of the settings again.
      if (id === documentToView?.id) setSettingsVersion((v) => v + 1);
    },
    // Filed elsewhere: the card leaves this list (or names its new folder).
    onMoved: (doc, target) => {
      if (!doc.id) return;
      patchDoc(doc.id, {
        folder_id: target,
        folder_path: folderPath(tree, target).map(({ id, name }) => ({
          id,
          name,
        })),
      });
      refreshDocs();
    },
    onSyncStarted: (doc, sync) =>
      doc.id && setStartedSync({ ...sync, sourceId: doc.id }),
    syncingId:
      viewSync?.sourceId ??
      (busyViewId && busyViewId === documentToView?.id ? busyViewId : null),
  });

  // The folder ⋯ (on its tile and its crumb row). A deleted folder's sources
  // moved up a level, so the list is read again.
  const folderMenu = useFolderMenu('source', () => refreshDocs());
  const [newFolderOpen, setNewFolderOpen] = useState(false);

  /**
   * Reads the app's knowledge list again into the store.
   *
   * @returns The list, or null when it couldn't be read.
   */
  const reloadKnowledge = () =>
    getDocs(token)
      .then((docs) => {
        if (docs) dispatch(setSourceDocs(docs));
        return docs;
      })
      .catch((error) => {
        console.error(error);
        return null;
      });

  /**
   * Reads the open source again after its pages changed (added, refreshed,
   * removed or synced in its view): this page of cards, which the open view
   * follows, and the app's knowledge list, which also carries a source opened
   * from off this page (its hosts, page count and sync date).
   */
  const refreshOpenSource = (id: string) => {
    refreshDocs();
    void reloadKnowledge().then((docs) => {
      const fresh = docs?.find((d) => d.id === id);
      if (!fresh) return;
      const listed = asListedDoc(fresh);
      setDocumentToView((open) =>
        open?.id === id ? { ...open, ...listed } : open,
      );
    });
  };

  // The first load opens on the URL's page; a new search or filter starts
  // on page 1.
  const listQuery = `${debouncedSearchTerm}\n${kind}\n${usage}\n${folderId}`;
  const queried = useRef(listQuery);
  useEffect(() => {
    const newQuery = queried.current !== listQuery;
    queried.current = listQuery;
    // Only when it moves: a page write would race a folder change.
    if (newQuery && currentPage !== 1) setCurrentPage(1);
    refreshDocs(undefined, newQuery ? 1 : currentPage, rowsPerPage);
  }, [listQuery]);

  // When a graph build reaches a terminal state via SSE, refresh the list so
  // the badge reflects the final state, then drop the entry. The modal (a
  // child) captures its summary in its own effect first, so clearing here
  // doesn't race its summary view.
  useEffect(() => {
    const terminal = Object.entries(graphBuilds).filter(
      ([, b]) => b.status === 'completed' || b.status === 'failed',
    );
    if (terminal.length === 0) return;
    terminal.forEach(([sourceId]) => dispatch(clearGraphBuild(sourceId)));
    refreshDocs();
  }, [graphBuilds, dispatch, refreshDocs, currentPage, rowsPerPage]);

  // A started sync's first ingest finished: read this page and the app's
  // knowledge list again, once, so its real card replaces the pending one.
  const finishedKey = syncIdsKey(unlistedSyncs, 'completed');
  useEffect(() => {
    const ids = finishedKey
      .split(',')
      .filter((id) => id && !reloading.current.has(id));
    if (ids.length === 0) return;
    ids.forEach((id) => reloading.current.add(id));
    refreshDocs();
    void reloadKnowledge().then(() => setReloaded((done) => [...done, ...ids]));
  }, [finishedKey]);

  // The fallback when no event comes (see POLL_AFTER_MS): read the app's
  // knowledge list, and this page too once a waited-for source is on it.
  // At the give-up the link is dropped, so nothing opens by surprise later;
  // the card stays as indexing until a list holds the source.
  const pollLists = useRef<(ids: string[]) => void>(() => undefined);
  const giveUp = useRef<(ids: string[]) => void>(() => undefined);
  useEffect(() => {
    pollLists.current = (ids) => {
      void reloadKnowledge().then((docs) => {
        if (docs?.some((d) => d.id && ids.includes(d.id))) refreshDocs();
      });
    };
    giveUp.current = (ids) => {
      if (!linkedId || !ids.includes(linkedId)) return;
      waitedFor.current = null;
      dropLink();
    };
  });
  const waitingKey = syncIdsKey(unlistedSyncs, null);
  useEffect(() => {
    const waiting = startedSyncs.filter((sync) =>
      waitingKey.split(',').includes(sync.id),
    );
    if (waiting.length === 0) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const check = (poll: boolean) => {
      const now = Date.now();
      const ages = waiting
        .map((sync) => ({ id: sync.id, age: startedSyncAge(sync, now) }))
        .filter(({ age }) => Number.isFinite(age));
      const expired = ages.filter(({ age }) => age >= STARTED_SYNC_GIVE_UP_MS);
      if (expired.length > 0) giveUp.current(expired.map(({ id }) => id));
      const active = ages.filter(({ age }) => age < STARTED_SYNC_GIVE_UP_MS);
      if (active.length === 0) return;
      const due = active.filter(({ age }) => age >= POLL_AFTER_MS);
      if (poll && due.length > 0) pollLists.current(due.map(({ id }) => id));
      const next = Math.min(
        ...active.map(({ age }) =>
          age < POLL_AFTER_MS
            ? POLL_AFTER_MS - age
            : Math.min(POLL_EVERY_MS, STARTED_SYNC_GIVE_UP_MS - age),
        ),
      );
      timer = setTimeout(() => check(true), next);
    };
    // The page has just loaded the list, so the first check only schedules.
    check(false);
    return () => clearTimeout(timer);
  }, [waitingKey, startedSyncs]);

  // Chunk, file, wiki and graph writes follow the source's `edit` action.
  const viewCanEdit = documentToView ? can(documentToView, 'edit') : false;

  // The open source's title row: Test retrieval, the kind's primary action
  // (drawn by the view: Add file, Add pages, Sync now), then the source's ⋯.
  const testRetrievalAction = documentToView ? (
    <Button
      type="button"
      variant="outline"
      shape="pill"
      size="field"
      onClick={() => actions.openTestRetrieval(documentToView)}
    >
      {t('settings.sources.testRetrieval.action')}
    </Button>
  ) : null;
  const viewMenuOptions = documentToView
    ? actions.menuOptions(documentToView, 'view')
    : [];
  const viewMenu =
    viewMenuOptions.length > 0 ? (
      <ActionMenu
        size="toolbar"
        options={viewMenuOptions}
        triggerLabel={t('settings.sources.menuAlt')}
        triggerTestId="source-view-menu"
      />
    ) : null;
  const viewConnection = documentToView?.connectionId
    ? connections.find((c) => c.id === documentToView.connectionId)
    : undefined;
  const viewSynced = documentToView ? isSyncedSource(documentToView) : false;
  // The link only applies to the source it opened.
  const link =
    viewLink && viewLink.sourceId === documentToView?.id ? viewLink : null;
  // The syncs still indexing lead the first page, newest first, filtered by
  // name the way the search filters the listed cards.
  const pendingTerm = debouncedSearchTerm.trim().toLowerCase();
  // Not a source yet, so a sync's kind is Synced and nothing uses it.
  const pendingFits =
    (kind === 'all' || kind === 'synced') && usage !== 'in_use';
  // A sync added inside a folder files its source there: it waits in that
  // folder (its subtree, for a search inside a parent), or anywhere when the
  // root lists flat.
  const subtree = useMemo(
    () => (folderId ? subtreeIds(tree, folderId) : null),
    [tree, folderId],
  );
  const pendingInScope = (sync: { folderId?: string }) =>
    subtree
      ? flat
        ? !!sync.folderId && subtree.has(sync.folderId)
        : sync.folderId === folderId
      : flat || !sync.folderId || !tree.byId.has(sync.folderId);
  const pendingSyncs =
    currentPage === 1 && pendingFits
      ? [...unlistedSyncs]
          .reverse()
          .filter(pendingInScope)
          .filter(
            (sync) =>
              !pendingTerm || sync.name.toLowerCase().includes(pendingTerm),
          )
      : [];

  // Needs attention: with no search or filter, the sources the reader can
  // fix: a failed ingest they may reingest (`edit`), then a source on their
  // own connection that needs a sign-in (only theirs are loaded). They come
  // from the app's knowledge list so a source on any page counts. Indexing
  // needs no one, so it stays in the list. Page 1 leads with them and drops
  // them from its grid; later pages, with no such section, keep their own
  // cards. A card on this page is the fresher copy of its source.
  const unfiltered = !inFolder && !pendingTerm && !filtered;
  const attentionRank = (doc: Doc): number | null => {
    if (ingestState(doc) === 'failed' && can(doc, 'edit')) return 0;
    return connectionNeedsSignIn(connectionOf(doc, connections)) ? 1 : null;
  };
  const attentionDocs =
    unfiltered && currentPage === 1
      ? (knowledge ?? [])
          .map(
            (listed) =>
              currentDocuments.find((d) => d.id === listed.id) ??
              asListedDoc(listed),
          )
          .map((doc) => ({ doc, rank: attentionRank(doc) }))
          .filter(
            (entry): entry is { doc: Doc; rank: number } => entry.rank !== null,
          )
          .sort((a, b) => a.rank - b.rank)
          .map(({ doc }) => doc)
      : [];
  const attentionIds = new Set(attentionDocs.map((doc) => doc.id));
  const gridDocuments = currentDocuments.filter(
    (doc) => !attentionIds.has(doc.id),
  );
  const showAttention = attentionDocs.length > 0;
  // Only the root's own (in no folder) are part of its listed total.
  const attentionListed = attentionDocs.filter(
    (doc) => !doc.folder_id || !tree.byId.has(doc.folder_id),
  ).length;

  // The folders on page 1: the level's own, or for a search the matching
  // ones from every level below (a filter alone lists sources only).
  const shownFolders: Folder[] =
    currentPage !== 1
      ? []
      : searching
        ? matchingFolders(
            tree,
            debouncedSearchTerm,
            subtree
              ? new Set([...subtree].filter((id) => id !== folderId))
              : undefined,
          )
        : filtered
          ? []
          : childFolders(tree, folderId);
  /** Where a folder found by a search sits, when not right here. */
  const parentNameOf = (found: Folder): string | undefined => {
    if (!searching) return undefined;
    const parentId = tree.parentOf.get(found.id) ?? null;
    if (parentId === null || parentId === folderId) return undefined;
    return tree.byId.get(parentId)?.name;
  };
  /**
   * The folder trail a source is filed under, where the list mixes levels
   * (a search, a filter, Needs attention): from the root, or from the open
   * folder; none for a source in no folder or right in the open one.
   */
  const folderLabelOf = (doc: Doc): string | null => {
    if (!doc.folder_id) return null;
    const path: { id: string; name: string }[] = tree.byId.has(doc.folder_id)
      ? folderPath(tree, doc.folder_id)
      : (doc.folder_path ?? []);
    const from = folderId
      ? path.findIndex((step) => step.id === folderId) + 1
      : 0;
    const label = path
      .slice(from)
      .map((step) => step.name)
      .join(' › ');
    return label || null;
  };

  // What every source view takes, and what a tree view adds.
  const viewProps = {
    docId: documentToView?.id || '',
    canEdit: viewCanEdit,
    sourceName: documentToView?.name ?? '',
    onBackToDocuments: leaveToRoot,
    headerAction: testRetrievalAction,
    headerMenu: viewMenu,
    linkedChunk: link?.chunk,
  };
  const treeProps = { ...viewProps, initialPath: link?.chunk?.path };
  // A website's page list, in its own view or the graph view's Files tab:
  // its byline, a sync started elsewhere, and its page changes.
  const websiteProps = {
    syncFrequency: documentToView?.syncFrequency,
    syncedAt: documentToView?.date,
    settingsVersion,
    sync: viewSync,
    onSyncSettled: settleSync,
    onBusyChange: reportBusy(documentToView?.id || ''),
    onPagesChanged: () =>
      documentToView?.id && refreshOpenSource(documentToView.id),
  };

  // A sync started this session that isn't a source yet: nothing to open
  // or manage, so no stretched button and no ⋯ until its real card is
  // listed. A failed one can only be dismissed.
  const renderPendingSync = (sync: (typeof pendingSyncs)[number]) => {
    const connection = connections.find((c) => c.id === sync.connectionId);
    const failed = sync.state === 'failed';
    return (
      <Card
        key={`pending-${sync.id}`}
        variant="filled"
        padding="lg"
        className="h-full"
      >
        {failed && (
          <div className="absolute top-5 right-6 z-10">
            <IconButton
              variant="ghost-on-accent"
              size="icon-xs"
              icon={X}
              label={t('settings.connectors.detail.dismissFailedSync', {
                name: sync.name,
                interpolation: { escapeValue: false },
              })}
              onClick={() => dispatch(syncForgotten([sync.id]))}
            />
          </div>
        )}
        {/* A source's tile parts: icon and title, the line, the state pill,
            then the meta line. */}
        <div
          className={cn(
            'flex w-full min-w-0 items-center gap-3',
            failed && 'pr-9',
          )}
        >
          {connection ? (
            <ConnectorIcon icon={connection.icon} className="size-6 shrink-0" />
          ) : (
            <Cloud className="text-foreground size-6 shrink-0" />
          )}
          <CardTitle
            className="line-clamp-2 w-full min-w-0 wrap-anywhere"
            title={sync.name}
          >
            {sync.name}
          </CardTitle>
        </div>
        {connection ? (
          <CardDescription size="xs" className="line-clamp-2 wrap-break-word">
            {connectionLabel(t, connection)}
          </CardDescription>
        ) : null}
        <div className="flex flex-wrap gap-1">
          <IngestBadge status={failed ? 'failed' : 'processing'} />
        </div>
        <CardFooter className="w-full">
          <MetaLine>
            <MetaItem icon={<RefreshCw />}>
              {t('settings.connectors.detail.firstSyncStarted', {
                time: formatRelative(sync.startedAt) ?? '',
                interpolation: { escapeValue: false },
              })}
            </MetaItem>
          </MetaLine>
        </CardFooter>
      </Card>
    );
  };

  /** A source's tile; `showFolder` names its folder trail (a mixed list). */
  const renderSourceCard = (document: Doc, showFolder = false) => {
    const docId = document.id ? document.id.toString() : '';
    const folderLabel = showFolder ? folderLabelOf(document) : null;
    const connection = connectionOf(document, connections);
    // Sync stops until the reader signs in again (the shared rule).
    const paused = connectionNeedsSignIn(connection);
    const ingest = ingestState(document);
    const line = sourceCardLine(t, document, connection);
    const tokens = Number(document.tokens) || 0;
    const graph = document.config?.kind === 'graphrag';
    const build = graph && document.id ? graphBuilds[document.id] : undefined;
    const building = build?.status === 'building';
    const buildingPct = building ? buildPct(build) : null;

    return (
      // DESIGN "A clickable card that holds a link": a stretched button
      // opens the source; the menu, the usage link and Reconnect are siblings
      // above it, never nested.
      // The tile's parts are ConnectorTile's: icon and title, the detail
      // line, the state pills, then the meta line.
      <Card
        key={docId}
        variant="filled"
        padding="lg"
        interactive="within"
        className="h-full"
      >
        <div className="flex w-full min-w-0 items-center gap-3 pr-9">
          <span aria-hidden="true" className="flex shrink-0">
            {sourceIcon(document, connection, 'size-6')}
          </span>
          <button
            type="button"
            aria-label={document.name}
            onClick={() => setDocumentToView(document)}
            className="flex min-w-0 flex-1 cursor-pointer text-left outline-none after:absolute after:inset-0 after:rounded-2xl"
          >
            <CardTitle
              className="line-clamp-2 w-full min-w-0 wrap-anywhere"
              title={document.name}
            >
              {document.name}
            </CardTitle>
          </button>
        </div>
        <div className="absolute top-5 right-6 z-10">
          <ActionMenu
            options={actions.menuOptions(document, 'card')}
            triggerLabel={t('settings.sources.menuAlt')}
            triggerTestId={`menu-button-${docId}`}
            open={actionMenuDocId === docId}
            onOpenChange={(open) => setActionMenuDocId(open ? docId : null)}
          />
        </div>
        {line ? (
          <CardDescription size="xs" className="line-clamp-2 wrap-break-word">
            {line}
          </CardDescription>
        ) : null}
        {/* Pills are states only: the sign-in, the ingest, a graph build. */}
        {(connection && paused) || ingest || building ? (
          <div className="flex flex-wrap gap-1">
            {connection && paused ? (
              <Badge variant="warning">
                {t('settings.connectors.status.reconnect')}
              </Badge>
            ) : null}
            {ingest ? <IngestBadge status={ingest} /> : null}
            {building ? (
              <Badge variant="neutral">
                <Network aria-hidden="true" />
                {buildingPct !== null
                  ? t('settings.sources.graphrag.buildingPct', {
                      pct: buildingPct,
                    })
                  : t('settings.sources.graphrag.building')}
              </Badge>
            ) : null}
          </div>
        ) : null}
        <CardFooter className="w-full">
          <MetaLine>
            {tokens > 0 ? (
              <MetaItem
                icon={<HardDrive />}
                title={t('settings.sources.tokenCount', {
                  tokens: formatTokens(tokens),
                })}
              >
                {formatTokens(tokens)}
              </MetaItem>
            ) : null}
            {graph && !building ? (
              <MetaItem icon={<Network />}>
                {t('settings.sources.graphrag.badge')}
              </MetaItem>
            ) : null}
            {folderLabel ? (
              <MetaItem icon={<FolderIcon />} title={folderLabel} data-folder>
                {folderLabel}
              </MetaItem>
            ) : null}
            {isOwner(document) ? null : <RoleMeta item={document} />}
            {agentUseCount(document.used_by) > 0 ? (
              // A sibling above the stretched button, so its popover opens.
              <span className="relative z-10">
                <UsedByAgents usage={document.used_by} />
              </span>
            ) : null}
          </MetaLine>
          {/* The reader's own connection (only theirs are loaded): sign in
              again right here, without opening the source. */}
          {connection && paused ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  shape="pill"
                  className="relative z-10 ml-auto"
                  onClick={() => reconnect(connection)}
                >
                  {t('settings.connectors.status.reconnect')}
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                {t('settings.sources.paused', {
                  name: connection.name,
                  interpolation: { escapeValue: false },
                })}
              </TooltipContent>
            </Tooltip>
          ) : null}
        </CardFooter>
      </Card>
    );
  };

  const GRID =
    'grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4';
  // New folder and Add knowledge, here or inside the open folder; on a
  // phone the two share the row.
  const toolbarAction = (
    <div className="flex w-full items-center gap-2 *:flex-1 sm:w-auto sm:*:flex-none">
      <NewFolderButton
        atDepthLimit={!canCreateIn(tree, folderId)}
        onClick={() => setNewFolderOpen(true)}
      />
      <Button
        type="button"
        size="field"
        shape="pill"
        onClick={() => setModalState('ACTIVE')}
      >
        {t('settings.sources.addSource')}
      </Button>
    </div>
  );
  const folderMenuButton = folder ? (
    <ActionMenu
      size="toolbar"
      options={folderMenu.menuOptions(folder)}
      triggerLabel={t('folders.menuLabel', {
        name: folder.name,
        interpolation: { escapeValue: false },
      })}
    />
  ) : null;
  // The open folder before its folder list has loaded: wait for it (or say
  // it failed) rather than draw a folder with no name.
  const folderPending = inFolder && !folder;

  const sourcesTitle =
    inFolder || hasFolders
      ? t('settings.sources.sections.sources')
      : t('settings.sources.allKnowledge');
  const sourcesCount =
    Math.max(0, totalDocuments - attentionListed) + pendingSyncs.length;
  const foldersFailed = folderList.failed && !folderList.loaded;
  const foldersError = (
    <EmptyState
      size="sm"
      illustration="none"
      tone="destructive"
      title={t('folders.errors.loadFailed')}
      onRetry={() => void folderActions.reload()}
    />
  );
  // The root with no folders keeps one unheaded grid, as before folders;
  // with folders (or inside one) every group has its heading.
  const sectioned =
    showAttention || inFolder || hasFolders || shownFolders.length > 0;
  const nothingListed =
    !currentDocuments.length &&
    !showAttention &&
    pendingSyncs.length === 0 &&
    shownFolders.length === 0;

  return documentToView ? (
    <SourceFolderTrail.Provider value={folderCrumbs}>
      <div className="flex flex-col">
        {isWikiSource(documentToView) ? (
          <WikiViewer
            docId={documentToView.id || ''}
            sourceName={documentToView.name}
            canEdit={viewCanEdit}
            onBackToDocuments={leaveToRoot}
            headerAction={testRetrievalAction}
            headerMenu={viewMenu}
            initialPath={link?.wikiPage}
          />
        ) : isGraphSource(documentToView) ? (
          <GraphSourceView
            // One view per source: another source's waits and state never
            // carry over.
            key={documentToView.id}
            {...viewProps}
            {...websiteProps}
            sourceType={documentToView.type}
            synced={viewSynced}
            canSync={canSyncSource(documentToView)}
            isNested={!!documentToView.isNested}
            website={documentToView.website}
          />
        ) : documentToView.isNested ? (
          documentToView.website ? (
            <WebsiteTree
              key={documentToView.id}
              {...treeProps}
              {...websiteProps}
              hosts={documentToView.website.hosts}
            />
          ) : viewSynced ? (
            // Synced from a connection or on a schedule, whatever its stored
            // type (an S3 or GitHub source is typed by its loader): Sync now,
            // no Add file, since a sync replaces the files.
            <ConnectorTree
              {...treeProps}
              sourceType={documentToView.type}
              connection={viewConnection}
              canSync={canSyncSource(documentToView)}
              syncFrequency={documentToView.syncFrequency}
              syncedAt={documentToView.date}
            />
          ) : (
            <FileTree {...treeProps} />
          )
        ) : (
          <Chunks
            documentId={documentToView.id || ''}
            documentName={documentToView.name}
            canEdit={viewCanEdit}
            handleGoBack={leaveToRoot}
            headerAction={
              <>
                {testRetrievalAction}
                {/* A flat synced source has no tree to sync from: the
                  button starts the sync and toasts. */}
                {viewCanEdit &&
                syncNowIsPrimary(documentToView) &&
                canSyncSource(documentToView) ? (
                  <Button
                    type="button"
                    shape="pill"
                    size="field"
                    onClick={() => void actions.syncNow(documentToView)}
                  >
                    {t('settings.sources.syncNow')}
                  </Button>
                ) : null}
              </>
            }
            headerMenu={viewMenu}
            linkedChunk={link?.chunk}
          />
        )}
        {actions.modals}
      </div>
    </SourceFolderTrail.Provider>
  ) : (
    <div className="flex w-full max-w-full flex-col">
      <div className="relative flex grow flex-col">
        {/* Inside a folder its crumb row stands where the intro was: the
            trail, its count line, and the folder's ⋯ last. */}
        {folder ? (
          <div className="mb-5">
            <FolderCrumbRow
              type="source"
              trail={trail}
              onNavigate={openFolder}
              meta={folderCountLine(t, folder, 'source')}
              menu={folderMenuButton}
            />
          </div>
        ) : null}
        <PageToolbar
          intro={inFolder ? undefined : t('settings.sources.subtitle')}
          search={
            <SearchInput
              maxLength={256}
              label={
                folder
                  ? t('folders.searchIn', {
                      name: folder.name,
                      interpolation: { escapeValue: false },
                    })
                  : t('settings.sources.searchPlaceholder')
              }
              name="Document-search-input"
              id="document-search-input"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
            />
          }
          action={toolbarAction}
          divider
        >
          {/* One recipe per page: the kind is the pill track, usage the
              FilterSelect beside it. */}
          {!loadFailed && (kindCounts || usageCounts) ? (
            <div className="mb-6 flex flex-wrap items-center gap-3 empty:hidden">
              {kindCounts && (
                <SourceKindToggle
                  value={kind}
                  onValueChange={setKind}
                  counts={kindCounts}
                />
              )}
              {usageCounts && (
                <FilterSelect
                  value={usage}
                  onValueChange={setUsage}
                  values={USAGE_FILTERS}
                  counts={usageCounts}
                  labelOf={(value) => t(USAGE_LABELS[value])}
                  ariaLabel={t('settings.usage.filterLabel')}
                />
              )}
            </div>
          ) : null}
        </PageToolbar>
        <div className="relative w-full">
          {folderPending && foldersFailed ? (
            foldersError
          ) : loading || folderPending ? (
            <div className={GRID}>
              <SkeletonLoader component="sourceCards" count={rowsPerPage} />
            </div>
          ) : loadFailed ? (
            <EmptyState
              tone="destructive"
              illustration="none"
              title={t('settings.sources.loadError')}
              onRetry={() => refreshDocs()}
            />
          ) : nothingListed ? (
            folder && flat ? (
              // Nothing in the folder matches: the same search at the root.
              <EmptyState
                size="xs"
                illustration="none"
                title={t('settings.sources.noResults')}
                description={
                  searching
                    ? t('settings.sources.folders.noMatchIn', {
                        name: folder.name,
                        query: debouncedSearchTerm.trim(),
                        interpolation: { escapeValue: false },
                      })
                    : undefined
                }
                action={
                  <Button
                    type="button"
                    variant="outline"
                    shape="pill"
                    onClick={() => {
                      carriedSearch.current = searchTerm;
                      openFolder(null);
                    }}
                  >
                    {t('settings.sources.folders.searchAll')}
                  </Button>
                }
              />
            ) : folder ? (
              <EmptyState
                size="sm"
                icon={FolderOpen}
                title={t('folders.emptyTitle')}
                description={t('settings.sources.folders.emptyHint')}
                action={
                  <Button
                    type="button"
                    shape="pill"
                    onClick={() => setModalState('ACTIVE')}
                  >
                    {t('settings.sources.addSource')}
                  </Button>
                }
              />
            ) : foldersFailed && !flat && currentPage === 1 ? (
              foldersError
            ) : searchTerm || filtered ? (
              <EmptyState
                size="xs"
                illustration="none"
                title={t('settings.sources.noResults')}
              />
            ) : (
              // Add knowledge is the one way in: its "From a service"
              // section connects a service too.
              <EmptyState
                title={t('settings.sources.noData')}
                description={t('settings.sources.emptyHint')}
                action={
                  <Button
                    type="button"
                    shape="pill"
                    onClick={() => setModalState('ACTIVE')}
                  >
                    {t('settings.sources.addSource')}
                  </Button>
                }
              />
            )
          ) : sectioned ? (
            <div className="flex flex-col gap-8">
              {showAttention ? (
                <section className="flex flex-col gap-3">
                  <SectionHeader
                    size="sm"
                    title={t('settings.sources.needsAttention')}
                    count={attentionDocs.length}
                  />
                  <div className={GRID}>
                    {attentionDocs.map((doc) => renderSourceCard(doc, true))}
                  </div>
                </section>
              ) : null}
              {shownFolders.length > 0 ? (
                <section className="flex flex-col gap-3">
                  <SectionHeader
                    size="sm"
                    title={t('settings.sources.sections.folders')}
                    count={shownFolders.length}
                  />
                  <div className={GRID}>
                    {shownFolders.map((shown) => (
                      <FolderTile
                        key={shown.id}
                        folder={shown}
                        type="source"
                        onOpen={(opened) => openFolder(opened.id)}
                        menuOptions={folderMenu.menuOptions(shown)}
                        parentName={parentNameOf(shown)}
                      />
                    ))}
                  </div>
                </section>
              ) : foldersFailed && !inFolder && !flat && currentPage === 1 ? (
                foldersError
              ) : null}
              {gridDocuments.length + pendingSyncs.length > 0 ? (
                <section className="flex flex-col gap-3">
                  <SectionHeader
                    size="sm"
                    title={sourcesTitle}
                    count={sourcesCount}
                  />
                  <div className={GRID}>
                    {pendingSyncs.map(renderPendingSync)}
                    {gridDocuments.map((doc) => renderSourceCard(doc, flat))}
                  </div>
                </section>
              ) : null}
            </div>
          ) : (
            <div className={GRID}>
              {pendingSyncs.map(renderPendingSync)}
              {gridDocuments.map((doc) => renderSourceCard(doc, flat))}
            </div>
          )}
        </div>
      </div>

      {currentDocuments.length > 0 && (
        <div className="mt-auto pt-4">
          <Pagination
            page={currentPage}
            pageSize={rowsPerPage}
            total={totalDocuments}
            pageSizeOptions={SOURCE_PAGE_SIZES}
            rangeLabel={(range) =>
              t('settings.sources.pageRange', pageRangeParams(range))
            }
            onPageChange={(page) => {
              setCurrentPage(page);
              refreshDocs(undefined, page, rowsPerPage);
            }}
            onPageSizeChange={(rows) => {
              setRowsPerPage(rows);
              setCurrentPage(1);
              refreshDocs(undefined, 1, rows);
            }}
          />
        </div>
      )}

      {modalState === 'ACTIVE' && (
        <Upload
          receivedFile={[]}
          setModalState={setModalState}
          isOnboarding={false}
          renderTab={null}
          close={() => setModalState('INACTIVE')}
          folderId={folderId}
          onSuccessfulUpload={() => {
            refreshDocs();
            // The folder it was added to counts it.
            if (folderId) void folderActions.reload();
          }}
          onBrowseConnectors={() =>
            navigate('/settings/connectors?capability=sync')
          }
        />
      )}

      {signInModals}

      {actions.modals}
      {folderMenu.dialogs}
      <FolderNameModal
        open={newFolderOpen}
        onOpenChange={setNewFolderOpen}
        type="source"
        mode="create"
        parentId={folderId}
      />
    </div>
  );
}
