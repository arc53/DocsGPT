import {
  BookOpen,
  CalendarIcon,
  Check,
  Eye,
  HardDrive,
  Network,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Trash2,
  Users,
} from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate, useSearchParams } from 'react-router-dom';

import userService from '../api/services/userService';
import modelService from '../api/services/modelService';

import PageToolbar from '../components/PageToolbar';
import RoleBadge from '../components/RoleBadge';
import SearchInput from '../components/SearchInput';
import SkeletonLoader from '../components/SkeletonLoader';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Card, CardFooter, CardTitle } from '../components/ui/card';
import { ActionMenu, type MenuOption } from '../components/ui/dropdown-menu';
import { EmptyState } from '../components/ui/empty-state';
import { Pagination, pageRangeParams } from '../components/ui/pagination';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '../components/ui/tooltip';
import { useDebouncedValue, useLoaderState } from '../hooks';
import { usePageParam, usePageSize } from '../hooks/usePageState';
import ConfirmationModal from '../modals/ConfirmationModal';
import { ActiveState, Doc, DocumentsProps } from '../models/misc';
import type { Model } from '../models/types';
import { showActionToast } from '../notifications/actionToastSlice';
import ShareToTeamModal from '../teams/ShareToTeamModal';
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
import {
  addUploadTask,
  removeUploadTask,
  selectUploadTasks,
  updateUploadTask,
} from '../upload/uploadSlice';
import { can } from '../utils/accessUtils';
import { EMPTY_VALUE, formatDate } from '../utils/dateTimeUtils';
import FileTree from '../components/FileTree';
import ConnectorTree from '../components/ConnectorTree';
import ConnectorIcon from '../connectors/ConnectorIcon';
import { useSignInAgain } from '../connectors/SignInAgainNotice';
import {
  connectionNeedsSignIn,
  loadConnectors,
  selectConnections,
  selectConnectorsLoaded,
} from '../connectors/connectorsSlice';
import type { AppDispatch } from '../store';
import Chunks from '../components/Chunks';
import WikiViewer from '../components/WikiViewer';
import GraphSourceView from '../components/graph/GraphSourceView';
import ConvertToWikiModal from './ConvertToWikiModal';
import EnableGraphRAGModal from './EnableGraphRAGModal';
import { clearGraphBuild, selectGraphBuilds } from './graphBuildSlice';
import SourceConfigModal from './SourceConfigModal';
import TestRetrievalModal from './TestRetrievalModal';
import WikiSettingsModal from './WikiSettingsModal';

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
  const uploadTasks = useSelector(selectUploadTasks);
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
  const syncOptions = [
    { label: t('settings.sources.syncFrequency.never'), value: 'never' },
    { label: t('settings.sources.syncFrequency.daily'), value: 'daily' },
    { label: t('settings.sources.syncFrequency.weekly'), value: 'weekly' },
    { label: t('settings.sources.syncFrequency.monthly'), value: 'monthly' },
  ];
  const [documentToView, setDocumentToView] = useState<Doc>();
  // A citation's "Open in Knowledge" (see knowledgeLink.ts): the source opens
  // on the cited chunk or wiki page, once. The source comes from this page
  // or the app's knowledge list, so the view gets the caller's real access;
  // one in neither is out of reach and just leaves the list showing.
  const knowledge = useSelector(selectSourceDocs);
  const [searchParams, setSearchParams] = useSearchParams();
  const [viewLink, setViewLink] = useState<KnowledgeLink | null>(null);
  useEffect(() => {
    const link = readKnowledgeLink(searchParams);
    if (!link) return;
    const listed =
      currentDocuments.find((d) => d.id === link.sourceId) ??
      knowledge?.find((d) => d.id === link.sourceId);
    if (!listed && knowledge == null) return; // the list is still loading
    setSearchParams(
      (params) => {
        const next = new URLSearchParams(params);
        KNOWLEDGE_LINK_PARAMS.forEach((key) => next.delete(key));
        return next;
      },
      { replace: true },
    );
    if (!listed) return;
    // The app-wide list names the folder flag `is_nested`.
    const raw = listed as Doc & { is_nested?: boolean };
    setDocumentToView({
      ...listed,
      isNested: listed.isNested ?? raw.is_nested,
    });
    setViewLink(link);
  }, [searchParams, knowledge, currentDocuments]);
  const closeDocument = () => {
    setDocumentToView(undefined);
    setViewLink(null);
  };
  const [documentToShare, setDocumentToShare] = useState<Doc | null>(null);
  const [documentForWikiSettings, setDocumentForWikiSettings] =
    useState<Doc | null>(null);
  const [documentToConfigure, setDocumentToConfigure] = useState<Doc | null>(
    null,
  );
  const [configModalState, setConfigModalState] =
    useState<ActiveState>('INACTIVE');
  const [documentToTest, setDocumentToTest] = useState<Doc | null>(null);
  const [testRetrievalState, setTestRetrievalState] =
    useState<ActiveState>('INACTIVE');
  const [documentToConvert, setDocumentToConvert] = useState<Doc | null>(null);
  const [convertModalState, setConvertModalState] =
    useState<ActiveState>('INACTIVE');
  const [documentToGraphRAG, setDocumentToGraphRAG] = useState<Doc | null>(
    null,
  );
  const [graphRAGModalState, setGraphRAGModalState] =
    useState<ActiveState>('INACTIVE');
  const [graphRAGAvailable, setGraphRAGAvailable] = useState<boolean>(false);
  const [hybridAvailable, setHybridAvailable] = useState<boolean>(false);
  const [availableModels, setAvailableModels] = useState<Model[]>([]);
  // Graph-build progress is SSE-driven (graphBuildSlice), so the "building"
  // badge survives closing the modal and reflects the real backend state.
  const graphBuilds = useSelector(selectGraphBuilds);

  /**
   * Shows a failed source action as a destructive toast: the forbidden
   * message on a 403, else the action's own.
   */
  const showActionError = (message: string, status?: number) =>
    dispatch(
      showActionToast({
        variant: 'destructive',
        message:
          status === 403 ? t('settings.sources.errors.forbidden') : message,
      }),
    );

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

  const handleManageSync = (doc: Doc, sync_frequency: string) => {
    setLoading(true);
    userService
      .manageSync({ source_id: doc.id, sync_frequency }, token)
      .then((response: Response) => {
        if (!response.ok) {
          showActionError(
            t('settings.sources.errors.syncFrequency'),
            response.status,
          );
          return null;
        }
        return getDocs(token);
      })
      .then((data) => {
        if (data === null) return null;
        dispatch(setSourceDocs(data));
        return getDocsWithPagination(
          sortField,
          sortOrder,
          currentPage,
          rowsPerPage,
          searchTerm,
          token,
        );
      })
      .then((paginatedData) => {
        if (paginatedData === null) return;
        dispatch(
          setPaginatedDocuments(paginatedData ? paginatedData.docs : []),
        );
        setTotalDocuments(paginatedData ? paginatedData.totalDocuments : 0);
      })
      .catch((error) => {
        console.error('Error in handleManageSync:', error);
        showActionError(t('settings.sources.errors.syncFrequency'));
      })
      .finally(() => {
        setLoading(false);
      });
  };

  const handleSyncNow = async (doc: Doc) => {
    if (!doc.id) {
      return;
    }
    const syncFailed = t('settings.sources.errors.sync');
    try {
      let response: Response;
      if (doc.type?.startsWith('connector')) {
        // The server finds the connector from the source itself.
        response = await userService.syncConnector(doc.id, token);
      } else {
        response = await userService.syncSource({ source_id: doc.id }, token);
      }
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data?.success) {
        console.error('Sync now failed:', data?.error || data?.message);
        showActionError(syncFailed, response.status);
      }
    } catch (error) {
      console.error('Error syncing source:', error);
      showActionError(syncFailed);
    }
  };

  const handleReingest = async (doc: Doc) => {
    if (!doc.id) {
      return;
    }
    const sourceId = doc.id;
    // Drop stale toast rows for this source (a finished/dismissed task
    // would swallow the reingest's SSE events), then open a fresh one.
    uploadTasks
      .filter((task) => task.sourceId === sourceId)
      .forEach((task) => dispatch(removeUploadTask(task.id)));
    const reingestTaskId = `reingest-${sourceId}-${Date.now()}`;
    dispatch(
      addUploadTask({
        id: reingestTaskId,
        fileName: doc.name || sourceId,
        progress: 0,
        status: 'training',
        sourceId,
      }),
    );
    try {
      const response = await userService.reingestSource(
        { source_id: sourceId },
        token,
      );
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data?.success) {
        console.error('Reingest failed:', data?.error || data?.message);
        dispatch(
          updateUploadTask({
            id: reingestTaskId,
            updates: {
              status: 'failed',
              errorMessage: data?.error || data?.message,
            },
          }),
        );
        showActionError(t('settings.sources.errors.reingest'), response.status);
        return;
      }
      refreshDocs(undefined, currentPage, rowsPerPage);
    } catch (error) {
      console.error('Error reingesting source:', error);
      showActionError(t('settings.sources.errors.reingest'));
      dispatch(
        updateUploadTask({
          id: reingestTaskId,
          updates: { status: 'failed' },
        }),
      );
    }
  };

  const [documentToDelete, setDocumentToDelete] = useState<{
    index: number;
    document: Doc;
  } | null>(null);
  const [deleteModalState, setDeleteModalState] =
    useState<ActiveState>('INACTIVE');

  const handleDeleteConfirmation = (index: number, document: Doc) => {
    setDocumentToDelete({ index, document });
    setDeleteModalState('ACTIVE');
  };

  // Returned to ConfirmationModal: it stays pending while the delete runs
  // and keeps a failure (its message) in the dialog. A delete then refetches
  // the page, so the total stays right and a page left empty steps back
  // (the server clamps it; refreshDocs follows).
  const handleConfirmedDelete = async () => {
    if (!documentToDelete) return;
    await handleDeleteDocument(
      documentToDelete.index,
      documentToDelete.document,
    );
    setDocumentToDelete(null);
    refreshDocs(undefined, currentPage, rowsPerPage);
  };

  const getActionOptions = (index: number, document: Doc): MenuOption[] => {
    const isWiki = document.config?.kind === 'wiki' || document.type === 'wiki';
    const isGraphRAG = document.config?.kind === 'graphrag';
    // The server's allowed_actions decide every write (utils/accessUtils).
    const canEdit = can(document, 'edit');
    const actions: MenuOption[] = [
      {
        icon: isGraphRAG ? Network : Eye,
        label: isWiki
          ? t('settings.sources.wiki.view')
          : isGraphRAG
            ? t('settings.sources.graphrag.view.action')
            : t('settings.sources.view'),
        onClick: () => {
          setDocumentToView(document);
        },
        variant: 'default',
      },
    ];

    if (canEdit && document.ingestStatus === 'failed') {
      actions.push({
        icon: RefreshCw,
        label: t('settings.sources.reingest'),
        onClick: () => {
          handleReingest(document);
        },
        variant: 'default',
      });
    }

    if (canEdit && document.syncFrequency) {
      // One row per sync frequency; the current one carries the check.
      syncOptions.forEach((opt) => {
        actions.push({
          icon: document.syncFrequency === opt.value ? Check : RefreshCw,
          label: t('settings.sources.syncFrequency.option', {
            frequency: opt.label,
          }),
          onClick: () => {
            handleManageSync(document, opt.value);
          },
          variant: 'default',
        });
      });
      actions.push({
        icon: RefreshCw,
        label: t('settings.sources.syncNow'),
        onClick: () => {
          handleSyncNow(document);
        },
        variant: 'default',
      });
    }

    // Editors edit the config; a viewer may read it (view_config).
    if (document.id && !isWiki && (canEdit || can(document, 'view_config'))) {
      actions.push({
        icon: canEdit ? SlidersHorizontal : Eye,
        label: canEdit
          ? t('settings.sources.editConfig')
          : t('settings.sources.viewConfig'),
        onClick: () => {
          setDocumentToConfigure(document);
          setConfigModalState('ACTIVE');
        },
        variant: 'default',
      });
    }

    // A wiki's own settings are the owner's (manage_settings).
    if (document.id && isWiki && can(document, 'manage_settings')) {
      actions.push({
        icon: SlidersHorizontal,
        label: t('settings.sources.wiki.settings.action'),
        onClick: () => {
          setDocumentForWikiSettings(document);
        },
        variant: 'default',
      });
    }

    if (document.id) {
      actions.push({
        icon: Search,
        label: t('settings.sources.testRetrieval.action'),
        onClick: () => {
          setDocumentToTest(document);
          setTestRetrievalState('ACTIVE');
        },
        variant: 'default',
      });
    }

    if (
      document.id &&
      !isWiki &&
      canEdit &&
      document.ingestStatus !== 'processing' &&
      document.ingestStatus !== 'failed'
    ) {
      actions.push({
        icon: BookOpen,
        label: t('settings.sources.wiki.convert.action'),
        onClick: () => {
          setDocumentToConvert(document);
          setConvertModalState('ACTIVE');
        },
        variant: 'default',
      });
    }

    // Owner-only unless the owner lets editors share (editors_can_share).
    if (document.id && can(document, 'share')) {
      actions.push({
        icon: Users,
        label: t('settings.sources.shareWithTeam'),
        onClick: () => {
          setDocumentToShare(document);
        },
        variant: 'default',
      });
    }

    if (can(document, 'delete')) {
      actions.push({
        icon: Trash2,
        label: t('settings.sources.delete'),
        onClick: () => {
          handleDeleteConfirmation(index, document);
        },
        variant: 'destructive',
      });
    }

    return actions;
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

  useEffect(() => {
    let cancelled = false;
    userService
      .getConfig()
      .then((response) => response.json())
      .then((config) => {
        if (!cancelled) {
          setGraphRAGAvailable(!!config?.graphrag_available);
          setHybridAvailable(!!config?.hybrid_available);
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  // Models back the graphrag extraction-model picker in the source settings
  // modal; only fetched when the instance supports graphrag.
  useEffect(() => {
    if (!graphRAGAvailable) return;
    let cancelled = false;
    modelService
      .getModels(token)
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (!cancelled && data)
          setAvailableModels(modelService.transformModels(data.models || []));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [graphRAGAvailable, token]);

  // Rendered inside the open source view's own header row.
  const testRetrievalAction = documentToView ? (
    <Button
      type="button"
      variant="outline"
      shape="pill"
      size="field"
      onClick={() => {
        setDocumentToTest(documentToView);
        setTestRetrievalState('ACTIVE');
      }}
    >
      {t('settings.sources.testRetrieval.action')}
    </Button>
  ) : null;

  // Chunk, file, wiki and graph writes follow the source's `edit` action.
  const viewCanEdit = documentToView ? can(documentToView, 'edit') : false;
  // The link only applies to the source it opened.
  const link =
    viewLink && viewLink.sourceId === documentToView?.id ? viewLink : null;

  return documentToView ? (
    <div className="flex flex-col">
      {documentToView.config?.kind === 'wiki' ||
      documentToView.type === 'wiki' ? (
        <WikiViewer
          docId={documentToView.id || ''}
          sourceName={documentToView.name}
          canEdit={viewCanEdit}
          onBackToDocuments={closeDocument}
          headerAction={testRetrievalAction}
          initialPath={link?.wikiPage}
        />
      ) : documentToView.config?.kind === 'graphrag' ? (
        <GraphSourceView
          docId={documentToView.id || ''}
          sourceName={documentToView.name}
          sourceType={documentToView.type}
          isNested={!!documentToView.isNested}
          canEdit={viewCanEdit}
          onBackToDocuments={closeDocument}
          headerAction={testRetrievalAction}
          linkedChunk={link?.chunk}
        />
      ) : documentToView.isNested ? (
        documentToView.type === 'connector:file' ? (
          <ConnectorTree
            docId={documentToView.id || ''}
            canEdit={viewCanEdit}
            sourceName={documentToView.name}
            onBackToDocuments={closeDocument}
            headerAction={testRetrievalAction}
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
          headerAction={testRetrievalAction}
          linkedChunk={link?.chunk}
        />
      )}
      <TestRetrievalModal
        modalState={testRetrievalState}
        setModalState={setTestRetrievalState}
        document={documentToTest}
        hybridAvailable={hybridAvailable}
        graphRAGAvailable={graphRAGAvailable}
        availableModels={availableModels}
      />
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
          ) : !currentDocuments?.length ? (
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
              {currentDocuments.map((document, index) => {
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
                        options={getActionOptions(index, document)}
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
                      <CardFooter className="flex-col items-start gap-1">
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
                          <CalendarIcon className="size-3.5" />
                          {document.date
                            ? formatDate(document.date)
                            : EMPTY_VALUE}
                        </span>
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

      {deleteModalState === 'ACTIVE' && documentToDelete && (
        <ConfirmationModal
          message={t('settings.sources.deleteWarning', {
            interpolation: { escapeValue: false },
            name: documentToDelete.document.name,
          })}
          description={t('settings.sources.deleteConsequence')}
          modalState={deleteModalState}
          setModalState={setDeleteModalState}
          handleSubmit={handleConfirmedDelete}
          error={(error) =>
            error instanceof Error && error.message
              ? error.message
              : t('settings.sources.errors.delete')
          }
          handleCancel={() => {
            setDeleteModalState('INACTIVE');
            setDocumentToDelete(null);
          }}
          submitLabel={t('settings.sources.delete')}
          variant="destructive"
        />
      )}

      {documentToShare && documentToShare.id && (
        <ShareToTeamModal
          resourceType="source"
          resourceId={documentToShare.id}
          resourceName={documentToShare.name}
          onClose={() => setDocumentToShare(null)}
        />
      )}

      <SourceConfigModal
        modalState={configModalState}
        setModalState={(state) => {
          setConfigModalState(state);
          if (state === 'INACTIVE') {
            setDocumentToConfigure(null);
          }
        }}
        document={documentToConfigure}
        onReingest={handleReingest}
        hybridAvailable={hybridAvailable}
        graphRAGAvailable={graphRAGAvailable}
        availableModels={availableModels}
        onEnableGraphRAG={(doc) => {
          setDocumentToGraphRAG(doc);
          setGraphRAGModalState('ACTIVE');
        }}
      />

      <TestRetrievalModal
        modalState={testRetrievalState}
        setModalState={(state) => {
          setTestRetrievalState(state);
          if (state === 'INACTIVE') {
            setDocumentToTest(null);
          }
        }}
        document={documentToTest}
        hybridAvailable={hybridAvailable}
        graphRAGAvailable={graphRAGAvailable}
        availableModels={availableModels}
      />

      {documentForWikiSettings && (
        <WikiSettingsModal
          document={documentForWikiSettings}
          onClose={() => setDocumentForWikiSettings(null)}
        />
      )}

      <ConvertToWikiModal
        modalState={convertModalState}
        setModalState={(state) => {
          setConvertModalState(state);
          if (state === 'INACTIVE') {
            setDocumentToConvert(null);
          }
        }}
        document={documentToConvert}
        onConverted={() => refreshDocs(undefined, currentPage, rowsPerPage)}
      />

      <EnableGraphRAGModal
        modalState={graphRAGModalState}
        setModalState={(state) => {
          setGraphRAGModalState(state);
          if (state === 'INACTIVE') {
            setDocumentToGraphRAG(null);
          }
        }}
        document={documentToGraphRAG}
        onEnabled={() => {
          // The "building" badge is now driven by SSE progress events; just
          // refresh so the source flips to graphrag kind in the list.
          refreshDocs(undefined, currentPage, rowsPerPage);
        }}
      />
    </div>
  );
}
