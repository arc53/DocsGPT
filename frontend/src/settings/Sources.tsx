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

import PageToolbar from '../components/PageToolbar';
import RoleBadge from '../components/RoleBadge';
import SearchInput from '../components/SearchInput';
import SkeletonLoader from '../components/SkeletonLoader';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Card, CardFooter, CardTitle } from '../components/ui/card';
import { ActionMenu } from '../components/ui/dropdown-menu';
import { EmptyState } from '../components/ui/empty-state';
import { IconButton } from '../components/ui/icon-button';
import { Pagination, pageRangeParams } from '../components/ui/pagination';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '../components/ui/tooltip';
import { useDebouncedValue, useLoaderState } from '../hooks';
import { usePageParam, usePageSize } from '../hooks/usePageState';
import {
  ActiveState,
  Doc,
  DocumentsProps,
  type KnowledgeDoc,
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
  STARTED_SYNC_GIVE_UP_MS,
  startedSyncAge,
} from '../connectors/startedSyncs';
import type { AppDispatch } from '../store';
import Chunks from '../components/Chunks';
import WikiViewer from '../components/WikiViewer';
import GraphSourceView from '../components/graph/GraphSourceView';
import { clearGraphBuild, selectGraphBuilds } from './graphBuildSlice';
import {
  canSyncSource,
  isGraphSource,
  isSyncedSource,
  isWikiSource,
  sourcePrimary,
  syncSchedule,
} from './sourceKinds';
import { type StartedSync, useSourceActions } from './useSourceActions';

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
// resumed past the event) is looked for on the list instead: from 2 minutes
// after it started, every 30 s, until 15 minutes (STARTED_SYNC_GIVE_UP_MS),
// when the page stops.
const POLL_AFTER_MS = 2 * 60_000;
const POLL_EVERY_MS = 30_000;

/** Multiples of 12, so a full page fills the 1-, 2-, 3- or 4-column grid. */
const SOURCE_PAGE_SIZES = [12, 24, 48];

/** Six rows of the 4-column desktop grid; 12 on narrower screens. */
const defaultSourcePageSize = (): number =>
  typeof window.matchMedia === 'function' &&
  window.matchMedia('(min-width: 1024px)').matches
    ? 24
    : 12;

const formatTokens = (tokens: number): string => {
  const roundToTwoDecimals = (num: number): string => {
    return (Math.round((num + Number.EPSILON) * 100) / 100).toString();
  };

  if (tokens >= 1_000_000_000) {
    return roundToTwoDecimals(tokens / 1_000_000_000) + 'b';
  } else if (tokens >= 1_000_000) {
    return roundToTwoDecimals(tokens / 1_000_000) + 'm';
  } else if (tokens >= 1_000) {
    return roundToTwoDecimals(tokens / 1_000) + 'k';
  } else {
    return tokens.toString();
  }
};

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
  const [isOnboarding, setIsOnboarding] = useState<boolean>(false);
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
  const unlistedSyncs = startedSyncs
    .map((sync) => ({ ...sync, state: firstIngestState(events, sync.id) }))
    .filter(
      (sync) =>
        !isListed(sync.id) &&
        !(sync.state === 'completed' && reloaded.includes(sync.id)),
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
    (StartedSync & { sourceId: string }) | null
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
  const settleSync = (settled: StartedSync) =>
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
    (
      field: 'date' | 'tokens' | undefined,
      pageNumber?: number,
      rows?: number,
    ) => {
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
      )
        .then((data) => {
          setLoadFailed(data === null);
          if (data === null) return;
          dispatch(setPaginatedDocuments(data.docs));
          setTotalDocuments(data.totalDocuments);
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
      refreshDocs(undefined, currentPage, rowsPerPage);
    },
    // An open source (one opened from a citation may be off this page)
    // follows its own reingest, wiki conversion or graph enable.
    onChanged: () =>
      documentToView?.id
        ? refreshOpenSource(documentToView.id)
        : refreshDocs(undefined, currentPage, rowsPerPage),
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
   * Reads the open source again after its pages changed (added, refreshed,
   * removed or synced in its view): this page of cards, which the open view
   * follows, and the app's knowledge list, which also carries a source opened
   * from off this page (its hosts, page count and sync date).
   */
  const refreshOpenSource = (id: string) => {
    refreshDocs(undefined, currentPage, rowsPerPage);
    getDocs(token)
      .then((docs) => {
        if (!docs) return;
        dispatch(setSourceDocs(docs));
        const fresh = docs.find((d) => d.id === id);
        if (!fresh) return;
        const listed = asListedDoc(fresh);
        setDocumentToView((open) =>
          open?.id === id ? { ...open, ...listed } : open,
        );
      })
      .catch((error) => console.error(error));
  };

  // The first load opens on the URL's page; a new search starts on page 1.
  const searchedTerm = useRef(debouncedSearchTerm);
  useEffect(() => {
    const newSearch = searchedTerm.current !== debouncedSearchTerm;
    searchedTerm.current = debouncedSearchTerm;
    if (newSearch) setCurrentPage(1);
    refreshDocs(undefined, newSearch ? 1 : currentPage, rowsPerPage);
  }, [debouncedSearchTerm]);

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
    refreshDocs(undefined, currentPage, rowsPerPage);
  }, [graphBuilds, dispatch, refreshDocs, currentPage, rowsPerPage]);

  // A started sync's first ingest finished: read this page and the app's
  // knowledge list again, once, so its real card replaces the pending one.
  const finishedKey = unlistedSyncs
    .filter((sync) => sync.state === 'completed')
    .map((sync) => sync.id)
    .join(',');
  useEffect(() => {
    const ids = finishedKey
      .split(',')
      .filter((id) => id && !reloading.current.has(id));
    if (ids.length === 0) return;
    ids.forEach((id) => reloading.current.add(id));
    refreshDocs(undefined, currentPage, rowsPerPage);
    getDocs(token)
      .then((docs) => {
        if (docs) dispatch(setSourceDocs(docs));
      })
      .catch((error) => console.error(error))
      .finally(() => setReloaded((done) => [...done, ...ids]));
  }, [finishedKey]);

  // The fallback when no event comes (see POLL_AFTER_MS): read the app's
  // knowledge list, and this page too once a waited-for source is on it.
  // Past STARTED_SYNC_GIVE_UP_MS the link is dropped, so nothing opens by
  // surprise later; the card stays as indexing until a list holds the source.
  const pollLists = useRef<(ids: string[]) => void>(() => undefined);
  const giveUp = useRef<(ids: string[]) => void>(() => undefined);
  useEffect(() => {
    pollLists.current = (ids) => {
      getDocs(token)
        .then((docs) => {
          if (!docs) return;
          dispatch(setSourceDocs(docs));
          if (docs.some((d) => d.id && ids.includes(d.id)))
            refreshDocs(undefined, currentPage, rowsPerPage);
        })
        .catch((error) => console.error(error));
    };
    giveUp.current = (ids) => {
      if (!linkedId || !ids.includes(linkedId)) return;
      waitedFor.current = null;
      dropLink();
    };
  });
  const waitingKey = unlistedSyncs
    .filter((sync) => sync.state === null)
    .map((sync) => sync.id)
    .join(',');
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
  const pendingSyncs =
    currentPage === 1
      ? [...unlistedSyncs]
          .reverse()
          .filter(
            (sync) =>
              !pendingTerm || sync.name.toLowerCase().includes(pendingTerm),
          )
      : [];

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
          docId={documentToView.id || ''}
          sourceName={documentToView.name}
          sourceType={documentToView.type}
          synced={viewSynced}
          canSync={canSyncSource(documentToView)}
          isNested={!!documentToView.isNested}
          canEdit={viewCanEdit}
          onBackToDocuments={closeDocument}
          headerAction={testRetrievalAction}
          headerMenu={viewMenu}
          linkedChunk={link?.chunk}
          website={documentToView.website}
          syncFrequency={documentToView.syncFrequency}
          syncedAt={documentToView.date}
          settingsVersion={settingsVersion}
          sync={viewSync}
          onSyncSettled={settleSync}
          onBusyChange={reportBusy(documentToView.id || '')}
          onPagesChanged={() =>
            documentToView.id && refreshOpenSource(documentToView.id)
          }
        />
      ) : documentToView.isNested ? (
        documentToView.website ? (
          <WebsiteTree
            key={documentToView.id}
            docId={documentToView.id || ''}
            canEdit={viewCanEdit}
            sourceName={documentToView.name}
            onBackToDocuments={closeDocument}
            headerAction={testRetrievalAction}
            headerMenu={viewMenu}
            hosts={documentToView.website.hosts}
            syncFrequency={documentToView.syncFrequency}
            syncedAt={documentToView.date}
            settingsVersion={settingsVersion}
            sync={viewSync}
            onSyncSettled={settleSync}
            onBusyChange={reportBusy(documentToView.id || '')}
            onPagesChanged={() =>
              documentToView.id && refreshOpenSource(documentToView.id)
            }
            initialPath={link?.chunk?.path}
            linkedChunk={link?.chunk}
          />
        ) : viewSynced ? (
          // Synced from a connection or on a schedule, whatever its stored
          // type (an S3 or GitHub source is typed by its loader): Sync now,
          // no Add file, since a sync replaces the files.
          <ConnectorTree
            docId={documentToView.id || ''}
            canEdit={viewCanEdit}
            sourceName={documentToView.name}
            sourceType={documentToView.type}
            connection={viewConnection}
            canSync={canSyncSource(documentToView)}
            syncFrequency={documentToView.syncFrequency}
            syncedAt={documentToView.date}
            onBackToDocuments={closeDocument}
            headerAction={testRetrievalAction}
            headerMenu={viewMenu}
            initialPath={link?.chunk?.path}
            linkedChunk={link?.chunk}
          />
        ) : (
          <FileTree
            docId={documentToView.id || ''}
            canEdit={viewCanEdit}
            sourceName={documentToView.name}
            onBackToDocuments={closeDocument}
            headerAction={testRetrievalAction}
            headerMenu={viewMenu}
            initialPath={link?.chunk?.path}
            linkedChunk={link?.chunk}
          />
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
              sourcePrimary(documentToView) === 'syncNow' &&
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
          action={
            <Button
              type="button"
              size="field"
              shape="pill"
              onClick={() => {
                setIsOnboarding(false);
                setModalState('ACTIVE');
              }}
            >
              {t('settings.sources.addSource')}
            </Button>
          }
          divider
        />
        <div className="relative w-full">
          {loading ? (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              <SkeletonLoader component="sourceCards" count={rowsPerPage} />
            </div>
          ) : loadFailed ? (
            <EmptyState
              tone="destructive"
              illustration="none"
              title={t('settings.sources.loadError')}
              onRetry={() => refreshDocs(undefined, currentPage, rowsPerPage)}
            />
          ) : !currentDocuments?.length && pendingSyncs.length === 0 ? (
            searchTerm ? (
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
                    onClick={() => {
                      setIsOnboarding(false);
                      setModalState('ACTIVE');
                    }}
                  >
                    {t('settings.sources.addSource')}
                  </Button>
                }
              />
            )
          ) : (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {pendingSyncs.map((sync) => {
                const connection = connections.find(
                  (c) => c.id === sync.connectionId,
                );
                const failed = sync.state === 'failed';
                return (
                  // Not a source yet: nothing to open or manage, so no
                  // stretched button and no ⋯ until its real card is listed.
                  // A failed one can only be dismissed.
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
                          label={t(
                            'settings.connectors.detail.dismissFailedSync',
                            {
                              name: sync.name,
                              interpolation: { escapeValue: false },
                            },
                          )}
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
                      {failed ? (
                        <Badge variant="destructive">
                          {t('settings.sources.ingestFailed')}
                        </Badge>
                      ) : (
                        <Badge variant="neutral">
                          {t('settings.sources.ingestProcessing')}
                        </Badge>
                      )}
                      <CardFooter className="w-full flex-col items-start gap-1">
                        {connection && (
                          <span className="flex max-w-full min-w-0 items-center gap-2">
                            <ConnectorIcon
                              icon={connection.icon}
                              className="text-muted-foreground size-3.5 shrink-0"
                            />
                            <span
                              className="truncate"
                              title={connection.account_label}
                            >
                              {t('settings.sources.viaConnection', {
                                name: connection.name,
                                interpolation: { escapeValue: false },
                              })}
                            </span>
                          </span>
                        )}
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
              })}
              {currentDocuments.map((document) => {
                const docId = document.id ? document.id.toString() : '';
                const connection = document.connectionId
                  ? connections.find((c) => c.id === document.connectionId)
                  : undefined;
                // Sync stops until the reader signs in again (the shared rule).
                const paused = connectionNeedsSignIn(connection);

                return (
                  // DESIGN "A clickable card that holds a link": a stretched
                  // button opens the source; the menu and Reconnect are
                  // siblings above it, never nested in it.
                  <Card
                    key={docId}
                    variant="filled"
                    padding="lg"
                    interactive="within"
                    // Its own height, not the row's: the meta stays under the title.
                    className="min-h-[130px] self-start"
                  >
                    <button
                      type="button"
                      aria-label={document.name}
                      onClick={() => setDocumentToView(document)}
                      className="flex w-full flex-1 cursor-pointer flex-col items-start pr-9 text-left outline-none after:absolute after:inset-0 after:rounded-2xl"
                    >
                      <CardTitle
                        className="line-clamp-2 w-full min-w-0 wrap-anywhere"
                        title={document.name}
                      >
                        {document.name}
                      </CardTitle>
                    </button>
                    <div className="absolute top-5 right-6 z-10">
                      <ActionMenu
                        options={actions.menuOptions(document, 'card')}
                        triggerLabel={t('settings.sources.menuAlt')}
                        triggerTestId={`menu-button-${docId}`}
                        open={actionMenuDocId === docId}
                        onOpenChange={(open) =>
                          setActionMenuDocId(open ? docId : null)
                        }
                      />
                    </div>

                    <div className="flex flex-col items-start justify-start gap-1">
                      <RoleBadge item={document} />
                      {connection && paused && (
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge variant="warning">
                            {t('settings.connectors.status.reconnect')}
                          </Badge>
                          {/* The reader's own connection (only theirs are
                              loaded): sign in again right here, without
                              opening the source. */}
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
                        </div>
                      )}
                      {document.ingestStatus === 'failed' && (
                        <Badge variant="destructive">
                          {t('settings.sources.ingestFailed')}
                        </Badge>
                      )}
                      {document.ingestStatus === 'processing' && (
                        <Badge variant="neutral">
                          {t('settings.sources.ingestProcessing')}
                        </Badge>
                      )}
                      {document.config?.kind === 'graphrag' &&
                        (() => {
                          const build = document.id
                            ? graphBuilds[document.id]
                            : undefined;
                          const isBuilding = build?.status === 'building';
                          const pct =
                            isBuilding && build.total > 0
                              ? Math.min(
                                  100,
                                  Math.round(
                                    (build.current / build.total) * 100,
                                  ),
                                )
                              : null;
                          return (
                            <Badge variant="neutral">
                              <Network aria-hidden="true" />
                              {isBuilding
                                ? pct !== null
                                  ? t('settings.sources.graphrag.buildingPct', {
                                      pct,
                                    })
                                  : t('settings.sources.graphrag.building')
                                : t('settings.sources.graphrag.badge')}
                            </Badge>
                          );
                        })()}
                      {/* w-full: the column is items-start, so without it the
                          footer sizes to a long host line and never truncates. */}
                      <CardFooter className="w-full flex-col items-start gap-1">
                        {connection && (
                          <span className="flex max-w-full min-w-0 items-center gap-2">
                            <ConnectorIcon
                              icon={connection.icon}
                              className="text-muted-foreground size-3.5 shrink-0"
                            />
                            <span
                              className="truncate"
                              title={connection.account_label}
                            >
                              {document.files
                                ? t('settings.sources.viaConnectionFiles', {
                                    name: connection.name,
                                    count: document.files,
                                    files: formatCount(document.files),
                                    interpolation: { escapeValue: false },
                                  })
                                : t('settings.sources.viaConnection', {
                                    name: connection.name,
                                    interpolation: { escapeValue: false },
                                  })}
                            </span>
                          </span>
                        )}
                        {document.website ? (
                          <>
                            {/* Where a website source comes from, and how it
                                stays current, instead of its date. */}
                            <span className="flex max-w-full min-w-0 items-center gap-2">
                              <Globe className="size-3.5 shrink-0" />
                              <span className="min-w-0 truncate">
                                {document.website.hosts.length === 1
                                  ? document.website.hosts[0]
                                  : t('settings.sources.website.sites', {
                                      count: document.website.hosts.length,
                                    })}
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
                        {/* A scheduled source says how it stays current
                            instead of its date; a website without one shows
                            neither. */}
                        {syncSchedule(document) ? (
                          <span className="flex items-center gap-2">
                            <RefreshCw className="size-3.5 shrink-0" />
                            {t('settings.sources.website.synced', {
                              frequency: t(
                                `settings.sources.syncFrequency.${syncSchedule(document)}`,
                              ),
                              when:
                                formatRelative(document.date) ?? EMPTY_VALUE,
                            })}
                          </span>
                        ) : document.website ? null : (
                          <span className="flex items-center gap-2">
                            <CalendarIcon className="size-3.5" />
                            {document.date
                              ? formatDate(document.date)
                              : EMPTY_VALUE}
                          </span>
                        )}
                        <span className="flex items-center gap-2">
                          <HardDrive className="size-3.5" />
                          {document.tokens
                            ? formatTokens(+document.tokens)
                            : EMPTY_VALUE}
                        </span>
                      </CardFooter>
                    </div>
                  </Card>
                );
              })}
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
          isOnboarding={isOnboarding}
          renderTab={null}
          close={() => setModalState('INACTIVE')}
          onSuccessfulUpload={() =>
            refreshDocs(undefined, currentPage, rowsPerPage)
          }
          onBrowseConnectors={() =>
            navigate('/settings/connectors?capability=sync')
          }
        />
      )}

      {signInModals}

      {actions.modals}
    </div>
  );
}
