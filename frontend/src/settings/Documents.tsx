import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import userService from '../api/services/userService';
import ArrowLeft from '../assets/arrow-left.svg';
import caretSort from '../assets/caret-sort.svg';
import Edit from '../assets/edit.svg';
import EyeView from '../assets/eye-view.svg';
import NoFilesDarkIcon from '../assets/no-files-dark.svg';
import NoFilesIcon from '../assets/no-files.svg';
import Trash from '../assets/red-trash.svg';
import SyncIcon from '../assets/sync.svg';
import ThreeDots from '../assets/three-dots.svg';
import ContextMenu, { MenuOption } from '../components/ContextMenu';
import Pagination from '../components/DocumentPagination';
import DropdownMenu from '../components/DropdownMenu';
import Input from '../components/Input';
import SkeletonLoader from '../components/SkeletonLoader';
import Spinner from '../components/Spinner';
import { useDarkTheme, useLoaderState } from '../hooks';
import ChunkModal from '../modals/ChunkModal';
import ConfirmationModal from '../modals/ConfirmationModal';
import { ActiveState, Doc, DocumentsProps } from '../models/misc';
import { getDocs, getDocsWithPagination } from '../preferences/preferenceApi';
import {
  selectToken,
  setPaginatedDocuments,
  setSourceDocs,
} from '../preferences/preferenceSlice';
import Upload from '../upload/Upload';
import { formatDate } from '../utils/dateTimeUtils';
import { ChunkType } from './types';

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

export default function Documents({
  paginatedDocuments,
  handleDeleteDocument,
}: DocumentsProps) {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const token = useSelector(selectToken);

  const [searchTerm, setSearchTerm] = useState<string>('');
  const [modalState, setModalState] = useState<ActiveState>('INACTIVE');
  const [isOnboarding, setIsOnboarding] = useState<boolean>(false);
  const [loading, setLoading] = useLoaderState(false);
  const [sortField, setSortField] = useState<'date' | 'tokens'>('date');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  // Pagination
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [rowsPerPage, setRowsPerPage] = useState<number>(10);
  const [totalPages, setTotalPages] = useState<number>(1);

  const [activeMenuId, setActiveMenuId] = useState<string | null>(null);
  const menuRefs = useRef<{
    [key: string]: React.RefObject<HTMLDivElement | null>;
  }>({});

  // Create or get a ref for each document wrapper div (not the td)
  const getMenuRef = (docId: string) => {
    if (!menuRefs.current[docId]) {
      menuRefs.current[docId] = React.createRef<HTMLDivElement>();
    }
    return menuRefs.current[docId];
  };

  const handleMenuClick = (e: React.MouseEvent, docId: string) => {
    e.preventDefault();
    e.stopPropagation();

    const isAnyMenuOpen =
      (syncMenuState.isOpen && syncMenuState.docId === docId) ||
      activeMenuId === docId;

    if (isAnyMenuOpen) {
      setSyncMenuState((prev) => ({ ...prev, isOpen: false, docId: null }));
      setActiveMenuId(null);
      return;
    }
    setActiveMenuId(docId);
  };

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (activeMenuId) {
        const activeRef = menuRefs.current[activeMenuId];
        if (
          activeRef?.current &&
          !activeRef.current.contains(event.target as Node)
        ) {
          setActiveMenuId(null);
        }
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [activeMenuId]);

  const currentDocuments = paginatedDocuments ?? [];
  const syncOptions = [
    { label: t('settings.documents.syncFrequency.never'), value: 'never' },
    { label: t('settings.documents.syncFrequency.daily'), value: 'daily' },
    { label: t('settings.documents.syncFrequency.weekly'), value: 'weekly' },
    { label: t('settings.documents.syncFrequency.monthly'), value: 'monthly' },
  ];
  const [showDocumentChunks, setShowDocumentChunks] = useState<Doc>();
  const [isMenuOpen, setIsMenuOpen] = useState(false);
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
        searchTerm,
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
    [currentPage, rowsPerPage, sortField, sortOrder, searchTerm],
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
    const actions: MenuOption[] = [
      {
        icon: EyeView,
        label: t('settings.documents.view'),
        onClick: () => {
          setShowDocumentChunks(document);
        },
        iconWidth: 18,
        iconHeight: 18,
        variant: 'primary',
      },
    ];

    if (document.syncFrequency) {
      actions.push({
        icon: SyncIcon,
        label: t('settings.documents.sync'),
        onClick: () => {
          setSyncMenuState({
            isOpen: true,
            docId: document.id ?? null,
            document: document,
          });
        },
        iconWidth: 14,
        iconHeight: 14,
        variant: 'primary',
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
      variant: 'danger',
    });

    return actions;
  };
  useEffect(() => {
    refreshDocs(undefined, 1, rowsPerPage);
  }, [searchTerm]);

  return showDocumentChunks ? (
    <DocumentChunks
      document={showDocumentChunks}
      handleGoBack={() => {
        setShowDocumentChunks(undefined);
      }}
    />
  ) : (
    <div className="mt-8 flex w-full max-w-full flex-col overflow-hidden">
      <div className="relative flex grow flex-col">
        <div className="mb-6">
          <h2 className="text-sonic-silver text-base font-medium">
            {t('settings.documents.title')}
          </h2>
        </div>
        <div className="mb-6 flex flex-col items-start justify-between gap-3 sm:flex-row sm:items-center">
          <div className="w-full sm:w-auto">
            <label htmlFor="document-search-input" className="sr-only">
              {t('settings.documents.searchPlaceholder')}
            </label>
            <Input
              maxLength={256}
              placeholder={t('settings.documents.searchPlaceholder')}
              name="Document-search-input"
              type="text"
              id="document-search-input"
              value={searchTerm}
              onChange={(e) => {
                setSearchTerm(e.target.value);
                setCurrentPage(1);
              }}
              borderVariant="thin"
            />
          </div>
          <button
            className="bg-purple-30 hover:bg-violets-are-blue flex h-[32px] min-w-[108px] items-center justify-center rounded-full px-4 text-sm whitespace-normal text-white"
            title={t('settings.documents.addNew')}
            onClick={() => {
              setIsOnboarding(false);
              setModalState('ACTIVE');
            }}
          >
            {t('settings.documents.addNew')}
          </button>
        </div>
        <div className="relative w-full">
          <div className="dark:border-silver/40 overflow-hidden rounded-md border border-gray-300">
            <div className="table-scroll overflow-x-auto">
              <table className="w-full table-auto">
                <thead>
                  <tr className="dark:border-silver/40 border-b border-gray-300">
                    <th className="text-sonic-silver w-[45%] px-4 py-3 text-left text-xs font-medium">
                      {t('settings.documents.name')}
                    </th>
                    <th className="text-sonic-silver w-[30%] px-4 py-3 text-left text-xs font-medium">
                      <div className="flex items-center justify-start">
                        {t('settings.documents.date')}
                        <img
                          className="ml-2 cursor-pointer"
                          onClick={() => refreshDocs('date')}
                          src={caretSort}
                          alt="sort"
                        />
                      </div>
                    </th>
                    <th className="text-sonic-silver w-[15%] px-4 py-3 text-left text-xs font-medium">
                      <div className="flex items-center justify-start">
                        <span className="hidden sm:inline">
                          {t('settings.documents.tokenUsage')}
                        </span>
                        <span className="sm:hidden">
                          {t('settings.documents.tokenUsage')}
                        </span>
                        <img
                          className="ml-2 cursor-pointer"
                          onClick={() => refreshDocs('tokens')}
                          src={caretSort}
                          alt="sort"
                        />
                      </div>
                    </th>
                    <th className="sr-only w-[10%] px-4 py-3">
                      {t('settings.documents.actions')}
                    </th>
                  </tr>
                </thead>
                <tbody className="dark:divide-silver/40 divide-y divide-gray-300">
                  {loading ? (
                    <SkeletonLoader component="table" />
                  ) : !currentDocuments?.length ? (
                    <tr>
                      <td
                        colSpan={4}
                        className="bg-transparent py-4 text-center text-gray-700 dark:text-neutral-200"
                      >
                        {t('settings.documents.noData')}
                      </td>
                    </tr>
                  ) : (
                    currentDocuments.map((document, index) => {
                      const docId = document.id ? document.id.toString() : '';

                      return (
                        <tr key={docId} className="group transition-colors">
                          <td
                            className="max-w-0 min-w-48 truncate px-4 py-4 text-sm font-semibold text-gray-700 group-hover:bg-gray-50 dark:text-[#E0E0E0] dark:group-hover:bg-gray-800/50"
                            title={document.name}
                          >
                            {document.name}
                          </td>
                          <td className="px-4 py-4 text-sm whitespace-nowrap text-gray-700 group-hover:bg-gray-50 dark:text-[#E0E0E0] dark:group-hover:bg-gray-800/50">
                            {document.date ? formatDate(document.date) : ''}
                          </td>
                          <td className="px-4 py-4 text-sm whitespace-nowrap text-gray-700 group-hover:bg-gray-50 dark:text-[#E0E0E0] dark:group-hover:bg-gray-800/50">
                            {document.tokens
                              ? formatTokens(+document.tokens)
                              : ''}
                          </td>
                          <td
                            className="px-4 py-4 text-right group-hover:bg-gray-50 dark:group-hover:bg-gray-800/50"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <div
                              ref={getMenuRef(docId)}
                              className="relative flex items-center justify-end gap-3"
                            >
                              {document.syncFrequency && (
                                <DropdownMenu
                                  name={t('settings.documents.sync')}
                                  options={syncOptions}
                                  onSelect={(value: string) => {
                                    handleManageSync(document, value);
                                  }}
                                  defaultValue={document.syncFrequency}
                                  icon={SyncIcon}
                                  isOpen={
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
                                  anchorRef={getMenuRef(docId)}
                                  position="bottom-left"
                                  offset={{ x: 24, y: -24 }}
                                  className="min-w-[120px]"
                                />
                              )}
                              <button
                                onClick={(e) => handleMenuClick(e, docId)}
                                className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full transition-colors hover:bg-gray-100 dark:hover:bg-gray-700"
                                aria-label="Open menu"
                                data-testid={`menu-button-${docId}`}
                              >
                                <img
                                  src={ThreeDots}
                                  alt={t('convTile.menu')}
                                  className="h-4 w-4 opacity-60 hover:opacity-100"
                                />
                              </button>
                              <ContextMenu
                                isOpen={activeMenuId === docId}
                                setIsOpen={(isOpen) => {
                                  setActiveMenuId(isOpen ? docId : null);
                                }}
                                options={getActionOptions(index, document)}
                                anchorRef={getMenuRef(docId)}
                                position="bottom-left"
                                offset={{ x: 48, y: 0 }}
                                className="z-50"
                              />
                            </div>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>

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
          message={t('settings.documents.deleteWarning', {
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
    </div>
  );
}

function DocumentChunks({
  document,
  handleGoBack,
}: {
  document: Doc;
  handleGoBack: () => void;
}) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const [isDarkTheme] = useDarkTheme();
  const [paginatedChunks, setPaginatedChunks] = useState<ChunkType[]>([]);
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(5);
  const [totalChunks, setTotalChunks] = useState(0);
  const [loading, setLoading] = useLoaderState(true);
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [addModal, setAddModal] = useState<ActiveState>('INACTIVE');
  const [editModal, setEditModal] = useState<{
    state: ActiveState;
    chunk: ChunkType | null;
  }>({ state: 'INACTIVE', chunk: null });

  const fetchChunks = () => {
    setLoading(true);
    try {
      userService
        .getDocumentChunks(document.id ?? '', page, perPage, token)
        .then((response) => {
          if (!response.ok) {
            setLoading(false);
            setPaginatedChunks([]);
            throw new Error('Failed to fetch chunks data');
          }
          return response.json();
        })
        .then((data) => {
          setPage(data.page);
          setPerPage(data.per_page);
          setTotalChunks(data.total);
          setPaginatedChunks(data.chunks);
          setLoading(false);
        });
    } catch (e) {
      console.log(e);
      setLoading(false);
    }
  };

  const handleAddChunk = (title: string, text: string) => {
    try {
      userService
        .addChunk(
          {
            id: document.id ?? '',
            text: text,
            metadata: {
              title: title,
            },
          },
          token,
        )
        .then((response) => {
          if (!response.ok) {
            throw new Error('Failed to add chunk');
          }
          fetchChunks();
        });
    } catch (e) {
      console.log(e);
    }
  };

  const handleUpdateChunk = (title: string, text: string, chunk: ChunkType) => {
    try {
      userService
        .updateChunk(
          {
            id: document.id ?? '',
            chunk_id: chunk.doc_id,
            text: text,
            metadata: {
              title: title,
            },
          },
          token,
        )
        .then((response) => {
          if (!response.ok) {
            throw new Error('Failed to update chunk');
          }
          fetchChunks();
        });
    } catch (e) {
      console.log(e);
    }
  };

  const handleDeleteChunk = (chunk: ChunkType) => {
    try {
      userService
        .deleteChunk(document.id ?? '', chunk.doc_id, token)
        .then((response) => {
          if (!response.ok) {
            throw new Error('Failed to delete chunk');
          }
          setEditModal({ state: 'INACTIVE', chunk: null });
          fetchChunks();
        });
    } catch (e) {
      console.log(e);
    }
  };

  React.useEffect(() => {
    fetchChunks();
  }, [page, perPage]);
  return (
    <div className="mt-8 flex flex-col">
      <div className="text-eerie-black dark:text-bright-gray mb-3 flex items-center gap-3 text-sm">
        <button
          className="rounded-full border p-3 text-sm text-gray-400 dark:border-0 dark:bg-[#28292D] dark:text-gray-500 dark:hover:bg-[#2E2F34]"
          onClick={handleGoBack}
        >
          <img src={ArrowLeft} alt="left-arrow" className="h-3 w-3" />
        </button>
        <p className="mt-px">{t('settings.documents.backToAll')}</p>
      </div>
      <div className="my-3 flex items-center justify-between gap-1">
        <div className="text-eerie-black dark:text-bright-gray flex w-full items-center gap-2 sm:w-auto">
          <p className="hidden text-2xl font-semibold sm:flex">{`${totalChunks} ${t('settings.documents.chunks')}`}</p>
          <label htmlFor="chunk-search-input" className="sr-only">
            {t('settings.documents.searchPlaceholder')}
          </label>
          <Input
            maxLength={256}
            placeholder={t('settings.documents.searchPlaceholder')}
            name="chunk-search-input"
            type="text"
            id="chunk-search-input"
            value={searchTerm}
            onChange={(e) => {
              setSearchTerm(e.target.value);
            }}
            borderVariant="thin"
          />
        </div>
        <button
          className="bg-purple-30 hover:bg-violets-are-blue flex h-[32px] min-w-[108px] items-center justify-center rounded-full px-4 text-sm whitespace-normal text-white"
          title={t('settings.documents.addNew')}
          onClick={() => setAddModal('ACTIVE')}
        >
          {t('settings.documents.addNew')}
        </button>
      </div>
      {loading ? (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
          <div className="col-span-2 mt-24 flex h-32 items-center justify-center lg:col-span-3">
            <Spinner />
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {paginatedChunks.filter((chunk) => {
            if (!chunk.metadata?.title) return true;
            return chunk.metadata.title
              .toLowerCase()
              .includes(searchTerm.toLowerCase());
          }).length === 0 ? (
            <div className="col-span-2 mt-24 text-center text-gray-500 lg:col-span-3 dark:text-gray-400">
              <img
                src={isDarkTheme ? NoFilesDarkIcon : NoFilesIcon}
                alt={t('settings.documents.noChunksAlt')}
                className="mx-auto mb-2 h-24 w-24"
              />
              {t('settings.documents.noChunks')}
            </div>
          ) : (
            paginatedChunks
              .filter((chunk) => {
                if (!chunk.metadata?.title) return true;
                return chunk.metadata.title
                  .toLowerCase()
                  .includes(searchTerm.toLowerCase());
              })
              .map((chunk, index) => (
                <div
                  key={index}
                  className="border-silver dark:border-silver/40 relative flex h-56 w-full flex-col justify-between rounded-2xl border p-6"
                >
                  <div className="w-full">
                    <div className="flex w-full items-center justify-between">
                      <button
                        aria-label={'edit'}
                        onClick={() => {
                          setEditModal({
                            state: 'ACTIVE',
                            chunk: chunk,
                          });
                        }}
                        className="absolute top-3 right-3 h-4 w-4 cursor-pointer"
                      >
                        <img
                          alt={'edit'}
                          src={Edit}
                          className="opacity-60 hover:opacity-100"
                        />
                      </button>
                    </div>
                    <div className="mt-[9px]">
                      <p className="ellipsis-text text-eerie-black h-12 text-sm leading-relaxed font-semibold break-words dark:text-[#EEEEEE]">
                        {chunk.metadata?.title ?? 'Untitled'}
                      </p>
                      <p className="mt-1 h-[110px] overflow-y-auto pr-1 text-[13px] leading-relaxed break-words text-gray-600 dark:text-gray-400">
                        {chunk.text}
                      </p>
                    </div>
                  </div>
                </div>
              ))
          )}
        </div>
      )}
      {!loading &&
        paginatedChunks.filter((chunk) => {
          if (!chunk.metadata?.title) return true;
          return chunk.metadata.title
            .toLowerCase()
            .includes(searchTerm.toLowerCase());
        }).length !== 0 && (
          <div className="mt-10 flex w-full items-center justify-center">
            <Pagination
              currentPage={page}
              totalPages={Math.ceil(totalChunks / perPage)}
              rowsPerPage={perPage}
              onPageChange={(page) => {
                setPage(page);
              }}
              onRowsPerPageChange={(rows) => {
                setPerPage(rows);
                setPage(1);
              }}
            />
          </div>
        )}
      <ChunkModal
        type="ADD"
        modalState={addModal}
        setModalState={setAddModal}
        handleSubmit={handleAddChunk}
      />
      {editModal.chunk && (
        <ChunkModal
          type="EDIT"
          modalState={editModal.state}
          setModalState={(state) =>
            setEditModal((prev) => ({ ...prev, state }))
          }
          handleSubmit={(title, text) => {
            handleUpdateChunk(title, text, editModal.chunk as ChunkType);
          }}
          originalText={editModal.chunk?.text ?? ''}
          originalTitle={editModal.chunk?.metadata?.title ?? ''}
          handleDelete={() => {
            handleDeleteChunk(editModal.chunk as ChunkType);
          }}
        />
      )}
    </div>
  );
}
