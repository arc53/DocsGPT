import React, { useState, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { selectToken } from '../preferences/preferenceSlice';
import { ActiveState } from '../models/misc';
import Chunks from './Chunks';
import SkeletonLoader from './SkeletonLoader';
import ConfirmationModal from '../modals/ConfirmationModal';
import userService from '../api/services/userService';
import FileIcon from '../assets/file.svg';
import FolderIcon from '../assets/folder.svg';
import ArrowLeft from '../assets/arrow-left.svg';
import { useOutsideAlerter, useLoaderState } from '../hooks';
import {
  Table,
  TableContainer,
  TableHead,
  TableBody,
  TableRow,
  TableHeader,
  TableCell,
} from './Table';

interface FileNode {
  type?: string;
  token_count?: number;
  size_bytes?: number;
  [key: string]: any;
}

interface DirectoryStructure {
  [key: string]: FileNode;
}

interface ConnectorTreeProps {
  docId: string;
  sourceName: string;
  onBackToDocuments: () => void;
}

interface SearchResult {
  name: string;
  path: string;
  isFile: boolean;
}

const ConnectorTree: React.FC<ConnectorTreeProps> = ({
  docId,
  sourceName,
  onBackToDocuments,
}) => {
  const { t } = useTranslation();
  const [loading, setLoading] = useLoaderState(true, 500);
  const [error, setError] = useState<string | null>(null);
  const [directoryStructure, setDirectoryStructure] =
    useState<DirectoryStructure | null>(null);
  const [currentPath, setCurrentPath] = useState<string[]>([]);
  const token = useSelector(selectToken);
  const [activeMenuId, setActiveMenuId] = useState<string | null>(null);
  const menuRefs = useRef<{
    [key: string]: React.RefObject<HTMLDivElement | null>;
  }>({});
  const [selectedFile, setSelectedFile] = useState<{
    id: string;
    name: string;
  } | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const searchDropdownRef = useRef<HTMLDivElement>(null);
  const [isSyncing, setIsSyncing] = useState<boolean>(false);
  const [syncProgress, setSyncProgress] = useState<number>(0);
  const [sourceProvider, setSourceProvider] = useState<string>('');
  const [syncDone, setSyncDone] = useState<boolean>(false);
  const [syncConfirmationModal, setSyncConfirmationModal] =
    useState<ActiveState>('INACTIVE');

  useOutsideAlerter(
    searchDropdownRef,
    () => {
      setSearchQuery('');
      setSearchResults([]);
    },
    [],
    false,
  );

  const handleFileClick = (fileName: string) => {
    const fullPath = [...currentPath, fileName].join('/');
    setSelectedFile({
      id: fullPath,
      name: fileName,
    });
  };

  const handleSync = async () => {
    if (isSyncing) return;
    const provider = sourceProvider;
    setIsSyncing(true);
    setSyncProgress(0);

    try {
      const response = await userService.syncConnector(docId, provider, token);
      const data = await response.json();

      if (data.success) {
        console.log('Sync started successfully:', data.task_id);
        setSyncProgress(10);
        const maxAttempts = 30;
        const pollInterval = 2000;

        for (let attempt = 0; attempt < maxAttempts; attempt++) {
          try {
            const statusResponse = await userService.getTaskStatus(
              data.task_id,
              token,
            );
            const statusData = await statusResponse.json();

            if (statusData.status === 'SUCCESS') {
              setSyncProgress(100);
              const refreshResponse = await userService.getDirectoryStructure(
                docId,
                token,
              );
              const refreshData = await refreshResponse.json();
              if (refreshData && refreshData.directory_structure) {
                setDirectoryStructure(refreshData.directory_structure);
                setCurrentPath([]);
              }
              if (refreshData && refreshData.provider) {
                setSourceProvider(refreshData.provider);
              }
              setSyncDone(true);
              setTimeout(() => setSyncDone(false), 5000);
              break;
            } else if (statusData.status === 'FAILURE') break;
            else if (statusData.status === 'PROGRESS') {
              const progress = Number(
                statusData.result?.current ?? statusData.meta?.current ?? 0,
              );
              setSyncProgress(Math.max(10, progress));
            }

            await new Promise((resolve) => setTimeout(resolve, pollInterval));
          } catch (error) {
            console.error('Error polling task status:', error);
            break;
          }
        }
      }
    } catch (err) {
      console.error('Error syncing connector:', err);
    } finally {
      setIsSyncing(false);
      setSyncProgress(0);
    }
  };

  useEffect(() => {
    const fetchDirectoryStructure = async () => {
      try {
        setLoading(true);
        const directoryResponse = await userService.getDirectoryStructure(
          docId,
          token,
        );
        const directoryData = await directoryResponse.json();

        if (directoryData && directoryData.directory_structure) {
          setDirectoryStructure(directoryData.directory_structure);
        } else {
          setError('Invalid response format');
        }

        if (directoryData && directoryData.provider) {
          setSourceProvider(directoryData.provider);
        }
      } catch (err) {
        setError('Failed to load source information');
      } finally {
        setLoading(false);
      }
    };

    if (docId) fetchDirectoryStructure();
  }, [docId, token]);

  const navigateUp = () => setCurrentPath(currentPath.slice(0, -1));

  const getCurrentDirectory = (): DirectoryStructure => {
    if (!directoryStructure) return {};
    let current = directoryStructure;
    for (const dir of currentPath) {
      if (current[dir] && !current[dir].type)
        current = current[dir] as DirectoryStructure;
      else return {};
    }
    return current;
  };

  const renderFileSearch = () => (
    <div
      className="flex w-full flex-col items-center gap-2 sm:w-auto sm:flex-row"
      ref={searchDropdownRef}
    >
      <input
        type="text"
        value={searchQuery}
        onChange={(e) => {
          setSearchQuery(e.target.value);
          if (directoryStructure) {
            setSearchResults(searchFiles(e.target.value, directoryStructure));
          }
        }}
        placeholder={t('settings.sources.searchFiles')}
        className="w-full rounded-md border border-gray-300 p-2 focus:ring-2 focus:ring-violet-500 focus:outline-none sm:w-64 dark:border-gray-600 dark:bg-[#1F2023] dark:text-gray-200"
      />
      <button
        onClick={() => {
          if (directoryStructure) {
            setSearchResults(searchFiles(searchQuery, directoryStructure));
          }
        }}
        className="w-full rounded-md bg-violet-600 px-4 py-2 text-white transition hover:bg-violet-700 sm:w-auto"
      >
        {t('settings.sources.search')}
      </button>

      {searchQuery && (
        <div className="absolute z-10 mt-12 max-h-64 w-full overflow-y-auto rounded-md border border-gray-200 bg-white shadow-lg sm:w-64 dark:border-gray-700 dark:bg-[#1F2023]">
          {searchResults.length === 0 ? (
            <div className="p-2 text-center text-sm text-gray-500 dark:text-gray-400">
              {t('settings.sources.noResults')}
            </div>
          ) : (
            searchResults.map((result, index) => (
              <div
                key={index}
                onClick={() => handleSearchSelect(result)}
                className="flex cursor-pointer items-center gap-2 px-3 py-2 hover:bg-gray-100 dark:hover:bg-[#27282D]"
              >
                <img
                  src={result.isFile ? FileIcon : FolderIcon}
                  alt={result.isFile ? 'File' : 'Folder'}
                  className="h-4 w-4"
                />
                <span className="truncate text-sm dark:text-gray-200">
                  {result.name}
                </span>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );

  const searchFiles = (
    query: string,
    structure: DirectoryStructure,
    currentPath: string[] = [],
  ): SearchResult[] => {
    let results: SearchResult[] = [];
    Object.entries(structure).forEach(([name, node]) => {
      const fullPath = [...currentPath, name].join('/');
      if (name.toLowerCase().includes(query.toLowerCase())) {
        results.push({ name, path: fullPath, isFile: !!node.type });
      }
      if (!node.type) {
        results = [
          ...results,
          ...searchFiles(query, node as DirectoryStructure, [
            ...currentPath,
            name,
          ]),
        ];
      }
    });
    return results;
  };

  const handleSearchSelect = (result: SearchResult) => {
    if (result.isFile) {
      const pathParts = result.path.split('/');
      const fileName = pathParts.pop() || '';
      setCurrentPath(pathParts);
      setSelectedFile({ id: result.path, name: fileName });
    } else {
      setCurrentPath(result.path.split('/'));
      setSelectedFile(null);
    }
    setSearchQuery('');
    setSearchResults([]);
  };

  const handleFileSearch = (searchQuery: string) => {
    if (directoryStructure) return searchFiles(searchQuery, directoryStructure);
    return [];
  };

  const handleFileSelect = (path: string) => {
    const pathParts = path.split('/');
    const fileName = pathParts.pop() || '';
    setCurrentPath(pathParts);
    setSelectedFile({ id: path, name: fileName });
  };

  const currentDirectory = getCurrentDirectory();

  return (
    <div className="p-2">
      {selectedFile ? (
        <Chunks
          documentId={docId}
          documentName={sourceName}
          handleGoBack={() => setSelectedFile(null)}
          path={selectedFile.id}
          onFileSearch={handleFileSearch}
          onFileSelect={handleFileSelect}
        />
      ) : (
        <div className="flex w-full flex-col">
          <div className="mb-4 flex flex-col items-center justify-between gap-2 sm:flex-row">
            <div className="flex w-full items-center sm:w-auto">
              <button
                className="mr-3 flex h-[29px] w-[29px] items-center justify-center rounded-full border p-2 text-gray-400 dark:bg-[#28292D]"
                onClick={() =>
                  selectedFile ? setSelectedFile(null) : navigateUp()
                }
              >
                <img src={ArrowLeft} alt="back" className="h-3 w-3" />
              </button>
              <h2 className="font-semibold break-words text-[#7D54D1]">
                {sourceName}
              </h2>
            </div>
            {renderFileSearch()}
          </div>

          <TableContainer>
            <Table>
              <TableHead>
                <TableRow>
                  <TableHeader width="40%" align="left">
                    {t('settings.sources.fileName')}
                  </TableHeader>
                  <TableHeader width="30%" align="left">
                    {t('settings.sources.tokens')}
                  </TableHeader>
                  <TableHeader width="20%" align="left">
                    {t('settings.sources.size')}
                  </TableHeader>
                  <TableHeader width="10%" align="right">
                    <span className="sr-only">
                      {t('settings.sources.actions')}
                    </span>
                  </TableHeader>
                </TableRow>
              </TableHead>
              <TableBody>
                {loading ? (
                  <SkeletonLoader component="fileTable" />
                ) : (
                  Object.keys(currentDirectory).length > 0 &&
                  Object.entries(currentDirectory).map(([key, value]) => (
                    <TableRow key={key}>
                      <TableCell>{key}</TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </TableContainer>
        </div>
      )}

      <ConfirmationModal
        message={t('settings.sources.syncConfirmation', { sourceName })}
        modalState={syncConfirmationModal}
        setModalState={setSyncConfirmationModal}
        handleSubmit={handleSync}
        submitLabel={t('settings.sources.sync')}
        cancelLabel={t('cancel')}
      />
    </div>
  );
};

export default ConnectorTree;
