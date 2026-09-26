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
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import userService from '../api/services/userService';
import modelService from '../api/services/modelService';

import PageToolbar from '../components/PageToolbar';
import SearchInput from '../components/SearchInput';
import SkeletonLoader from '../components/SkeletonLoader';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Card, CardFooter, CardTitle } from '../components/ui/card';
import { ActionMenu, type MenuOption } from '../components/ui/dropdown-menu';
import { EmptyState } from '../components/ui/empty-state';
import { Pagination } from '../components/ui/pagination';
import { useDebouncedValue, useLoaderState } from '../hooks';
import ConfirmationModal from '../modals/ConfirmationModal';
import { ActiveState, Doc, DocumentsProps } from '../models/misc';
import type { Model } from '../models/types';
import ShareToTeamModal from '../teams/ShareToTeamModal';
import { getDocs, getDocsWithPagination } from '../preferences/preferenceApi';
import {
  selectToken,
  setPaginatedDocuments,
  setSourceDocs,
} from '../preferences/preferenceSlice';
import Upload from '../upload/Upload';
import {
  addUploadTask,
  removeUploadTask,
  selectUploadTasks,
  updateUploadTask,
} from '../upload/uploadSlice';
import { formatDate } from '../utils/dateTimeUtils';
import FileTree from '../components/FileTree';
import ConnectorTree from '../components/ConnectorTree';
import Chunks from '../components/Chunks';
import WikiViewer from '../components/WikiViewer';
import GraphView from '../components/GraphView';
import ConvertToWikiModal from './ConvertToWikiModal';
import EnableGraphRAGModal from './EnableGraphRAGModal';
import { clearGraphBuild, selectGraphBuilds } from './graphBuildSlice';
import SourceConfigModal from './SourceConfigModal';
import TestRetrievalModal from './TestRetrievalModal';

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
  const dispatch = useDispatch();
  const token = useSelector(selectToken);
  const uploadTasks = useSelector(selectUploadTasks);

  const [searchTerm, setSearchTerm] = useState<string>('');
  const debouncedSearchTerm = useDebouncedValue(searchTerm, 500);
  const [modalState, setModalState] = useState<ActiveState>('INACTIVE');
  const [isOnboarding, setIsOnboarding] = useState<boolean>(false);
  const [loading, setLoading] = useLoaderState(false);
  const [sortField, setSortField] = useState<'date' | 'tokens'>('date');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  // Pagination
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [rowsPerPage, setRowsPerPage] = useState<number>(10);
  const [totalPages, setTotalPages] = useState<number>(1);

  const [actionMenuDocId, setActionMenuDocId] = useState<string | null>(null);

  const currentDocuments = paginatedDocuments ?? [];
  const syncOptions = [
    { label: t('settings.sources.syncFrequency.never'), value: 'never' },
    { label: t('settings.sources.syncFrequency.daily'), value: 'daily' },
    { label: t('settings.sources.syncFrequency.weekly'), value: 'weekly' },
    { label: t('settings.sources.syncFrequency.monthly'), value: 'monthly' },
  ];
  const [documentToView, setDocumentToView] = useState<Doc>();
  const [documentToShare, setDocumentToShare] = useState<Doc | null>(null);
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
          dispatch(setPaginatedDocuments(data ? data.docs : []));
          setTotalPages(data ? data.totalPages : 0);
        })
        .catch((error) => console.error(error))
        .finally(() => {
          setLoading(false);
        });
    },
    [currentPage, rowsPerPage, sortField, sortOrder, debouncedSearchTerm],
  );

  const handleManageSync = (doc: Doc, sync_frequency: string) => {
    setLoading(true);
    userService
      .manageSync({ source_id: doc.id, sync_frequency }, token)
      .then(() => {
        return getDocs(token);
      })
      .then((data) => {
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
        dispatch(
          setPaginatedDocuments(paginatedData ? paginatedData.docs : []),
        );
        setTotalPages(paginatedData ? paginatedData.totalPages : 0);
      })
      .catch((error) => console.error('Error in handleManageSync:', error))
      .finally(() => {
        setLoading(false);
      });
  };

  const getConnectorProvider = async (doc: Doc): Promise<string | null> => {
    if (doc.provider) {
      return doc.provider;
    }
    if (!doc.id) {
      return null;
    }
    try {
      const directoryResponse = await userService.getDirectoryStructure(
        doc.id,
        token,
      );
      const directoryData = await directoryResponse.json();
      return directoryData?.provider ?? null;
    } catch (error) {
      console.error('Error fetching connector provider:', error);
      return null;
    }
  };

  const handleSyncNow = async (doc: Doc) => {
    if (!doc.id) {
      return;
    }
    try {
      if (doc.type?.startsWith('connector')) {
        const provider = await getConnectorProvider(doc);
        if (!provider) {
          console.error('Sync now failed: provider not found');
          return;
        }
        const response = await userService.syncConnector(
          doc.id,
          provider,
          token,
        );
        const data = await response.json();
        if (!data.success) {
          console.error('Sync now failed:', data.error || data.message);
        }
        return;
      }
      const response = await userService.syncSource(
        { source_id: doc.id },
        token,
      );
      const data = await response.json();
      if (!data.success) {
        console.error('Sync now failed:', data.error || data.message);
      }
    } catch (error) {
      console.error('Error syncing source:', error);
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
      const data = await response.json();
      if (!data.success) {
        console.error('Reingest failed:', data.error || data.message);
        dispatch(
          updateUploadTask({
            id: reingestTaskId,
            updates: {
              status: 'failed',
              errorMessage: data.error || data.message,
            },
          }),
        );
        return;
      }
      refreshDocs(undefined, currentPage, rowsPerPage);
    } catch (error) {
      console.error('Error reingesting source:', error);
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

  const handleConfirmedDelete = () => {
    if (documentToDelete) {
      handleDeleteDocument(documentToDelete.index, documentToDelete.document);
      setDeleteModalState('INACTIVE');
      setDocumentToDelete(null);
    }
  };

  const getActionOptions = (index: number, document: Doc): MenuOption[] => {
    const isWiki = document.config?.kind === 'wiki' || document.type === 'wiki';
    const isGraphRAG = document.config?.kind === 'graphrag';
    // 'team' viewers cannot write; convert is owner/editor only.
    const canEdit =
      document.ownership !== 'team' || document.team_access === 'editor';
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

    if (document.ingestStatus === 'failed') {
      actions.push({
        icon: RefreshCw,
        label: t('settings.sources.reingest'),
        onClick: () => {
          handleReingest(document);
        },
        variant: 'default',
      });
    }

    if (document.syncFrequency) {
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

    if (document.id && !isWiki) {
      actions.push({
        icon: SlidersHorizontal,
        label: t('settings.sources.editConfig'),
        onClick: () => {
          setDocumentToConfigure(document);
          setConfigModalState('ACTIVE');
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

    // Sharing is an owner-only action: hide it for sources shared into the
    // user's workspace by a team.
    if (document.ownership !== 'team' && document.id) {
      actions.push({
        icon: Users,
        label: t('settings.sources.shareWithTeam'),
        onClick: () => {
          setDocumentToShare(document);
        },
        variant: 'default',
      });
    }

    actions.push({
      icon: Trash2,
      label: t('convTile.delete'),
      onClick: () => {
        handleDeleteConfirmation(index, document);
      },
      variant: 'destructive',
    });

    return actions;
  };
  useEffect(() => {
    refreshDocs(undefined, 1, rowsPerPage);
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

  return documentToView ? (
    <div className="flex flex-col">
      {documentToView.config?.kind === 'wiki' ||
      documentToView.type === 'wiki' ? (
        <WikiViewer
          docId={documentToView.id || ''}
          sourceName={documentToView.name}
          canEdit={
            documentToView.ownership !== 'team' ||
            documentToView.team_access === 'editor'
          }
          onBackToDocuments={() => setDocumentToView(undefined)}
          headerAction={testRetrievalAction}
        />
      ) : documentToView.config?.kind === 'graphrag' ? (
        <GraphView
          docId={documentToView.id || ''}
          sourceName={documentToView.name}
          onBackToDocuments={() => setDocumentToView(undefined)}
          headerAction={testRetrievalAction}
        />
      ) : documentToView.isNested ? (
        documentToView.type === 'connector:file' ? (
          <ConnectorTree
            docId={documentToView.id || ''}
            sourceName={documentToView.name}
            onBackToDocuments={() => setDocumentToView(undefined)}
            headerAction={testRetrievalAction}
          />
        ) : (
          <FileTree
            docId={documentToView.id || ''}
            sourceName={documentToView.name}
            onBackToDocuments={() => setDocumentToView(undefined)}
            headerAction={testRetrievalAction}
          />
        )
      ) : (
        <Chunks
          documentId={documentToView.id || ''}
          documentName={documentToView.name}
          handleGoBack={() => setDocumentToView(undefined)}
          headerAction={testRetrievalAction}
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
              onChange={(e) => {
                setSearchTerm(e.target.value);
                setCurrentPage(1);
              }}
            />
          }
          action={
            <Button
              type="button"
              size="field"
              shape="pill"
              title={t('settings.sources.addSource')}
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
          ) : !currentDocuments?.length ? (
            <EmptyState title={t('settings.sources.noData')} />
          ) : (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {currentDocuments.map((document, index) => {
                const docId = document.id ? document.id.toString() : '';

                return (
                  <div key={docId} className="relative">
                    <Card
                      variant="filled"
                      interactive
                      padding="lg"
                      role="button"
                      tabIndex={0}
                      aria-label={document.name}
                      onClick={() => setDocumentToView(document)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          setDocumentToView(document);
                        }
                      }}
                      className="min-h-[130px]"
                    >
                      <div className="w-full flex-1">
                        <div className="flex w-full items-center justify-between gap-2">
                          <CardTitle
                            className="line-clamp-2 min-w-0 flex-1 wrap-anywhere"
                            title={document.name}
                          >
                            {document.name}
                          </CardTitle>
                          <div className="relative flex shrink-0 items-center justify-end">
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
                        </div>
                      </div>

                      <div className="flex flex-col items-start justify-start gap-1">
                        {document.ownership === 'team' && (
                          <Badge variant="neutral">
                            <Users className="size-3" aria-hidden="true" />
                            {document.team_access === 'editor'
                              ? t('teamAccess.editor')
                              : t('teamAccess.viewer')}
                          </Badge>
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
                                <Network
                                  className="size-3"
                                  aria-hidden="true"
                                />
                                {isBuilding
                                  ? pct !== null
                                    ? t(
                                        'settings.sources.graphrag.buildingPct',
                                        { pct },
                                      )
                                    : t('settings.sources.graphrag.building')
                                  : t('settings.sources.graphrag.badge')}
                              </Badge>
                            );
                          })()}
                        <CardFooter className="flex-col items-start gap-1">
                          <span className="flex items-center gap-2">
                            <CalendarIcon className="size-3.5" />
                            {document.date ? formatDate(document.date) : ''}
                          </span>
                          <span className="flex items-center gap-2">
                            <HardDrive className="size-3.5" />
                            {document.tokens
                              ? formatTokens(+document.tokens)
                              : ''}
                          </span>
                        </CardFooter>
                      </div>
                    </Card>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {currentDocuments.length > 0 && totalPages > 1 && (
        <div className="mt-auto pt-4">
          <Pagination
            page={currentPage}
            pageCount={totalPages}
            pageSize={rowsPerPage}
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
        />
      )}

      {deleteModalState === 'ACTIVE' && documentToDelete && (
        <ConfirmationModal
          message={t('settings.sources.deleteWarning', {
            name: documentToDelete.document.name,
          })}
          modalState={deleteModalState}
          setModalState={setDeleteModalState}
          handleSubmit={handleConfirmedDelete}
          handleCancel={() => {
            setDeleteModalState('INACTIVE');
            setDocumentToDelete(null);
          }}
          submitLabel={t('convTile.delete')}
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
