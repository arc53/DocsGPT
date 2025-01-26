import React, { useState, useEffect, useCallback } from 'react';
import PropTypes from 'prop-types';
import userService from '../api/services/userService';
import SyncIcon from '../assets/sync.svg';
import Trash from '../assets/trash.svg';
import caretSort from '../assets/caret-sort.svg';
import DropdownMenu from '../components/DropdownMenu';
import SkeletonLoader from '../components/SkeletonLoader';
import Input from '../components/Input';
import Upload from '../upload/Upload'; // Import the Upload component
import Pagination from '../components/DocumentPagination';
import { useTranslation } from 'react-i18next';
import { useDispatch } from 'react-redux';
import { Doc, DocumentsProps, ActiveState } from '../models/misc'; // Ensure ActiveState type is imported
import { getDocs, getDocsWithPagination } from '../preferences/preferenceApi';
import { setSourceDocs } from '../preferences/preferenceSlice';
import { setPaginatedDocuments } from '../preferences/preferenceSlice';
import { formatDate } from '../utils/dateTimeUtils';

// Utility function to format numbers
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

const Documents: React.FC<DocumentsProps> = ({
  paginatedDocuments,
  handleDeleteDocument,
}) => {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  // State for search input
  const [searchTerm, setSearchTerm] = useState<string>('');
  // State for modal: active/inactive
  const [modalState, setModalState] = useState<ActiveState>('INACTIVE'); // Initialize with inactive state
  const [isOnboarding, setIsOnboarding] = useState<boolean>(false); // State for onboarding flag
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

  useEffect(() => {
    refreshDocs(undefined, 1, rowsPerPage);
  }, [searchTerm]);

  return (
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
            <div className="border rounded-md border-silver dark:border-silver/40">
              <table className="w-full min-w-[640px] table-auto">
                <thead>
                  <tr className="border-b border-silver dark:border-silver/40">
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
                <tbody className="divide-y divide-silver dark:divide-silver/40">
                  {!currentDocuments?.length ? (
                    <tr>
                      <td
                        colSpan={4}
                        className="py-4 text-center text-gray-700 dark:text-[#E0E0E0] bg-white dark:bg-transparent"
                      >
                        {t('settings.documents.noData')}
                      </td>
                    </tr>
                  ) : (
                    currentDocuments.map((document, index) => (
                      <tr key={index} className="bg-white dark:bg-transparent">
                        <td
                          className="py-4 px-4 text-sm text-gray-700 dark:text-[#E0E0E0] w-[45%] truncate"
                          title={document.name}
                        >
                          {document.name}
                        </td>
                        <td className="py-4 px-4 text-center text-sm text-gray-700 dark:text-[#E0E0E0] whitespace-nowrap w-[20%]">
                          {document.date ? formatDate(document.date) : ''}
                        </td>
                        <td className="py-4 px-4 text-center text-sm text-gray-700 dark:text-[#E0E0E0] whitespace-nowrap w-[25%]">
                          {document.tokens
                            ? formatTokens(+document.tokens)
                            : ''}
                        </td>
                        <td className="py-4 px-4 text-right w-[10%]">
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
                                handleDeleteDocument(index, document);
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
    </div>
  );
};

Documents.propTypes = {
  //documents: PropTypes.array.isRequired,
  handleDeleteDocument: PropTypes.func.isRequired,
};

export default Documents;
