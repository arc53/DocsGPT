import {
  CalendarIcon,
  FileText,
  Globe,
  HardDrive,
  Network,
  RefreshCw,
  X,
} from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate, useSearchParams } from 'react-router-dom';

import userService from '../api/services/userService';
import PageToolbar from '../components/PageToolbar';
import RoleBadge from '../components/RoleBadge';
import SearchInput from '../components/SearchInput';
import SkeletonLoader from '../components/SkeletonLoader';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Card, CardFooter, CardTitle } from '../components/ui/card';
import { Checkbox } from '../components/ui/checkbox';
import { ActionMenu } from '../components/ui/dropdown-menu';
import { EmptyState } from '../components/ui/empty-state';
import { IconButton } from '../components/ui/icon-button';
import { Pagination, pageRangeParams } from '../components/ui/pagination';
import { SectionHeader } from '../components/ui/section-header';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '../components/ui/tooltip';
import { useDebouncedValue, useLoaderState } from '../hooks';
import { usePageParam, usePageSize } from '../hooks/usePageState';
import { shownFilters, useUrlFilter } from '../hooks/useUrlFilter';
import ConfirmationModal from '../modals/ConfirmationModal';
import {
  ActiveState,
  Doc,
  DocumentsProps,
  type KnowledgeDoc,
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
import { can } from '../utils/accessUtils';
import {
  EMPTY_VALUE,
  formatCount,
  formatDate,
  formatRelative,
} from '../utils/dateTimeUtils';
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
import type { Connection } from '../connectors/types';
import type { AppDispatch } from '../store';
import Chunks from '../components/Chunks';
import WikiViewer from '../components/WikiViewer';
import GraphSourceView from '../components/graph/GraphSourceView';
import { buildPct } from '../components/graph/useGraphBuild';
import { clearGraphBuild, selectGraphBuilds } from './graphBuildSlice';
import {
  connectionLabel,
  connectionOf,
  formatTokens,
  IngestBadge,
  ingestState,
  scheduleLabel,
  websiteHostsLabel,
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
const USAGE_LABELS: Record<UsageFilter, string> = {
  all: 'settings.sources.usageFilters.all',
  in_use: 'settings.sources.usageFilters.inUse',
  unused: 'settings.sources.usageFilters.unused',
};

/** The most ids `POST /api/sources/delete` takes at once. */
const BULK_DELETE_MAX = 100;

/** What a failed bulk delete's `code` says, as a reason key. */
const DELETE_FAILURE_REASONS: Record<string, string> = {
  source_busy: 'settings.sources.deleteFailedReasons.busy',
  forbidden: 'settings.sources.deleteFailedReasons.forbidden',
  not_found: 'settings.sources.deleteFailedReasons.notFound',
};

/** Multiples of 12, so a full page fills the 1-, 2-, 3- or 4-column grid. */
const SOURCE_PAGE_SIZES = [12, 24, 48];

/** Six rows of the 4-column desktop grid; 12 on narrower screens. */
const defaultSourcePageSize = (): number =>
  typeof window.matchMedia === 'function' &&
  window.matchMedia('(min-width: 1024px)').matches
    ? 24
    : 12;

/**
 * Where a synced source comes from: the connection's icon and "via <name>"
 * (with its file count when known), the account on hover.
 */
function ConnectionLine({
  connection,
  files,
}: {
  connection: Connection;
  files?: number | null;
}) {
  const { t } = useTranslation();
  return (
    <span className="flex max-w-full min-w-0 items-center gap-2">
      <ConnectorIcon
        icon={connection.icon}
        className="text-muted-foreground size-3.5 shrink-0"
      />
      <span className="truncate" title={connection.account_label}>
        {connectionLabel(t, connection, files)}
      </span>
    </span>
  );
}

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

  const [searchTerm, setSearchTerm] = useState<string>('');
  const debouncedSearchTerm = useDebouncedValue(searchTerm, 500);
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
  // Graph-build progress is SSE-driven (graphBuildSlice), so the "building"
  // badge survives closing the modal and reflects the real backend state.
  const graphBuilds = useSelector(selectGraphBuilds);

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

      setLoading(true);
      getDocsWithPagination(
        newSortField,
        newSortOrder,
        page,
        rowsPerPg,
        debouncedSearchTerm,
        token,
        { kind, usage },
      )
        .then((data) => {
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
          setLoading(false);
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
    },
    // An open source (one opened from a citation may be off this page)
    // follows its own reingest, wiki conversion or graph enable.
    onChanged: () =>
      documentToView?.id ? refreshOpenSource(documentToView.id) : refreshDocs(),
    onPatched: (id, patch) => {
      patchDoc(id, patch);
      // The open view reads what it keeps of the settings again.
      if (id === documentToView?.id) setSettingsVersion((v) => v + 1);
    },
    onSyncStarted: (doc, sync) =>
      doc.id && setStartedSync({ ...sync, sourceId: doc.id }),
    syncingId:
      viewSync?.sourceId ??
      (busyViewId && busyViewId === documentToView?.id ? busyViewId : null),
  });

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
  const listQuery = `${debouncedSearchTerm}\n${kind}\n${usage}`;
  const queried = useRef(listQuery);
  useEffect(() => {
    const newQuery = queried.current !== listQuery;
    queried.current = listQuery;
    if (newQuery) setCurrentPage(1);
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
  const pendingSyncs =
    currentPage === 1 && pendingFits
      ? [...unlistedSyncs]
          .reverse()
          .filter(
            (sync) =>
              !pendingTerm || sync.name.toLowerCase().includes(pendingTerm),
          )
      : [];

  // Needs attention: with no search or filter, the sources whose ingest
  // failed, whose connection needs a sign-in, or that are still indexing
  // (in that order), from the app's knowledge list so a source on any page
  // counts. They leave the paged grid, and page 1 leads with them; a card
  // on this page is the fresher copy of its source.
  const unfiltered = !pendingTerm && kind === 'all' && usage === 'all';
  const attentionRank = (doc: Doc): number | null => {
    const ingest = ingestState(doc);
    if (ingest === 'failed') return 0;
    if (connectionNeedsSignIn(connectionOf(doc, connections))) return 1;
    return ingest === 'processing' ? 2 : null;
  };
  const attentionDocs = unfiltered
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
  const showAttention =
    currentPage === 1 &&
    unfiltered &&
    attentionDocs.length + pendingSyncs.length > 0;

  // Select mode: the cards the caller can delete get a checkbox, and the
  // ticked ones go together. The selection keeps each source (its name and
  // `used_by`), so it survives a page change.
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<Map<string, Doc>>(new Map());
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const canTick = (doc: Doc) => !!doc.id && can(doc, 'delete');
  const toggleSelected = (doc: Doc) =>
    setSelected((current) => {
      const next = new Map(current);
      if (doc.id && next.has(doc.id)) next.delete(doc.id);
      else if (doc.id) next.set(doc.id, doc);
      return next;
    });
  const tickable = [
    ...(showAttention ? attentionDocs : []),
    ...gridDocuments,
  ].filter(canTick);
  const allTicked = tickable.every((doc) => selected.has(doc.id ?? ''));
  const selectAllOnPage = () =>
    setSelected((current) => {
      const next = new Map(current);
      tickable.forEach((doc) => next.set(doc.id ?? '', doc));
      return next;
    });
  const leaveSelecting = () => {
    setSelecting(false);
    setSelected(new Map());
  };
  // Escape leaves the mode, unless it closes the confirm.
  useEffect(() => {
    if (!selecting || confirmingDelete) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !event.defaultPrevented) leaveSelecting();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [selecting, confirmingDelete]);

  const selectedDocs = Array.from(selected.values());
  // The agents that lose the selection: each agent the caller can open
  // once, plus the teammates' agents counted per source.
  const losingAgents =
    new Set(
      selectedDocs.flatMap((doc) =>
        (doc.used_by?.agents ?? []).map((a) => a.id),
      ),
    ).size +
    selectedDocs.reduce((sum, doc) => sum + (doc.used_by?.others ?? 0), 0);

  /**
   * Deletes the selection, at most BULK_DELETE_MAX ids per request. What
   * went leaves the lists; what failed stays ticked, and the confirm stays
   * open saying how many and why (rejecting keeps it open).
   */
  const deleteSelected = async () => {
    const ids = selectedDocs.map((doc) => doc.id ?? '').filter(Boolean);
    const deleted: string[] = [];
    const failed: { id: string; code: string }[] = [];
    let requestFailed = false;
    for (let i = 0; i < ids.length; i += BULK_DELETE_MAX) {
      const batch = ids.slice(i, i + BULK_DELETE_MAX);
      try {
        const response = await userService.deleteSources(batch, token);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const body = await response.json();
        deleted.push(...(body.deleted ?? []));
        failed.push(...(body.failed ?? []));
      } catch (error) {
        console.error(error);
        requestFailed = true;
        batch.forEach((id) => failed.push({ id, code: 'failed' }));
      }
    }
    if (deleted.length > 0) {
      const gone = new Set(deleted);
      if (knowledge)
        dispatch(setSourceDocs(knowledge.filter((d) => !gone.has(d.id ?? ''))));
      dispatch(syncForgotten(deleted));
      refreshDocs();
    }
    if (failed.length === 0) {
      leaveSelecting();
      return;
    }
    setSelected((current) => {
      const next = new Map<string, Doc>();
      failed.forEach(({ id }) => {
        const doc = current.get(id);
        if (doc) next.set(id, doc);
      });
      return next;
    });
    if (requestFailed && deleted.length === 0)
      throw new Error(t('settings.sources.deleteSelectedFailed'));
    const reasons = Array.from(
      new Set(
        failed.map(
          ({ code }) =>
            DELETE_FAILURE_REASONS[code] ??
            'settings.sources.deleteFailedReasons.failed',
        ),
      ),
    ).map((key) => t(key));
    throw new Error(
      [
        t('settings.sources.deleteSomeFailed', {
          count: failed.length,
          formatted: formatCount(failed.length),
        }),
        ...reasons,
      ].join(' '),
    );
  };

  // What every source view takes, and what a tree view adds.
  const viewProps = {
    docId: documentToView?.id || '',
    canEdit: viewCanEdit,
    sourceName: documentToView?.name ?? '',
    onBackToDocuments: closeDocument,
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
        className="min-h-[130px] self-start"
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
        <div
          className={cn(
            'flex w-full flex-1 flex-col items-start',
            failed && 'pr-9',
          )}
        >
          <CardTitle
            className="line-clamp-2 w-full min-w-0 wrap-anywhere"
            title={sync.name}
          >
            {sync.name}
          </CardTitle>
        </div>
        <div className="flex flex-col items-start justify-start gap-1">
          <IngestBadge status={failed ? 'failed' : 'processing'} />
          <CardFooter className="w-full flex-col items-start gap-1">
            {connection && <ConnectionLine connection={connection} />}
            <span className="flex items-center gap-2">
              <RefreshCw className="size-3.5 shrink-0" />
              {t('settings.connectors.detail.firstSyncStarted', {
                time: formatRelative(sync.startedAt) ?? '',
                interpolation: { escapeValue: false },
              })}
            </span>
          </CardFooter>
        </div>
      </Card>
    );
  };

  const renderSourceCard = (document: Doc) => {
    const docId = document.id ? document.id.toString() : '';
    const connection = connectionOf(document, connections);
    // Sync stops until the reader signs in again (the shared rule).
    const paused = connectionNeedsSignIn(connection);
    const ingest = ingestState(document);
    const schedule = scheduleLabel(t, document);
    const pickable = selecting && canTick(document);
    const ticked = pickable && selected.has(docId);

    return (
      // DESIGN "A clickable card that holds a link": a stretched button
      // opens the source (in select mode, ticks it); the menu, the checkbox
      // and Reconnect are siblings above it, never nested in it.
      <Card
        key={docId}
        variant="filled"
        padding="lg"
        interactive="within"
        // Its own height, not the row's: the meta stays under the title.
        // A ticked tile shows it in its checkbox (Card has no selected look;
        // that belongs to OptionCard).
        className="min-h-[130px] self-start"
      >
        <button
          type="button"
          aria-label={document.name}
          aria-pressed={pickable ? ticked : undefined}
          disabled={selecting && !pickable}
          onClick={() =>
            selecting ? toggleSelected(document) : setDocumentToView(document)
          }
          className="flex w-full flex-1 cursor-pointer flex-col items-start pr-9 text-left outline-none after:absolute after:inset-0 after:rounded-2xl disabled:cursor-default"
        >
          <CardTitle
            className="line-clamp-2 w-full min-w-0 wrap-anywhere"
            title={document.name}
          >
            {document.name}
          </CardTitle>
        </button>
        {selecting ? (
          pickable ? (
            <div className="absolute top-5 right-6 z-10 flex size-8 items-center justify-center">
              <Checkbox
                checked={ticked}
                onCheckedChange={() => toggleSelected(document)}
                aria-label={t('settings.sources.selectSource', {
                  name: document.name,
                  interpolation: { escapeValue: false },
                })}
              />
            </div>
          ) : null
        ) : (
          <div className="absolute top-5 right-6 z-10">
            <ActionMenu
              options={actions.menuOptions(document, 'card')}
              triggerLabel={t('settings.sources.menuAlt')}
              triggerTestId={`menu-button-${docId}`}
              open={actionMenuDocId === docId}
              onOpenChange={(open) => setActionMenuDocId(open ? docId : null)}
            />
          </div>
        )}

        <div className="flex flex-col items-start justify-start gap-1">
          <RoleBadge item={document} />
          {connection && paused && (
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="warning">
                {t('settings.connectors.status.reconnect')}
              </Badge>
              {/* The reader's own connection (only theirs are loaded): sign
                  in again right here, without opening the source. */}
              {!selecting && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      shape="pill"
                      className="relative z-10"
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
              )}
            </div>
          )}
          {ingest && <IngestBadge status={ingest} />}
          {document.config?.kind === 'graphrag' &&
            (() => {
              const build = document.id ? graphBuilds[document.id] : undefined;
              const isBuilding = build?.status === 'building';
              const pct = buildPct(build);
              return (
                <Badge variant="neutral">
                  <Network aria-hidden="true" />
                  {isBuilding
                    ? pct !== null
                      ? t('settings.sources.graphrag.buildingPct', { pct })
                      : t('settings.sources.graphrag.building')
                    : t('settings.sources.graphrag.badge')}
                </Badge>
              );
            })()}
          {/* w-full: the column is items-start, so without it the footer
              sizes to a long host line and never truncates. */}
          <CardFooter className="w-full flex-col items-start gap-1">
            {connection && (
              <ConnectionLine connection={connection} files={document.files} />
            )}
            {document.website ? (
              <>
                {/* Where a website source comes from, and how it stays
                    current, instead of its date. */}
                <span className="flex max-w-full min-w-0 items-center gap-2">
                  <Globe className="size-3.5 shrink-0" />
                  <span className="min-w-0 truncate">
                    {websiteHostsLabel(t, document.website)}
                  </span>
                </span>
                <span className="flex items-center gap-2">
                  <FileText className="size-3.5" />
                  {t('settings.sources.website.pageCount', {
                    count: document.website.pages,
                  })}
                </span>
              </>
            ) : null}
            {/* A scheduled source says how it stays current instead of its
                date; a website without one shows neither. */}
            {schedule ? (
              <span className="flex items-center gap-2">
                <RefreshCw className="size-3.5 shrink-0" />
                {t('settings.sources.website.synced', {
                  frequency: schedule,
                  when: formatRelative(document.date) ?? EMPTY_VALUE,
                })}
              </span>
            ) : document.website ? null : (
              <span className="flex items-center gap-2">
                <CalendarIcon className="size-3.5" />
                {document.date ? formatDate(document.date) : EMPTY_VALUE}
              </span>
            )}
            <span className="flex items-center gap-2">
              <HardDrive className="size-3.5" />
              {document.tokens ? formatTokens(+document.tokens) : EMPTY_VALUE}
            </span>
            {agentUseCount(document.used_by) > 0 && (
              // A sibling above the stretched button, so its popover opens.
              <span className="relative z-10">
                <UsedByAgents usage={document.used_by} />
              </span>
            )}
          </CardFooter>
        </div>
      </Card>
    );
  };

  const GRID =
    'grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4';
  const usageFilters = usageCounts
    ? shownFilters(USAGE_FILTERS, usage, usageCounts)
    : [];
  const filtered = kind !== 'all' || usage !== 'all';
  const selectedCount = selected.size;

  const toolbarAction = selecting ? (
    <div className="flex flex-wrap items-center gap-3">
      <span aria-live="polite" className="text-sm">
        {t('settings.sources.selectedCount', {
          count: selectedCount,
          formatted: formatCount(selectedCount),
        })}
      </span>
      <Button
        type="button"
        variant="ghost"
        size="field"
        shape="pill"
        disabled={tickable.length === 0 || allTicked}
        onClick={selectAllOnPage}
      >
        {t('settings.sources.selectAllOnPage')}
      </Button>
      <Button
        type="button"
        variant="outline"
        size="field"
        shape="pill"
        onClick={leaveSelecting}
      >
        {t('cancel')}
      </Button>
      <Button
        type="button"
        variant="destructive-outline"
        size="field"
        shape="pill"
        disabled={selectedCount === 0}
        onClick={() => setConfirmingDelete(true)}
      >
        {t('settings.sources.delete')}
      </Button>
    </div>
  ) : (
    <div className="flex flex-wrap items-center gap-3">
      {currentDocuments.length > 0 && (
        <Button
          type="button"
          variant="outline"
          size="field"
          shape="pill"
          onClick={() => setSelecting(true)}
        >
          {t('settings.sources.select')}
        </Button>
      )}
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

  return documentToView ? (
    <div className="flex flex-col">
      {isWikiSource(documentToView) ? (
        <WikiViewer
          docId={documentToView.id || ''}
          sourceName={documentToView.name}
          canEdit={viewCanEdit}
          onBackToDocuments={closeDocument}
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
          handleGoBack={closeDocument}
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
  ) : (
    <div className="flex w-full max-w-full flex-col">
      <div className="relative flex grow flex-col">
        <PageToolbar
          intro={t('settings.sources.subtitle')}
          search={
            <SearchInput
              maxLength={256}
              label={t('settings.sources.searchPlaceholder')}
              name="Document-search-input"
              id="document-search-input"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
            />
          }
          action={toolbarAction}
          divider
        >
          {/* One ToggleGroup per page: the kind is the pill track, usage a
              pill Select beside it. */}
          {!loadFailed && (kindCounts || usageFilters.length > 0) ? (
            <div className="mb-6 flex flex-wrap items-center gap-3">
              {kindCounts && (
                <SourceKindToggle
                  value={kind}
                  onValueChange={setKind}
                  counts={kindCounts}
                />
              )}
              {usageCounts && usageFilters.length > 0 && (
                <Select
                  value={usage}
                  onValueChange={(value) => setUsage(value as UsageFilter)}
                >
                  <SelectTrigger
                    className="min-w-[125px]"
                    size="field"
                    shape="pill"
                    aria-label={t('settings.sources.usageFilterLabel')}
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent fit>
                    {usageFilters.map((value) => (
                      <SelectItem key={value} value={value}>
                        {t(USAGE_LABELS[value])}
                        <span className="text-muted-foreground tabular-nums">
                          {formatCount(usageCounts[value])}
                        </span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>
          ) : null}
        </PageToolbar>
        <div className="relative w-full">
          {loading ? (
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
          ) : !currentDocuments.length &&
            !showAttention &&
            pendingSyncs.length === 0 ? (
            searchTerm || filtered ? (
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
          ) : showAttention ? (
            <div className="flex flex-col gap-8">
              <section className="flex flex-col gap-3">
                <SectionHeader
                  size="sm"
                  title={t('settings.sources.needsAttention')}
                  count={attentionDocs.length + pendingSyncs.length}
                />
                <div className={GRID}>
                  {attentionDocs.map(renderSourceCard)}
                  {pendingSyncs.map(renderPendingSync)}
                </div>
              </section>
              {gridDocuments.length > 0 && (
                <section className="flex flex-col gap-3">
                  <SectionHeader
                    size="sm"
                    title={t('settings.sources.allKnowledge')}
                    count={Math.max(0, totalDocuments - attentionDocs.length)}
                  />
                  <div className={GRID}>
                    {gridDocuments.map(renderSourceCard)}
                  </div>
                </section>
              )}
            </div>
          ) : (
            <div className={GRID}>
              {pendingSyncs.map(renderPendingSync)}
              {gridDocuments.map(renderSourceCard)}
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
          onSuccessfulUpload={() => refreshDocs()}
          onBrowseConnectors={() =>
            navigate('/settings/connectors?capability=sync')
          }
        />
      )}

      <ConfirmationModal
        message={t('settings.sources.deleteSelectedWarning', {
          count: selectedCount,
          formatted: formatCount(selectedCount),
        })}
        description={[
          losingAgents > 0
            ? t('settings.sources.deleteSelectedUsedBy', {
                count: losingAgents,
                formatted: formatCount(losingAgents),
              })
            : null,
          t('settings.sources.deleteSelectedConsequence', {
            count: selectedCount,
          }),
        ]
          .filter(Boolean)
          .join(' ')}
        modalState={confirmingDelete ? 'ACTIVE' : 'INACTIVE'}
        setModalState={(state) => setConfirmingDelete(state === 'ACTIVE')}
        handleSubmit={deleteSelected}
        error={(reason) =>
          reason instanceof Error && reason.message
            ? reason.message
            : t('settings.sources.deleteSelectedFailed')
        }
        submitLabel={t('settings.sources.delete')}
        variant="destructive"
      />

      {signInModals}

      {actions.modals}
    </div>
  );
}
