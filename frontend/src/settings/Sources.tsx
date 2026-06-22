import {
  BookOpen,
  Search as SearchIcon,
  SlidersHorizontal,
  Users,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import userService from '../api/services/userService';

import EyeView from '../assets/eye-view.svg';
import NoFilesIcon from '../assets/no-files.svg';
import NoFilesDarkIcon from '../assets/no-files-dark.svg';
import Trash from '../assets/red-trash.svg';
import SyncIcon from '../assets/sync.svg';
import ThreeDots from '../assets/three-dots.svg';
import CalendarIcon from '../assets/calendar.svg';
import DiscIcon from '../assets/disc.svg';
import Pagination from '../components/DocumentPagination';
import SkeletonLoader from '../components/SkeletonLoader';
import { Button } from '../components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '../components/ui/dropdown-menu';
import { Input } from '../components/ui/input';
import { useDarkTheme, useDebouncedValue, useLoaderState } from '../hooks';
import ConfirmationModal from '../modals/ConfirmationModal';
import { ActiveState, Doc, DocumentsProps } from '../models/misc';
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
import ConvertToWikiModal from './ConvertToWikiModal';
import SourceConfigModal from './SourceConfigModal';

type SourceMenuOption = {
  icon: string | LucideIcon;
  label: string;
  onClick: () => void;
  variant: 'default' | 'destructive';
  iconWidth?: number;
  iconHeight?: number;
};

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
  const [isDarkTheme] = useDarkTheme();
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
  const [documentToConvert, setDocumentToConvert] = useState<Doc | null>(null);
  const [convertModalState, setConvertModalState] =
    useState<ActiveState>('INACTIVE');
  const [syncMenuState, setSyncMenuState] = useState<{
    isOpen: boolean;
    docId: string | null;
    document: Doc | null;
  }>({
    isOpen: false,
    docId: null,
    document: null,
  });

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

  const getActionOptions = (
    index: number,
    document: Doc,
  ): SourceMenuOption[] => {
    const isWiki = document.type === 'wiki';
    // 'team' viewers cannot write; convert is owner/editor only.
    const canEdit =
      document.ownership !== 'team' || document.team_access === 'editor';
    const actions: SourceMenuOption[] = [
      {
        icon: EyeView,
        label: isWiki
          ? t('settings.sources.wiki.view')
          : t('settings.sources.view'),
        onClick: () => {
          setDocumentToView(document);
        },
        iconWidth: 18,
        iconHeight: 18,
        variant: 'default',
      },
    ];

    if (document.ingestStatus === 'failed') {
      actions.push({
        icon: SyncIcon,
        label: t('settings.sources.reingest'),
        onClick: () => {
          handleReingest(document);
        },
        iconWidth: 14,
        iconHeight: 14,
        variant: 'default',
      });
    }

    if (document.syncFrequency) {
      actions.push({
        icon: SyncIcon,
        label: t('settings.sources.sync'),
        onClick: () => {
          setSyncMenuState({
            isOpen: true,
            docId: document.id ?? null,
            document: document,
          });
        },
        iconWidth: 14,
        iconHeight: 14,
        variant: 'default',
      });
      actions.push({
        icon: SyncIcon,
        label: t('settings.sources.syncNow'),
        onClick: () => {
          handleSyncNow(document);
        },
        iconWidth: 14,
        iconHeight: 14,
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
        iconWidth: 16,
        iconHeight: 16,
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
        iconWidth: 16,
        iconHeight: 16,
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
        iconWidth: 16,
        iconHeight: 16,
        variant: 'default',
      });
    }

    actions.push({
      icon: Trash,
      label: t('convTile.delete'),
      onClick: () => {
        handleDeleteConfirmation(index, document);
      },
      iconWidth: 18,
      iconHeight: 18,
      variant: 'destructive',
    });

    return actions;
  };
  useEffect(() => {
    refreshDocs(undefined, 1, rowsPerPage);
  }, [debouncedSearchTerm]);

  return documentToView ? (
    <div className="mt-8 flex flex-col">
      {documentToView.type === 'wiki' ? (
        <WikiViewer
          docId={documentToView.id || ''}
          sourceName={documentToView.name}
          canEdit={
            documentToView.ownership !== 'team' ||
            documentToView.team_access === 'editor'
          }
          onBackToDocuments={() => setDocumentToView(undefined)}
        />
      ) : documentToView.isNested ? (
        documentToView.type === 'connector:file' ? (
          <ConnectorTree
            docId={documentToView.id || ''}
            sourceName={documentToView.name}
            onBackToDocuments={() => setDocumentToView(undefined)}
          />
        ) : (
          <FileTree
            docId={documentToView.id || ''}
            sourceName={documentToView.name}
            onBackToDocuments={() => setDocumentToView(undefined)}
          />
        )
      ) : (
        <Chunks
          documentId={documentToView.id || ''}
          documentName={documentToView.name}
          handleGoBack={() => setDocumentToView(undefined)}
        />
      )}
    </div>
  ) : (
    <div className="mt-8 flex w-full max-w-full flex-col">
      <div className="relative flex grow flex-col">
        <p className="text-muted-foreground mb-5 text-sm leading-6">
          {t('settings.sources.subtitle')}
        </p>
        <div className="mb-6 flex flex-col items-start justify-between gap-3 sm:flex-row sm:items-center">
          <div className="w-full max-w-md sm:w-auto">
            <Input
              maxLength={256}
              label={t('settings.sources.searchPlaceholder')}
              name="Document-search-input"
              type="text"
              id="document-search-input"
              value={searchTerm}
              onChange={(e) => {
                setSearchTerm(e.target.value);
                setCurrentPage(1);
              }}
              labelBgClassName="bg-background"
              className="rounded-full"
              leftIcon={
                <SearchIcon
                  className="text-muted-foreground size-4"
                  strokeWidth={1.75}
                />
              }
            />
          </div>
          <Button
            type="button"
            className="h-11 min-w-[108px] rounded-full whitespace-normal text-white"
            title={t('settings.sources.addSource')}
            onClick={() => {
              setIsOnboarding(false);
              setModalState('ACTIVE');
            }}
          >
            {t('settings.sources.addSource')}
          </Button>
        </div>
        <div className="relative w-full">
          {loading ? (
            <div className="grid w-full grid-cols-1 gap-6 px-2 py-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              <SkeletonLoader component="sourceCards" count={rowsPerPage} />
            </div>
          ) : !currentDocuments?.length ? (
            <div className="flex flex-col items-center justify-center py-12">
              <img
                src={isDarkTheme ? NoFilesDarkIcon : NoFilesIcon}
                alt={t('settings.sources.noData')}
                className="mx-auto mb-6 h-32 w-32"
              />
              <p className="text-center text-lg text-gray-500 dark:text-gray-400">
                {t('settings.sources.noData')}
              </p>
            </div>
          ) : (
            <div className="grid w-full grid-cols-1 gap-6 px-2 py-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {currentDocuments.map((document, index) => {
                const docId = document.id ? document.id.toString() : '';

                return (
                  <div key={docId} className="relative">
                    <div
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
                      className={`bg-muted dark:bg-accent focus-visible:ring-ring/50 flex h-[130px] w-full cursor-pointer flex-col rounded-2xl p-5 transition-all duration-200 outline-none focus-visible:ring-[3px] ${
                        actionMenuDocId === docId ||
                        syncMenuState.docId === docId
                          ? 'scale-[1.05]'
                          : 'hover:scale-[1.05]'
                      }`}
                    >
                      <div className="w-full flex-1">
                        <div className="flex w-full items-center justify-between gap-2">
                          <h3
                            className="dark:text-foreground text-foreground line-clamp-3 text-sm leading-[18px] font-semibold wrap-break-word"
                            title={document.name}
                          >
                            {document.name}
                          </h3>
                          <div className="relative flex items-center justify-end">
                            {document.syncFrequency && (
                              <DropdownMenu
                                open={
                                  syncMenuState.docId === docId &&
                                  syncMenuState.isOpen
                                }
                                onOpenChange={(isOpen) => {
                                  setSyncMenuState((prev) => ({
                                    ...prev,
                                    isOpen,
                                    docId: isOpen ? docId : null,
                                    document: isOpen ? document : null,
                                  }));
                                }}
                              >
                                <DropdownMenuTrigger asChild>
                                  <span
                                    aria-hidden
                                    className="pointer-events-none absolute inset-0 opacity-0"
                                  />
                                </DropdownMenuTrigger>
                                <DropdownMenuContent
                                  align="end"
                                  className="min-w-[120px]"
                                  onClick={(e) => e.stopPropagation()}
                                >
                                  {syncOptions.map((opt) => (
                                    <DropdownMenuItem
                                      key={opt.value}
                                      onSelect={() =>
                                        handleManageSync(document, opt.value)
                                      }
                                    >
                                      {opt.label}
                                    </DropdownMenuItem>
                                  ))}
                                </DropdownMenuContent>
                              </DropdownMenu>
                            )}
                            <DropdownMenu
                              open={actionMenuDocId === docId}
                              onOpenChange={(open) =>
                                setActionMenuDocId(open ? docId : null)
                              }
                            >
                              <DropdownMenuTrigger asChild>
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="icon"
                                  onClick={(e) => e.stopPropagation()}
                                  className="h-[35px] w-6"
                                  aria-label={t('settings.sources.menuAlt')}
                                  data-testid={`menu-button-${docId}`}
                                >
                                  <img
                                    src={ThreeDots}
                                    alt={t('settings.sources.menuAlt')}
                                    className="opacity-60 hover:opacity-100"
                                  />
                                </Button>
                              </DropdownMenuTrigger>
                              <DropdownMenuContent
                                align="end"
                                className="min-w-[144px]"
                                onClick={(e) => e.stopPropagation()}
                              >
                                {getActionOptions(index, document).map(
                                  (option, idx) => (
                                    <DropdownMenuItem
                                      key={idx}
                                      variant={option.variant}
                                      onSelect={() => option.onClick()}
                                    >
                                      {typeof option.icon === 'string' ? (
                                        <img
                                          src={option.icon}
                                          alt=""
                                          width={option.iconWidth ?? 16}
                                          height={option.iconHeight ?? 16}
                                        />
                                      ) : (
                                        <option.icon
                                          size={Math.max(
                                            option.iconWidth ?? 16,
                                            option.iconHeight ?? 16,
                                          )}
                                          strokeWidth={1.75}
                                          aria-hidden="true"
                                        />
                                      )}
                                      <span>{option.label}</span>
                                    </DropdownMenuItem>
                                  ),
                                )}
                              </DropdownMenuContent>
                            </DropdownMenu>
                          </div>
                        </div>
                      </div>

                      <div className="flex flex-col items-start justify-start gap-1">
                        {document.ownership === 'team' && (
                          <span className="bg-muted-foreground/10 text-muted-foreground flex items-center gap-1 rounded-full px-2 py-0.5 text-xs leading-[16px] font-medium">
                            <Users
                              size={11}
                              strokeWidth={2}
                              aria-hidden="true"
                            />
                            {document.team_access === 'editor'
                              ? t('teamAccess.editor')
                              : t('teamAccess.viewer')}
                          </span>
                        )}
                        {document.ingestStatus === 'failed' && (
                          <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs leading-[16px] font-medium text-red-700 dark:bg-red-900/30 dark:text-red-400">
                            {t('settings.sources.ingestFailed')}
                          </span>
                        )}
                        {document.ingestStatus === 'processing' && (
                          <span className="bg-muted-foreground/10 text-muted-foreground rounded-full px-2 py-0.5 text-xs leading-[16px] font-medium">
                            {t('settings.sources.ingestProcessing')}
                          </span>
                        )}
                        <div className="flex items-center gap-2">
                          <img
                            src={CalendarIcon}
                            alt=""
                            className="h-3.5 w-3.5"
                          />
                          <span className="text-muted-foreground text-xs leading-[18px] font-medium">
                            {document.date ? formatDate(document.date) : ''}
                          </span>
                        </div>
                        <div className="flex items-center gap-2">
                          <img src={DiscIcon} alt="" className="h-3.5 w-3.5" />
                          <span className="text-muted-foreground text-xs leading-[18px] font-medium">
                            {document.tokens
                              ? formatTokens(+document.tokens)
                              : ''}
                          </span>
                        </div>
                      </div>
                    </div>
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
            currentPage={currentPage}
            totalPages={totalPages}
            rowsPerPage={rowsPerPage}
            onPageChange={(page) => {
              setCurrentPage(page);
              refreshDocs(undefined, page, rowsPerPage);
            }}
            onRowsPerPageChange={(rows) => {
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
          variant="danger"
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
    </div>
  );
}
