import React, { useState, useEffect } from 'react';
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
    { label: 'Never', value: 'never' },
    { label: 'Daily', value: 'daily' },
    { label: 'Weekly', value: 'weekly' },
    { label: 'Monthly', value: 'monthly' },
  ];

  const refreshDocs = (
    field: 'date' | 'tokens' | undefined,
    pageNumber?: number,
    rows?: number,
  ) => {
    const page = pageNumber ?? currentPage;
    const rowsPerPg = rows ?? rowsPerPage;

    if (field !== undefined) {
      if (field === sortField) {
        // Toggle sort order
        setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
      } else {
        // Change sort field and reset order to 'desc'
        setSortField(field);
        setSortOrder('desc');
      }
    }
    getDocsWithPagination(sortField, sortOrder, page, rowsPerPg, searchTerm)
      .then((data) => {
        dispatch(setPaginatedDocuments(data ? data.docs : []));
        setTotalPages(data ? data.totalPages : 0);
      })
      .catch((error) => console.error(error))
      .finally(() => {
        setLoading(false);
      });
  };

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
  }, [modalState, sortField, currentPage, rowsPerPage]);

  useEffect(() => {
    refreshDocs(sortField, 1, rowsPerPage);
  }, [searchTerm]);

  return (
    <div className="mt-8">
      <div className="flex flex-col relative">
        <div className="z-10 w-full overflow-x-auto">
          <div className="my-3 flex justify-between items-center">
            <div className="p-1">
              <Input
                maxLength={256}
                placeholder="Search..."
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
              onClick={() => {
                setIsOnboarding(false); // Set onboarding flag if needed
                setModalState('ACTIVE'); // Open the upload modal
              }}
            >
              Add New
            </button>
          </div>
          {loading ? (
            <SkeletonLoader count={1} />
          ) : (
            <div className="flex flex-col">
              <div className="flex-grow">
                <div className="dark:border-silver/40 border-silver rounded-xl border overflow-auto">
                  <table className="min-w-full divide-y divide-gray-200 ">
                    <thead>
                      <tr>
                        <th className="px-5 py-3 text-start text-sm font-medium text-gray-700 dark:text-gray-50 uppercase">
                          {t('settings.documents.name')}
                        </th>
                        <th className="px-5 py-3 text-start text-sm font-medium text-gray-700 dark:text-gray-50 uppercase">
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
                        <th className="px-5 py-2 text-start text-sm font-medium text-gray-700 dark:text-gray-50 uppercase">
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
                          className="px-6 py-2 text-start text-xs font-medium text-gray-700 dark:text-gray-50 uppercase"
                        ></th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-200 dark:divide-neutral-700">
                      {!currentDocuments?.length && (
                        <tr>
                          <td colSpan={5} className="!p-4">
                            {t('settings.documents.noData')}
                          </td>
                        </tr>
                      )}
                      {Array.isArray(currentDocuments) &&
                        currentDocuments.map((document, index) => (
                          <tr key={index} className="text-nowrap font-normal">
                            <td className="px-6 py-4 whitespace-nowrap text-left text-sm font-medium text-gray-800 dark:text-neutral-200">
                              {document.name}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-center text-sm font-medium text-gray-800 dark:text-neutral-200">
                              {document.date}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-center text-sm font-medium text-gray-800 dark:text-neutral-200">
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
                                    alt="Delete"
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
                                      name="Sync"
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
                <div className="mt-4">
                  <Pagination
                    currentPage={currentPage}
                    totalPages={totalPages}
                    rowsPerPage={rowsPerPage}
                    onPageChange={(page) => {
                      setCurrentPage(page);
                      refreshDocs(sortField, page, rowsPerPage);
                    }}
                    onRowsPerPageChange={(rows) => {
                      setRowsPerPage(rows);
                      setCurrentPage(1);
                      refreshDocs(sortField, 1, rows);
                    }}
                  />
                </div>
              </div>
            </div>
          )}
        </div>
        {/* Conditionally render the Upload modal based on modalState */}
        {modalState === 'ACTIVE' && (
          <div className="fixed top-0 left-0 w-screen h-screen z-50 flex items-center justify-center bg-transparent">
            <div className="w-full h-full bg-transparent flex flex-col items-center justify-center p-8">
              {/* Your Upload component */}
              <Upload
                modalState={modalState}
                setModalState={setModalState}
                isOnboarding={isOnboarding}
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
