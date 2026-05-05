import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import userService from '../api/services/userService';
import { formatBytes } from '../utils/stringUtils';
import { formatDate } from '../utils/dateTimeUtils';
import {
  getSessionToken,
  setSessionToken,
  removeSessionToken,
} from '../utils/providerUtils';
import ConnectorAuth from '../components/ConnectorAuth';
import FileIcon from '../assets/file.svg';
import FolderIcon from '../assets/folder.svg';
import CheckIcon from '../assets/checkmark.svg';
import SearchIcon from '../assets/search.svg';
import Input from './Input';
import {
  Table,
  TableContainer,
  TableHead,
  TableBody,
  TableRow,
  TableHeader,
  TableCell,
} from './Table';

interface CloudFile {
  id: string;
  name: string;
  type: string;
  size?: number;
  modifiedTime: string;
  isFolder?: boolean;
}

interface CloudFilePickerProps {
  onSelectionChange: (
    selectedFileIds: string[],
    selectedFolderIds?: string[],
  ) => void;
  onDisconnect?: () => void;
  provider: string;
  token: string | null;
  initialSelectedFiles?: string[];
  initialSelectedFolders?: string[];
}

export const FilePicker: React.FC<CloudFilePickerProps> = ({
  onSelectionChange,
  onDisconnect,
  provider,
  token,
  initialSelectedFiles = [],
}) => {
  const PROVIDER_CONFIG = {
    google_drive: {
      displayName: 'Drive',
      rootName: 'My Drive',
    },
    share_point: {
      displayName: 'SharePoint',
      rootName: 'My Files',
    },
    confluence: {
      displayName: 'Confluence',
      rootName: 'Spaces',
    },
  } as const;

  const getProviderConfig = (provider: string) => {
    return (
      PROVIDER_CONFIG[provider as keyof typeof PROVIDER_CONFIG] || {
        displayName: provider,
        rootName: 'Root',
      }
    );
  };

  const { t } = useTranslation();
  const [files, setFiles] = useState<CloudFile[]>([]);
  const [selectedFiles, setSelectedFiles] =
    useState<string[]>(initialSelectedFiles);
  const [selectedFolders, setSelectedFolders] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [hasMoreFiles, setHasMoreFiles] = useState(false);
  const [nextPageToken, setNextPageToken] = useState<string | null>(null);
  const [currentFolderId, setCurrentFolderId] = useState<string | null>(null);
  const [folderPath, setFolderPath] = useState<
    Array<{ id: string | null; name: string }>
  >([
    {
      id: null,
      name: getProviderConfig(provider).rootName,
    },
  ]);
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [authError, setAuthError] = useState<string>('');
  const [isConnected, setIsConnected] = useState(false);
  const [userEmail, setUserEmail] = useState<string>('');
  const [allowsSharedContent, setAllowsSharedContent] = useState(false);
  const [activeTab, setActiveTab] = useState<'my_files' | 'shared'>('my_files');

  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const searchTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  const isFolder = (file: CloudFile) => {
    return (
      file.isFolder ||
      file.type === 'application/vnd.google-apps.folder' ||
      file.type === 'folder'
    );
  };

  const loadCloudFiles = useCallback(
    async (
      sessionToken: string,
      folderId: string | null,
      pageToken?: string,
      searchQuery = '',
      shared = false,
    ) => {
      // Cancel any in-flight request so stale responses never overwrite new state
      abortControllerRef.current?.abort();
      const controller = new AbortController();
      abortControllerRef.current = controller;

      setIsLoading(true);

      if (!pageToken) {
        setFiles([]);
      }

      try {
        const body: Record<string, unknown> = {
          provider: provider,
          session_token: sessionToken,
          folder_id: folderId,
          limit: 10,
          page_token: pageToken,
          search_query: searchQuery,
          shared: shared,
        };
        const response = await userService.getConnectorFiles(
          body,
          token,
          controller.signal,
        );

        const data = await response.json();
        if (data.success) {
          setFiles((prev) =>
            pageToken ? [...prev, ...data.files] : data.files,
          );
          setNextPageToken(data.next_page_token);
          setHasMoreFiles(!!data.next_page_token);
        } else {
          console.error('Error loading files:', data.error);
          if (!pageToken) {
            setFiles([]);
          }
        }
      } catch (err) {
        if ((err as Error).name === 'AbortError') return;
        console.error('Error loading files:', err);
        if (!pageToken) {
          setFiles([]);
        }
      } finally {
        if (!controller.signal.aborted) {
          setIsLoading(false);
        }
      }
    },
    [token, provider],
  );

  const validateAndLoadFiles = useCallback(async () => {
    const sessionToken = getSessionToken(provider);
    if (!sessionToken) {
      setIsConnected(false);
      return;
    }

    try {
      const validateResponse = await userService.validateConnectorSession(
        provider,
        token,
      );

      if (!validateResponse.ok) {
        removeSessionToken(provider);
        setIsConnected(false);
        setAuthError(
          `Session expired. Please reconnect to ${getProviderConfig(provider).displayName}.`,
        );
        return;
      }

      const validateData = await validateResponse.json();
      if (validateData.success) {
        setUserEmail(validateData.user_email || 'Connected User');
        setIsConnected(true);
        setAuthError('');
        if (provider === 'share_point') {
          setAllowsSharedContent(validateData.allows_shared_content ?? false);
        }

        setFiles([]);
        setNextPageToken(null);
        setHasMoreFiles(false);
        setCurrentFolderId(null);
        setActiveTab('my_files');
        setFolderPath([
          {
            id: null,
            name: getProviderConfig(provider).rootName,
          },
        ]);
        loadCloudFiles(sessionToken, null, undefined, '');
      } else {
        removeSessionToken(provider);
        setIsConnected(false);
        setAuthError(
          validateData.error ||
            'Session expired. Please reconnect your account.',
        );
      }
    } catch (error) {
      console.error('Error validating session:', error);
      setAuthError('Failed to validate session. Please reconnect.');
      setIsConnected(false);
    }
  }, [provider, token, loadCloudFiles]);

  useEffect(() => {
    validateAndLoadFiles();
  }, [validateAndLoadFiles]);

  const handleScroll = useCallback(() => {
    const scrollContainer = scrollContainerRef.current;
    if (!scrollContainer) return;

    const { scrollTop, scrollHeight, clientHeight } = scrollContainer;
    const isNearBottom = scrollHeight - scrollTop - clientHeight < 50;

    if (isNearBottom && hasMoreFiles && !isLoading && nextPageToken) {
      const sessionToken = getSessionToken(provider);
      if (sessionToken) {
        loadCloudFiles(
          sessionToken,
          currentFolderId,
          nextPageToken,
          searchQuery,
          activeTab === 'shared' && !currentFolderId,
        );
      }
    }
  }, [
    hasMoreFiles,
    isLoading,
    nextPageToken,
    currentFolderId,
    searchQuery,
    provider,
    loadCloudFiles,
    activeTab,
  ]);

  useEffect(() => {
    const scrollContainer = scrollContainerRef.current;
    if (scrollContainer) {
      scrollContainer.addEventListener('scroll', handleScroll);
      return () => scrollContainer.removeEventListener('scroll', handleScroll);
    }
  }, [handleScroll]);

  useEffect(() => {
    return () => {
      if (searchTimeoutRef.current) {
        clearTimeout(searchTimeoutRef.current);
      }
      abortControllerRef.current?.abort();
    };
  }, []);

  const handleSearchChange = (query: string) => {
    setSearchQuery(query);

    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current);
    }

    searchTimeoutRef.current = setTimeout(() => {
      const sessionToken = getSessionToken(provider);
      if (sessionToken) {
        loadCloudFiles(
          sessionToken,
          currentFolderId,
          undefined,
          query,
          activeTab === 'shared' && !currentFolderId,
        );
      }
    }, 300);
  };

  const handleFolderClick = (folderId: string, folderName: string) => {
    if (folderId === currentFolderId) {
      return;
    }

    setIsLoading(true);

    setCurrentFolderId(folderId);
    setFolderPath((prev) => [...prev, { id: folderId, name: folderName }]);
    setSearchQuery('');

    const sessionToken = getSessionToken(provider);
    if (sessionToken) {
      loadCloudFiles(sessionToken, folderId, undefined, '', false);
    }
  };

  const navigateBack = (index: number) => {
    if (index >= folderPath.length - 1) return;

    const newFolderPath = folderPath.slice(0, index + 1);
    const newFolderId = newFolderPath[newFolderPath.length - 1].id;

    setFolderPath(newFolderPath);
    setCurrentFolderId(newFolderId);
    setSearchQuery('');

    const sessionToken = getSessionToken(provider);
    if (sessionToken) {
      loadCloudFiles(
        sessionToken,
        newFolderId,
        undefined,
        '',
        activeTab === 'shared' && !newFolderId,
      );
    }
  };

  const handleTabChange = (tab: 'my_files' | 'shared') => {
    if (tab === activeTab) return;
    setActiveTab(tab);
    setFiles([]);
    setNextPageToken(null);
    setHasMoreFiles(false);
    setCurrentFolderId(null);
    setSearchQuery('');
    setFolderPath([
      {
        id: null,
        name:
          tab === 'shared' ? 'Shared' : getProviderConfig(provider).rootName,
      },
    ]);
    const sessionToken = getSessionToken(provider);
    if (sessionToken) {
      loadCloudFiles(sessionToken, null, undefined, '', tab === 'shared');
    }
  };

  const handleFileSelect = (fileId: string, isFolder: boolean) => {
    if (isFolder) {
      const newSelectedFolders = selectedFolders.includes(fileId)
        ? selectedFolders.filter((id) => id !== fileId)
        : [...selectedFolders, fileId];
      setSelectedFolders(newSelectedFolders);
      onSelectionChange(selectedFiles, newSelectedFolders);
    } else {
      const newSelectedFiles = selectedFiles.includes(fileId)
        ? selectedFiles.filter((id) => id !== fileId)
        : [...selectedFiles, fileId];
      setSelectedFiles(newSelectedFiles);
      onSelectionChange(newSelectedFiles, selectedFolders);
    }
  };

  return (
    <div className="">
      {authError && (
        <div className="mb-4 text-center text-sm text-red-500">{authError}</div>
      )}

      <ConnectorAuth
        provider={provider}
        label={`Connect to ${getProviderConfig(provider).displayName}`}
        onSuccess={(data) => {
          setUserEmail(data.user_email || 'Connected User');
          setIsConnected(true);
          setAuthError('');

          if (data.session_token) {
            setSessionToken(provider, data.session_token);
            validateAndLoadFiles();
          }
        }}
        onError={(error) => {
          setAuthError(error);
          setIsConnected(false);
        }}
        isConnected={isConnected}
        userEmail={userEmail}
        onDisconnect={() => {
          const sessionToken = getSessionToken(provider);
          if (sessionToken) {
            userService
              .disconnectConnector(provider, sessionToken, token)
              .catch((err) =>
                console.error(
                  `Error disconnecting from ${getProviderConfig(provider).displayName}:`,
                  err,
                ),
              );
          }

          removeSessionToken(provider);
          setIsConnected(false);
          setAllowsSharedContent(false);
          setActiveTab('my_files');
          setFiles([]);
          setSelectedFiles([]);
          onSelectionChange([]);

          if (onDisconnect) {
            onDisconnect();
          }
        }}
      />

      {isConnected && (
        <div className="border-border dark:border-border mt-3 overflow-hidden rounded-lg border">
          <div className="border-border dark:border-border rounded-t-lg">
            {provider === 'share_point' && allowsSharedContent && (
              <div className="border-border dark:border-border flex border-b">
                <button
                  onClick={() => handleTabChange('my_files')}
                  className={`px-4 py-2 text-sm font-medium ${
                    activeTab === 'my_files'
                      ? 'border-b-2 border-[#A076F6] text-[#A076F6]'
                      : 'text-gray-600 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200'
                  }`}
                >
                  {t('filePicker.myFiles')}
                </button>
                <button
                  onClick={() => handleTabChange('shared')}
                  className={`px-4 py-2 text-sm font-medium ${
                    activeTab === 'shared'
                      ? 'border-b-2 border-[#A076F6] text-[#A076F6]'
                      : 'text-gray-600 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200'
                  }`}
                >
                  {t('filePicker.sharedWithMe')}
                </button>
              </div>
            )}
            <div className="dark:bg-muted rounded-t-lg bg-[#EEE6FF78] px-4 pt-4">
              <div className="mb-2 flex items-center gap-1">
                {folderPath.map((path, index) => (
                  <div
                    key={path.id || 'root'}
                    className="flex items-center gap-1"
                  >
                    {index > 0 && <span className="text-gray-400">/</span>}
                    <button
                      onClick={() => navigateBack(index)}
                      className="text-sm text-[#A076F6] hover:text-[#8A5FD4] hover:underline"
                      disabled={index === folderPath.length - 1}
                    >
                      {path.name}
                    </button>
                  </div>
                ))}
              </div>

              <div className="mb-3 text-sm text-gray-600 dark:text-gray-400">
                Select Files from {getProviderConfig(provider).displayName}
              </div>

              <div className="mb-3 max-w-md">
                <Input
                  type="text"
                  placeholder={t('filePicker.searchPlaceholder')}
                  value={searchQuery}
                  onChange={(e) => handleSearchChange(e.target.value)}
                  colorVariant="silver"
                  borderVariant="thin"
                  labelBgClassName="bg-[#EEE6FF78] dark:bg-muted"
                  leftIcon={
                    <img src={SearchIcon} alt="Search" width={16} height={16} />
                  }
                />
              </div>

              {/* Selected Files Message */}
              <div className="pb-3 text-sm text-gray-600 dark:text-gray-400">
                {t('filePicker.itemsSelected', {
                  count: selectedFiles.length + selectedFolders.length,
                })}
              </div>
            </div>

            <div className="border-border dark:border-border h-72 border-t">
              <TableContainer
                ref={scrollContainerRef}
                height="288px"
                className="scrollbar-overlay md:w-4xl lg:w-5xl"
                bordered={false}
              >
                {
                  <>
                    <Table minWidth="1200px">
                      <TableHead>
                        <TableRow>
                          <TableHeader width="40px"></TableHeader>
                          <TableHeader width="60%">
                            {t('filePicker.name')}
                          </TableHeader>
                          <TableHeader width="20%">
                            {t('filePicker.lastModified')}
                          </TableHeader>
                          <TableHeader width="20%">
                            {t('filePicker.size')}
                          </TableHeader>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {isLoading && files.length === 0
                          ? Array.from({ length: 5 }).map((_, i) => (
                              <TableRow key={`skeleton-${i}`}>
                                <TableCell width="40px" align="center">
                                  <div className="mx-auto h-5 w-5 animate-pulse rounded bg-gray-200 dark:bg-gray-700" />
                                </TableCell>
                                <TableCell>
                                  <div className="h-4 w-48 animate-pulse rounded bg-gray-200 dark:bg-gray-700" />
                                </TableCell>
                                <TableCell>
                                  <div className="h-4 w-24 animate-pulse rounded bg-gray-200 dark:bg-gray-700" />
                                </TableCell>
                                <TableCell>
                                  <div className="h-4 w-16 animate-pulse rounded bg-gray-200 dark:bg-gray-700" />
                                </TableCell>
                              </TableRow>
                            ))
                          : files.map((file, index) => (
                              <TableRow
                                key={`${file.id}-${index}`}
                                onClick={() => {
                                  if (isFolder(file)) {
                                    handleFolderClick(file.id, file.name);
                                  } else {
                                    handleFileSelect(file.id, false);
                                  }
                                }}
                              >
                                <TableCell width="40px" align="center">
                                  <div
                                    className="border-border dark:border-border mx-auto flex h-5 w-5 shrink-0 cursor-pointer items-center justify-center border p-[0.5px] text-sm"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      handleFileSelect(file.id, isFolder(file));
                                    }}
                                  >
                                    {(isFolder(file)
                                      ? selectedFolders
                                      : selectedFiles
                                    ).includes(file.id) && (
                                      <img
                                        src={CheckIcon}
                                        alt="Selected"
                                        className="h-4 w-4"
                                      />
                                    )}
                                  </div>
                                </TableCell>
                                <TableCell>
                                  <div className="flex min-w-0 items-center gap-3">
                                    <div className="shrink-0">
                                      <img
                                        src={
                                          isFolder(file) ? FolderIcon : FileIcon
                                        }
                                        alt={isFolder(file) ? 'Folder' : 'File'}
                                        className="h-6 w-6"
                                      />
                                    </div>
                                    <span className="truncate">
                                      {file.name}
                                    </span>
                                  </div>
                                </TableCell>
                                <TableCell className="text-xs">
                                  {formatDate(file.modifiedTime)}
                                </TableCell>
                                <TableCell className="text-xs">
                                  {file.size ? formatBytes(file.size) : '-'}
                                </TableCell>
                              </TableRow>
                            ))}
                        {isLoading &&
                          files.length > 0 &&
                          Array.from({ length: 3 }).map((_, i) => (
                            <TableRow key={`load-more-skeleton-${i}`}>
                              <TableCell width="40px" align="center">
                                <div className="mx-auto h-5 w-5 animate-pulse rounded bg-gray-200 dark:bg-gray-700" />
                              </TableCell>
                              <TableCell>
                                <div className="h-4 w-48 animate-pulse rounded bg-gray-200 dark:bg-gray-700" />
                              </TableCell>
                              <TableCell>
                                <div className="h-4 w-24 animate-pulse rounded bg-gray-200 dark:bg-gray-700" />
                              </TableCell>
                              <TableCell>
                                <div className="h-4 w-16 animate-pulse rounded bg-gray-200 dark:bg-gray-700" />
                              </TableCell>
                            </TableRow>
                          ))}
                      </TableBody>
                    </Table>
                  </>
                }
              </TableContainer>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
