import React, { useState, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { formatBytes } from '../utils/stringUtils';
import { selectToken } from '../preferences/preferenceSlice';
import { ActiveState } from '../models/misc';
import Chunks from './Chunks';
import ContextMenu, { MenuOption } from './ContextMenu';
import ConfirmationModal from '../modals/ConfirmationModal';
import userService from '../api/services/userService';
import FileIcon from '../assets/file.svg';
import FolderIcon from '../assets/folder.svg';
import ArrowLeft from '../assets/arrow-left.svg';
import ThreeDots from '../assets/three-dots.svg';
import EyeView from '../assets/eye-view.svg';
import SyncIcon from '../assets/sync.svg';
import CheckmarkIcon from '../assets/checkMark2.svg';
import { useOutsideAlerter } from '../hooks';
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

interface ConnectorTreeComponentProps {
  docId: string;
  sourceName: string;
  onBackToDocuments: () => void;
}

interface SearchResult {
  name: string;
  path: string;
  isFile: boolean;
}

const ConnectorTreeComponent: React.FC<ConnectorTreeComponentProps> = ({
  docId,
  sourceName,
  onBackToDocuments,
}) => {
  const { t } = useTranslation();
  const [loading, setLoading] = useState<boolean>(true);
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

        // Poll task status using userService
        const maxAttempts = 30;
        const pollInterval = 2000;

        for (let attempt = 0; attempt < maxAttempts; attempt++) {
          try {
            const statusResponse = await userService.getTaskStatus(
              data.task_id,
              token,
            );
            const statusData = await statusResponse.json();

            console.log(
              `Task status (attempt ${attempt + 1}):`,
              statusData.status,
            );

            if (statusData.status === 'SUCCESS') {
              setSyncProgress(100);
              console.log('Sync completed successfully');

              // Refresh directory structure
              try {
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
              } catch (err) {
                console.error('Error refreshing directory structure:', err);
              }
              break;
            } else if (statusData.status === 'FAILURE') {
              console.error('Sync task failed:', statusData.result);
              break;
            } else if (statusData.status === 'PROGRESS') {
              const progress = Number(
                statusData.result && statusData.result.current != null
                  ? statusData.result.current
                  : statusData.meta && statusData.meta.current != null
                    ? statusData.meta.current
                    : 0,
              );
              setSyncProgress(Math.max(10, progress));
            }

            await new Promise((resolve) => setTimeout(resolve, pollInterval));
          } catch (error) {
            console.error('Error polling task status:', error);
            break;
          }
        }
      } else {
        console.error('Sync failed:', data.error);
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
        console.error(err);
      } finally {
        setLoading(false);
      }
    };

    if (docId) {
      fetchDirectoryStructure();
    }
  }, [docId, token]);

  const navigateToDirectory = (dirName: string) => {
    setCurrentPath([...currentPath, dirName]);
  };

  const navigateUp = () => {
    setCurrentPath(currentPath.slice(0, -1));
  };

  const getCurrentDirectory = (): DirectoryStructure => {
    if (!directoryStructure) return {};

    let current = directoryStructure;
    for (const dir of currentPath) {
      if (current[dir] && !current[dir].type) {
        current = current[dir] as DirectoryStructure;
      } else {
        return {};
      }
    }
    return current;
  };

  const getMenuRef = (id: string) => {
    if (!menuRefs.current[id]) {
      menuRefs.current[id] = React.createRef();
    }
    return menuRefs.current[id];
  };

  const handleMenuClick = (
    e: React.MouseEvent<HTMLButtonElement>,
    id: string,
  ) => {
    e.stopPropagation();
    setActiveMenuId(activeMenuId === id ? null : id);
  };

  const getActionOptions = (
    name: string,
    isFile: boolean,
    _itemId: string,
  ): MenuOption[] => {
    const options: MenuOption[] = [];

    options.push({
      icon: EyeView,
      label: t('settings.sources.view'),
      onClick: (event: React.SyntheticEvent) => {
        event.stopPropagation();
        if (isFile) {
          handleFileClick(name);
        } else {
          navigateToDirectory(name);
        }
      },
      iconWidth: 18,
      iconHeight: 18,
      variant: 'primary',
    });

    return options;
  };

  const calculateDirectoryStats = (
    structure: DirectoryStructure,
  ): { totalSize: number; totalTokens: number } => {
    let totalSize = 0;
    let totalTokens = 0;

    Object.entries(structure).forEach(([_, node]) => {
      if (node.type) {
        // It's a file
        totalSize += node.size_bytes || 0;
        totalTokens += node.token_count || 0;
      } else {
        // It's a directory, recurse
        const stats = calculateDirectoryStats(node);
        totalSize += stats.totalSize;
        totalTokens += stats.totalTokens;
      }
    });

    return { totalSize, totalTokens };
  };

  const handleBackNavigation = () => {
    if (selectedFile) {
      setSelectedFile(null);
    } else if (currentPath.length === 0) {
      if (onBackToDocuments) {
        onBackToDocuments();
      }
    } else {
      navigateUp();
    }
  };

  const renderPathNavigation = () => {
    return (
      <div className="mb-0 flex min-h-[38px] flex-col gap-2 text-base sm:flex-row sm:items-center sm:justify-between">
        {/* Left side with path navigation */}
        <div className="flex w-full items-center sm:w-auto">
          <button
            className="mr-3 flex h-[29px] w-[29px] items-center justify-center rounded-full border p-2 text-sm font-medium text-gray-400 dark:border-0 dark:bg-[#28292D] dark:text-gray-500 dark:hover:bg-[#2E2F34]"
            onClick={handleBackNavigation}
          >
            <img src={ArrowLeft} alt="left-arrow" className="h-3 w-3" />
          </button>

          <div className="flex flex-wrap items-center">
            <span className="font-semibold break-words text-[#7D54D1]">
              {sourceName}
            </span>
            {currentPath.length > 0 && (
              <>
                <span className="mx-1 flex-shrink-0 text-gray-500">/</span>
                {currentPath.map((dir, index) => (
                  <React.Fragment key={index}>
                    <span className="break-words text-gray-700 dark:text-[#E0E0E0]">
                      {dir}
                    </span>
                    {index < currentPath.length - 1 && (
                      <span className="mx-1 flex-shrink-0 text-gray-500">
                        /
                      </span>
                    )}
                  </React.Fragment>
                ))}
              </>
            )}
          </div>
        </div>

        <div className="relative mt-2 flex w-full flex-row flex-nowrap items-center justify-end gap-2 sm:mt-0 sm:w-auto">
          {renderFileSearch()}

          {/* Sync button */}
          <button
            onClick={() => setSyncConfirmationModal('ACTIVE')}
            disabled={isSyncing}
            className={`flex h-[38px] min-w-[108px] items-center justify-center rounded-full px-4 text-[14px] font-medium whitespace-nowrap transition-colors ${
              isSyncing
                ? 'cursor-not-allowed bg-gray-300 text-gray-600 dark:bg-gray-600 dark:text-gray-400'
                : 'bg-purple-30 hover:bg-violets-are-blue text-white'
            }`}
            title={
              isSyncing
                ? `${t('settings.sources.syncing')} ${syncProgress}%`
                : syncDone
                  ? 'Done'
                  : t('settings.sources.sync')
            }
          >
            <img
              src={syncDone ? CheckmarkIcon : SyncIcon}
              alt={t('settings.sources.sync')}
              className={`mr-2 h-4 w-4 brightness-0 invert filter ${isSyncing ? 'animate-spin' : ''}`}
            />
            {isSyncing
              ? `${syncProgress}%`
              : syncDone
                ? 'Done'
                : t('settings.sources.sync')}
          </button>
        </div>
      </div>
    );
  };

  const renderFileTree = (directory: DirectoryStructure): React.ReactNode[] => {
    // Create parent directory row
    const parentRow =
      currentPath.length > 0
        ? [
            <TableRow key="parent-dir" onClick={navigateUp}>
              <TableCell width="40%" align="left">
                <div className="flex items-center">
                  <img
                    src={FolderIcon}
                    alt={t('settings.sources.parentFolderAlt')}
                    className="mr-2 h-4 w-4 flex-shrink-0"
                  />
                  <span className="truncate">..</span>
                </div>
              </TableCell>
              <TableCell width="30%" align="left">
                -
              </TableCell>
              <TableCell width="20%" align="left">
                -
              </TableCell>
              <TableCell width="10%" align="right"></TableCell>
            </TableRow>,
          ]
        : [];

    // Sort entries: directories first, then files, both alphabetically
    const sortedEntries = Object.entries(directory).sort(
      ([nameA, nodeA], [nameB, nodeB]) => {
        const isFileA = !!nodeA.type;
        const isFileB = !!nodeB.type;

        if (isFileA !== isFileB) {
          return isFileA ? 1 : -1; // Directories first
        }

        return nameA.localeCompare(nameB); // Alphabetical within each group
      },
    );

    // Process directories
    const directoryRows = sortedEntries
      .filter(([_, node]) => !node.type)
      .map(([name, node]) => {
        const itemId = `dir-${name}`;
        const menuRef = getMenuRef(itemId);

        // Calculate directory stats
        const dirStats = calculateDirectoryStats(node as DirectoryStructure);

        return (
          <TableRow key={itemId} onClick={() => navigateToDirectory(name)}>
            <TableCell width="40%" align="left">
              <div className="flex min-w-0 items-center">
                <img
                  src={FolderIcon}
                  alt={t('settings.sources.folderAlt')}
                  className="mr-2 h-4 w-4 flex-shrink-0"
                />
                <span className="truncate">{name}</span>
              </div>
            </TableCell>
            <TableCell width="30%" align="left">
              {dirStats.totalTokens > 0
                ? dirStats.totalTokens.toLocaleString()
                : '-'}
            </TableCell>
            <TableCell width="20%" align="left">
              {dirStats.totalSize > 0 ? formatBytes(dirStats.totalSize) : '-'}
            </TableCell>
            <TableCell width="10%" align="right">
              <div ref={menuRef} className="relative">
                <button
                  onClick={(e) => handleMenuClick(e, itemId)}
                  className="inline-flex h-[35px] w-[24px] shrink-0 items-center justify-center rounded-md font-medium transition-colors hover:bg-[#EBEBEB] dark:hover:bg-[#26272E]"
                  aria-label={t('settings.sources.menuAlt')}
                >
                  <img
                    src={ThreeDots}
                    alt={t('settings.sources.menuAlt')}
                    className="opacity-60 hover:opacity-100"
                  />
                </button>
                <ContextMenu
                  isOpen={activeMenuId === itemId}
                  setIsOpen={(isOpen) =>
                    setActiveMenuId(isOpen ? itemId : null)
                  }
                  options={getActionOptions(name, false, itemId)}
                  anchorRef={menuRef}
                  position="bottom-left"
                  offset={{ x: -4, y: 4 }}
                />
              </div>
            </TableCell>
          </TableRow>
        );
      });

    // Process files
    const fileRows = sortedEntries
      .filter(([_, node]) => !!node.type)
      .map(([name, node]) => {
        const itemId = `file-${name}`;
        const menuRef = getMenuRef(itemId);

        return (
          <TableRow key={itemId} onClick={() => handleFileClick(name)}>
            <TableCell width="40%" align="left">
              <div className="flex min-w-0 items-center">
                <img
                  src={FileIcon}
                  alt={t('settings.sources.fileAlt')}
                  className="mr-2 h-4 w-4 flex-shrink-0"
                />
                <span className="truncate">{name}</span>
              </div>
            </TableCell>
            <TableCell width="30%" align="left">
              {node.token_count?.toLocaleString() || '-'}
            </TableCell>
            <TableCell width="20%" align="left">
              {node.size_bytes ? formatBytes(node.size_bytes) : '-'}
            </TableCell>
            <TableCell width="10%" align="right">
              <div ref={menuRef} className="relative">
                <button
                  onClick={(e) => handleMenuClick(e, itemId)}
                  className="inline-flex h-[35px] w-[24px] shrink-0 items-center justify-center rounded-md font-medium transition-colors hover:bg-[#EBEBEB] dark:hover:bg-[#26272E]"
                  aria-label={t('settings.sources.menuAlt')}
                >
                  <img
                    src={ThreeDots}
                    alt={t('settings.sources.menuAlt')}
                    className="opacity-60 hover:opacity-100"
                  />
                </button>
                <ContextMenu
                  isOpen={activeMenuId === itemId}
                  setIsOpen={(isOpen) =>
                    setActiveMenuId(isOpen ? itemId : null)
                  }
                  options={getActionOptions(name, true, itemId)}
                  anchorRef={menuRef}
                  position="bottom-left"
                  offset={{ x: -4, y: 4 }}
                />
              </div>
            </TableCell>
          </TableRow>
        );
      });

    return [...parentRow, ...directoryRows, ...fileRows];
  };

  const searchFiles = (
    query: string,
    structure: DirectoryStructure,
    currentPath: string[] = [],
  ): SearchResult[] => {
    let results: SearchResult[] = [];

    Object.entries(structure).forEach(([name, node]) => {
      const fullPath = [...currentPath, name].join('/');

      if (name.toLowerCase().includes(query.toLowerCase())) {
        results.push({
          name,
          path: fullPath,
          isFile: !!node.type,
        });
      }

      if (!node.type) {
        // If it's a directory, search recursively
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

      setSelectedFile({
        id: result.path,
        name: fileName,
      });
    } else {
      setCurrentPath(result.path.split('/'));
      setSelectedFile(null);
    }
    setSearchQuery('');
    setSearchResults([]);
  };

  const renderFileSearch = () => {
    return (
      <div className="relative w-52" ref={searchDropdownRef}>
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
          className={`h-[38px] w-full border border-[#D1D9E0] px-4 py-2 dark:border-[#6A6A6A] ${searchQuery ? 'rounded-t-[24px]' : 'rounded-[24px]'} bg-transparent focus:outline-none dark:text-[#E0E0E0]`}
        />

        {searchQuery && (
          <div className="absolute top-full right-0 left-0 z-10 max-h-[calc(100vh-200px)] w-full overflow-hidden rounded-b-[12px] border border-t-0 border-[#D1D9E0] bg-white shadow-lg transition-all duration-200 dark:border-[#6A6A6A] dark:bg-[#1F2023]">
            <div className="max-h-[calc(100vh-200px)] overflow-x-hidden overflow-y-auto overscroll-contain">
              {searchResults.length === 0 ? (
                <div className="py-2 text-center text-sm text-gray-500 dark:text-gray-400">
                  {t('settings.sources.noResults')}
                </div>
              ) : (
                searchResults.map((result, index) => (
                  <div
                    key={index}
                    onClick={() => handleSearchSelect(result)}
                    title={result.path}
                    className={`flex min-w-0 cursor-pointer items-center px-3 py-2 hover:bg-[#ECEEEF] dark:hover:bg-[#27282D] ${
                      index !== searchResults.length - 1
                        ? 'border-b border-[#D1D9E0] dark:border-[#6A6A6A]'
                        : ''
                    }`}
                  >
                    <img
                      src={result.isFile ? FileIcon : FolderIcon}
                      alt={
                        result.isFile
                          ? t('settings.sources.fileAlt')
                          : t('settings.sources.folderAlt')
                      }
                      className="mr-2 h-4 w-4 flex-shrink-0"
                    />
                    <span className="flex-1 truncate text-sm dark:text-[#E0E0E0]">
                      {result.path.split('/').pop() || result.path}
                    </span>
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </div>
    );
  };

  const handleFileSearch = (searchQuery: string) => {
    if (directoryStructure) {
      return searchFiles(searchQuery, directoryStructure);
    }
    return [];
  };

  const handleFileSelect = (path: string) => {
    const pathParts = path.split('/');
    const fileName = pathParts.pop() || '';
    setCurrentPath(pathParts);
    setSelectedFile({
      id: path,
      name: fileName,
    });
  };

  const currentDirectory = getCurrentDirectory();

  const navigateToPath = (index: number) => {
    setCurrentPath(currentPath.slice(0, index + 1));
  };

  return (
    <div>
      {selectedFile ? (
        <div className="flex">
          <div className="flex-1">
            <Chunks
              documentId={docId}
              documentName={sourceName}
              handleGoBack={() => setSelectedFile(null)}
              path={selectedFile.id}
              onFileSearch={handleFileSearch}
              onFileSelect={handleFileSelect}
            />
          </div>
        </div>
      ) : (
        <div className="flex w-full max-w-full flex-col overflow-hidden">
          <div className="mb-2">{renderPathNavigation()}</div>

          <div className="w-full">
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
                <TableBody>{renderFileTree(getCurrentDirectory())}</TableBody>
              </Table>
            </TableContainer>
          </div>
        </div>
      )}

      <ConfirmationModal
        message={t('settings.sources.syncConfirmation', {
          sourceName,
        })}
        modalState={syncConfirmationModal}
        setModalState={setSyncConfirmationModal}
        handleSubmit={handleSync}
        submitLabel={t('settings.sources.sync')}
        cancelLabel={t('cancel')}
      />
    </div>
  );
};

export default ConnectorTreeComponent;
