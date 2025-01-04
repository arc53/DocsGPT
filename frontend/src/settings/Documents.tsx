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
import { truncate } from '../utils/stringUtils';

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
        // First, fetch the updated source docs
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
    if (modalState === 'INACTIVE') {
      refreshDocs(sortField, currentPage, rowsPerPage);
    }
  }, [modalState]);

  useEffect(() => {
    // undefine to prevent reset the sort order
    refreshDocs(undefined, 1, rowsPerPage);
  }, [searchTerm]);

  return (
    <div className="mt-8">
      <div className="flex flex-col relative">
        <div className="z-10 w-full overflow-x-auto">
          <div className="my-3 flex justify-between items-center">
            <div className="p-1">
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
                  // refreshDocs(sortField, 1, rowsPerPage);
                  // do not call refreshDocs here the state is async
                  // so it will not have the updated value
                }} // Handle search input change
              />
            </div>
            <button
              className="rounded-full w-40 bg-purple-30 px-4 py-3 text-white hover:bg-[#6F3FD1]"
              title={t('settings.documents.addNewTitle')}
              onClick={() => {
                setIsOnboarding(false); // Set onboarding flag if needed
                setModalState('ACTIVE'); // Open the upload modal
              }}
            >
              {t('settings.documents.addNew')}
            </button>
          </div>
          {loading ? (
            <SkeletonLoader count={1} />
          ) : (
            <div className="flex flex-col">
              <div className="flex-grow">
                <div className="dark:border-silver/40 border-silver rounded-md border overflow-auto">
                  <table className="min-w-full divide-y divide-silver dark:divide-silver/40 text-xs sm:text-sm ">
                    <thead>
                      <tr className="text-nowrap">
                        <th className="px-5 py-3 text-start font-medium text-gray-700 dark:text-gray-50 uppercase w-96">
                          {t('settings.documents.name')}
                        </th>
                        <th className="px-5 py-3 text-start font-medium text-gray-700 dark:text-gray-50 uppercase">
                          <div className="flex justify-center items-center">
                            {t('settings.documents.date')}
                            <img
                              className="cursor-pointer"
                              onClick={() => refreshDocs('date')}
                              src={caretSort}
                              alt="sort"
                            />
                          </div>
                        </th>
                        <th
                          scope="col"
                          className="px-5 py-2 text-center font-medium text-gray-700 dark:text-gray-50 uppercase"
                        >
                          <div className="flex justify-center items-center">
                            {t('settings.documents.tokenUsage')}
                            <img
                              className="cursor-pointer"
                              onClick={() => refreshDocs('tokens')}
                              src={caretSort}
                              alt="sort"
                            />
                          </div>
                        </th>
                        {/*}
                        <th className="px-5 py-2 text-start text-sm font-medium text-gray-700 dark:text-gray-50 uppercase">
                          <div className="flex justify-center items-center">
                            {t('settings.documents.type')}
                          </div>
                        </th>
                        */}
                        <th
                          scope="col"
                          className="px-6 py-2 text-start font-medium text-gray-700 dark:text-gray-50 uppercase"
                        >
                          {' '}
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-200 dark:divide-neutral-700">
                      {!currentDocuments?.length && (
                        <tr>
                          <td
                            colSpan={4}
                            className="!py-4 text-gray-800 dark:text-neutral-200 text-center"
                          >
                            {t('settings.documents.noData')}
                          </td>
                        </tr>
                      )}
                      {Array.isArray(currentDocuments) &&
                        currentDocuments.map((document, index) => (
                          <tr key={index} className="text-nowrap font-normal">
                            <td
                              title={document.name}
                              className="px-6 py-4 whitespace-nowrap text-left font-medium text-gray-800 dark:text-neutral-200"
                            >
                              {truncate(document.name, 50)}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-center font-medium text-gray-800 dark:text-neutral-200">
                              {document.date}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-center font-medium text-gray-800 dark:text-neutral-200">
                              {document.tokens
                                ? formatTokens(+document.tokens)
                                : ''}
                            </td>
                            {/*}
                            <td className="px-6 py-4 whitespace-nowrap text-center text-sm font-medium text-gray-800 dark:text-neutral-200">
                              {document.type === 'remote'
                                ? 'Pre-loaded'
                                : 'Private'}
                            </td>
                            */}
                            <td className="px-6 py-4 whitespace-nowrap text-left text-sm font-medium flex">
                              <div className="min-w-[150px] flex flex-row items-center ml-auto gap-10">
                                {document.type !== 'remote' && (
                                  <img
                                    src={Trash}
                                    alt={t('convTile.delete')}
                                    className="h-4 w-4 cursor-pointer opacity-60 hover:opacity-100"
                                    id={`img-${index}`}
                                    onClick={(event) => {
                                      event.stopPropagation();
                                      handleDeleteDocument(index, document);
                                    }}
                                  />
                                )}
                                {document.syncFrequency && (
                                  <div className="ml-2">
                                    <DropdownMenu
                                      name={t('settings.documents.sync')}
                                      options={syncOptions}
                                      onSelect={(value: string) => {
                                        handleManageSync(document, value);
                                      }}
                                      defaultValue={document.syncFrequency}
                                      icon={SyncIcon}
                                    />
                                  </div>
                                )}
                              </div>
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}
        </div>
        {/* outside scrollable area */}
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

        {/* Conditionally render the Upload modal based on modalState */}
        {modalState === 'ACTIVE' && (
          <div className="fixed top-0 left-0 w-screen h-screen z-50 flex items-center justify-center bg-transparent">
            <div className="w-full h-full bg-transparent flex flex-col items-center justify-center p-8">
              {/* Your Upload component */}
              <Upload
                receivedFile={[]}
                setModalState={setModalState}
                isOnboarding={isOnboarding}
                renderTab={null}
                close={() => setModalState('INACTIVE')}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

Documents.propTypes = {
  //documents: PropTypes.array.isRequired,
  handleDeleteDocument: PropTypes.func.isRequired,
};

export default Documents;
