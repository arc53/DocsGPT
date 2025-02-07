import React, { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch } from 'react-redux';

import userService from '../api/services/userService';
import ArrowLeft from '../assets/arrow-left.svg';
import caretSort from '../assets/caret-sort.svg';
import NoFilesDarkIcon from '../assets/no-files-dark.svg';
import NoFilesIcon from '../assets/no-files.svg';
import SyncIcon from '../assets/sync.svg';
import Trash from '../assets/trash.svg';
import Pagination from '../components/DocumentPagination';
import DropdownMenu from '../components/DropdownMenu';
import Input from '../components/Input';
import SkeletonLoader from '../components/SkeletonLoader';
import { useDarkTheme } from '../hooks';
import AddChunkModal from '../modals/AddChunkModal';
import ConfirmationModal from '../modals/ConfirmationModal';
import { ActiveState, Doc, DocumentsProps } from '../models/misc';
import { getDocs, getDocsWithPagination } from '../preferences/preferenceApi';
import {
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

  const [searchTerm, setSearchTerm] = useState<string>('');
  const [modalState, setModalState] = useState<ActiveState>('INACTIVE');
  const [isOnboarding, setIsOnboarding] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(false);
  const [sortField, setSortField] = useState<'date' | 'tokens'>('date');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  // Pagination
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [rowsPerPage, setRowsPerPage] = useState<number>(10);
  const [totalPages, setTotalPages] = useState<number>(1);
  const currentDocuments = paginatedDocuments ?? [];
  const syncOptions = [
    { label: t('settings.documents.syncFrequency.never'), value: 'never' },
    { label: t('settings.documents.syncFrequency.daily'), value: 'daily' },
    { label: t('settings.documents.syncFrequency.weekly'), value: 'weekly' },
    { label: t('settings.documents.syncFrequency.monthly'), value: 'monthly' },
  ];
  const [showDocumentChunks, setShowDocumentChunks] = useState<Doc>();

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
      .manageSync({ source_id: doc.id, sync_frequency })
      .then(() => {
        return getDocs();
      })
      .then((data) => {
        dispatch(setSourceDocs(data));
        return getDocsWithPagination(
          sortField,
          sortOrder,
          currentPage,
          rowsPerPage,
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
    <div className="flex flex-col mt-8">
      <div className="flex flex-col relative flex-grow">
        <div className="mb-6">
          <h2 className="text-base font-medium text-sonic-silver">
            {t('settings.documents.title')}
          </h2>
        </div>
        <div className="my-3 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
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
            className="rounded-full w-full sm:w-40 bg-purple-30 px-4 py-3 text-white hover:bg-[#6F3FD1]"
            title={t('settings.documents.addNew')}
            onClick={() => {
              setIsOnboarding(false);
              setModalState('ACTIVE');
            }}
          >
            {t('settings.documents.addNew')}
          </button>
        </div>

        {loading ? (
          <SkeletonLoader count={1} />
        ) : (
          <div className="flex flex-col flex-grow">
            {' '}
            {/* Removed overflow-auto */}
            <div className="border rounded-md border-gray-300 dark:border-silver/40 overflow-hidden">
              <table className="w-full min-w-[640px] table-auto">
                <thead>
                  <tr className="border-b border-gray-300 dark:border-silver/40">
                    <th className="py-3 px-4 text-left text-xs font-medium text-sonic-silver uppercase w-[45%]">
                      {t('settings.documents.name')}
                    </th>
                    <th className="py-3 px-4 text-center text-xs font-medium text-sonic-silver uppercase w-[20%]">
                      <div className="flex justify-center items-center">
                        {t('settings.documents.date')}
                        <img
                          className="cursor-pointer ml-2"
                          onClick={() => refreshDocs('date')}
                          src={caretSort}
                          alt="sort"
                        />
                      </div>
                    </th>
                    <th className="py-3 px-4 text-center text-xs font-medium text-sonic-silver uppercase w-[25%]">
                      <div className="flex justify-center items-center">
                        <span className="hidden sm:inline">
                          {t('settings.documents.tokenUsage')}
                        </span>
                        <span className="sm:hidden">
                          {t('settings.documents.tokenUsage')}
                        </span>
                        <img
                          className="cursor-pointer ml-2"
                          onClick={() => refreshDocs('tokens')}
                          src={caretSort}
                          alt="sort"
                        />
                      </div>
                    </th>
                    <th className="py-3 px-4 text-right text-xs font-medium text-gray-700 dark:text-[#E0E0E0] uppercase w-[10%]">
                      <span className="sr-only">
                        {t('settings.documents.actions')}
                      </span>
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-300 dark:divide-silver/40">
                  {!currentDocuments?.length ? (
                    <tr>
                      <td
                        colSpan={4}
                        className="py-4 text-center text-gray-700 dark:text-[#E0E0E] bg-transparent"
                      >
                        {t('settings.documents.noData')}
                      </td>
                    </tr>
                  ) : (
                    currentDocuments.map((document, index) => (
                      <tr
                        key={index}
                        className="group transition-colors"
                        onClick={() => setShowDocumentChunks(document)}
                      >
                        <td
                          className="py-4 px-4 text-sm text-gray-700 dark:text-[#E0E0E0] w-[45%] truncate group-hover:bg-gray-50 dark:group-hover:bg-gray-800/50"
                          title={document.name}
                        >
                          {document.name}
                        </td>
                        <td className="py-4 px-4 text-center text-sm text-gray-700 dark:text-[#E0E0E0] whitespace-nowrap w-[20%] group-hover:bg-gray-50 dark:group-hover:bg-gray-800/50">
                          {document.date ? formatDate(document.date) : ''}
                        </td>
                        <td className="py-4 px-4 text-center text-sm text-gray-700 dark:text-[#E0E0E0] whitespace-nowrap w-[25%] group-hover:bg-gray-50 dark:group-hover:bg-gray-800/50">
                          {document.tokens
                            ? formatTokens(+document.tokens)
                            : ''}
                        </td>
                        <td className="py-4 px-4 text-right w-[10%] group-hover:bg-gray-50 dark:group-hover:bg-gray-800/50">
                          <div className="flex items-center justify-end gap-3">
                            {!document.syncFrequency && (
                              <div className="w-8"></div>
                            )}
                            {document.syncFrequency && (
                              <DropdownMenu
                                name={t('settings.documents.sync')}
                                options={syncOptions}
                                onSelect={(value: string) => {
                                  handleManageSync(document, value);
                                }}
                                defaultValue={document.syncFrequency}
                                icon={SyncIcon}
                              />
                            )}
                            <button
                              onClick={(event) => {
                                event.stopPropagation();
                                handleDeleteConfirmation(index, document);
                              }}
                              className="inline-flex items-center justify-center w-8 h-8 rounded-full hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors flex-shrink-0"
                            >
                              <img
                                src={Trash}
                                alt={t('convTile.delete')}
                                className="h-4 w-4 opacity-60 hover:opacity-100"
                              />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}
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
  const [isDarkTheme] = useDarkTheme();
  const [paginatedChunks, setPaginatedChunks] = useState<ChunkType[]>([]);
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(5);
  const [totalChunks, setTotalChunks] = useState(0);
  const [loading, setLoading] = useState(false);
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [modalState, setModalState] = useState<ActiveState>('INACTIVE');

  const fetchChunks = () => {
    setLoading(true);
    try {
      userService
        .getDocumentChunks(document.id ?? '', page, perPage)
        .then((response) => {
          if (!response.ok) {
            throw new Error('Failed to fetch chunks data');
          }
          return response.json();
        })
        .then((data) => {
          setPage(data.page);
          setPerPage(data.per_page);
          setTotalChunks(data.total);
          setPaginatedChunks(data.chunks);
        });
    } catch (e) {
      console.log(e);
    } finally {
      setLoading(false);
    }
  };

  const handleAddChunk = (title: string, text: string) => {
    try {
      userService
        .addChunk({
          id: document.id ?? '',
          text: text,
          metadata: {
            title: title,
          },
        })
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

  React.useEffect(() => {
    fetchChunks();
  }, [page, perPage]);
  return (
    <div className="flex flex-col mt-8">
      <div className="mb-3 flex items-center gap-3 text-eerie-black dark:text-bright-gray text-sm">
        <button
          className="text-sm text-gray-400 dark:text-gray-500 border dark:border-0 dark:bg-[#28292D] dark:hover:bg-[#2E2F34] p-3 rounded-full"
          onClick={handleGoBack}
        >
          <img src={ArrowLeft} alt="left-arrow" className="w-3 h-3" />
        </button>
        <p className="mt-px">Back to all documents</p>
      </div>
      <div className="my-3 flex justify-between items-center gap-1">
        <div className="w-full sm:w-auto">
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
          className="rounded-full w-full sm:w-40 bg-purple-30 px-4 py-3 text-white hover:bg-[#6F3FD1]"
          title={t('settings.documents.addNew')}
          onClick={() => setModalState('ACTIVE')}
        >
          {t('settings.documents.addNew')}
        </button>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
        {paginatedChunks.filter((chunk) =>
          chunk.metadata?.title
            .toLowerCase()
            .includes(searchTerm.toLowerCase()),
        ).length === 0 ? (
          <div className="mt-24 col-span-2 lg:col-span-3 text-center text-gray-500 dark:text-gray-400">
            <img
              src={isDarkTheme ? NoFilesDarkIcon : NoFilesIcon}
              alt="No tools found"
              className="h-24 w-24 mx-auto mb-2"
            />
            No chunks found
          </div>
        ) : (
          paginatedChunks
            .filter((chunk) =>
              chunk.metadata?.title
                .toLowerCase()
                .includes(searchTerm.toLowerCase()),
            )
            .map((chunk, index) => (
              <div
                key={index}
                className="relative h-56 w-full p-6 border rounded-2xl border-silver dark:border-silver/40 flex flex-col justify-between"
              >
                <div className="w-full">
                  <div className="mt-[9px]">
                    <p className="h-12 text-sm font-semibold text-eerie-black dark:text-[#EEEEEE] leading-relaxed break-words ellipsis-text">
                      {chunk.metadata?.title}
                    </p>
                    <p className="mt-1 pr-1 h-[110px] overflow-y-auto text-[13px] text-gray-600 dark:text-gray-400 leading-relaxed break-words">
                      {chunk.text}
                    </p>
                  </div>
                </div>
              </div>
            ))
        )}
      </div>
      <div className="mt-10 w-full flex items-center justify-center">
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
      <AddChunkModal
        modalState={modalState}
        setModalState={setModalState}
        handleSubmit={handleAddChunk}
      />
    </div>
  );
}
