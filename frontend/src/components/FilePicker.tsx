import React, { useState, useEffect, useCallback, useRef } from 'react';
import { formatBytes } from '../utils/stringUtils';
import { formatDate } from '../utils/dateTimeUtils';
import { getSessionToken, setSessionToken, removeSessionToken } from '../utils/providerUtils';
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
  onSelectionChange: (selectedFileIds: string[], selectedFolderIds?: string[]) => void;
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
  } as const;

  const getProviderConfig = (provider: string) => {
    return PROVIDER_CONFIG[provider as keyof typeof PROVIDER_CONFIG] || {
      displayName: provider,
      rootName: 'Root',
    };
  };

  const [files, setFiles] = useState<CloudFile[]>([]);
  const [selectedFiles, setSelectedFiles] = useState<string[]>(initialSelectedFiles);
  const [selectedFolders, setSelectedFolders] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [hasMoreFiles, setHasMoreFiles] = useState(false);
  const [nextPageToken, setNextPageToken] = useState<string | null>(null);
  const [currentFolderId, setCurrentFolderId] = useState<string | null>(null);
  const [folderPath, setFolderPath] = useState<Array<{ id: string | null, name: string }>>([{
    id: null,
    name: getProviderConfig(provider).rootName
  }]);
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [authError, setAuthError] = useState<string>('');
  const [isConnected, setIsConnected] = useState(false);
  const [userEmail, setUserEmail] = useState<string>('');

  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const searchTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const isFolder = (file: CloudFile) => {
    return file.isFolder ||
      file.type === 'application/vnd.google-apps.folder' ||
      file.type === 'folder';
  };

  const loadCloudFiles = useCallback(
    async (
      sessionToken: string,
      folderId: string | null,
      pageToken?: string,
      searchQuery: string = ''
    ) => {
      setIsLoading(true);

      const apiHost = import.meta.env.VITE_API_HOST;
      if (!pageToken) {
        setFiles([]);
      }

      try {
        const response = await fetch(`${apiHost}/api/connectors/files`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify({
            provider: provider,
            session_token: sessionToken,
            folder_id: folderId,
            limit: 10,
            page_token: pageToken,
            search_query: searchQuery
          })
        });

        const data = await response.json();
        if (data.success) {
          setFiles(prev => pageToken ? [...prev, ...data.files] : data.files);
          setNextPageToken(data.next_page_token);
          setHasMoreFiles(!!data.next_page_token);
        } else {
          console.error('Error loading files:', data.error);
          if (!pageToken) {
            setFiles([]);
          }
        }
      } catch (err) {
        console.error('Error loading files:', err);
        if (!pageToken) {
          setFiles([]);
        }
      } finally {
        setIsLoading(false);
      }
    },
    [token, provider]
  );

  const validateAndLoadFiles = useCallback(async () => {
    const sessionToken = getSessionToken(provider);
    if (!sessionToken) {
      setIsConnected(false);
      return;
    }

    try {
      const apiHost = import.meta.env.VITE_API_HOST;
      const validateResponse = await fetch(`${apiHost}/api/connectors/validate-session`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ provider: provider, session_token: sessionToken })
      });

      if (!validateResponse.ok) {
        removeSessionToken(provider);
        setIsConnected(false);
        setAuthError('Session expired. Please reconnect to Google Drive.');
        return;
      }

      const validateData = await validateResponse.json();
      if (validateData.success) {
        setUserEmail(validateData.user_email || 'Connected User');
        setIsConnected(true);
        setAuthError('');

        setFiles([]);
        setNextPageToken(null);
        setHasMoreFiles(false);
        setCurrentFolderId(null);
        setFolderPath([{
          id: null, name: getProviderConfig(provider).rootName
        }]);
        loadCloudFiles(sessionToken, null, undefined, '');
      } else {
        removeSessionToken(provider);
        setIsConnected(false);
        setAuthError(validateData.error || 'Session expired. Please reconnect your account.');
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
        loadCloudFiles(sessionToken, currentFolderId, nextPageToken, searchQuery);
      }
    }
  }, [hasMoreFiles, isLoading, nextPageToken, currentFolderId, searchQuery, provider, loadCloudFiles]);

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
        loadCloudFiles(sessionToken, currentFolderId, undefined, query);
      }
    }, 300);
  };

  const handleFolderClick = (folderId: string, folderName: string) => {
    if (folderId === currentFolderId) {
      return;
    }

    setIsLoading(true);

    setCurrentFolderId(folderId);
    setFolderPath(prev => [...prev, { id: folderId, name: folderName }]);
    setSearchQuery('');

    const sessionToken = getSessionToken(provider);
    if (sessionToken) {
      loadCloudFiles(sessionToken, folderId, undefined, '');
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
      loadCloudFiles(sessionToken, newFolderId, undefined, '');
    }
  };

  const handleFileSelect = (fileId: string, isFolder: boolean) => {
    if (isFolder) {
      const newSelectedFolders = selectedFolders.includes(fileId)
        ? selectedFolders.filter(id => id !== fileId)
        : [...selectedFolders, fileId];
      setSelectedFolders(newSelectedFolders);
      onSelectionChange(selectedFiles, newSelectedFolders);
    } else {
      const newSelectedFiles = selectedFiles.includes(fileId)
        ? selectedFiles.filter(id => id !== fileId)
        : [...selectedFiles, fileId];
      setSelectedFiles(newSelectedFiles);
      onSelectionChange(newSelectedFiles, selectedFolders);
    }
  };

  // Render authentication UI
  if (!isConnected) {
    return (
      <div className="border border-[#EEE6FF78] rounded-lg dark:border-[#6A6A6A] p-6">
        {authError && (
          <div className="text-red-500 text-sm mb-4 text-center">{authError}</div>
        )}
        <ConnectorAuth
          provider={provider}
          onSuccess={(data) => {
            setUserEmail(data.user_email || 'Connected User');
            setIsConnected(true);
            setAuthError('');

            if (data.session_token) {
              setSessionToken(provider, data.session_token);
              loadCloudFiles(data.session_token, null);
            }
          }}
          onError={(error) => {
            setAuthError(error);
            setIsConnected(false);
          }}
        />
      </div>
    );
  }

  // Render file browser UI
  return (
    <div className=''>
      {/* Connected state indicator */}
      <div className="p-3">
        <div className="w-full flex items-center justify-between rounded-[10px] bg-[#8FDD51] px-4 py-2 text-[#212121] font-medium text-sm">
          <div className="flex items-center gap-2">
            <svg className="h-4 w-4" viewBox="0 0 24 24">
              <path fill="currentColor" d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z" />
            </svg>
            <span>Connected as {userEmail}</span>
          </div>
          <button
            onClick={() => {
              const sessionToken = getSessionToken(provider);
              if (sessionToken) {
                const apiHost = import.meta.env.VITE_API_HOST;
                fetch(`${apiHost}/api/connectors/disconnect`, {
                  method: 'POST',
                  headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                  },
                  body: JSON.stringify({ provider: provider, session_token: sessionToken })
                }).catch(err => console.error(`Error disconnecting from ${getProviderConfig(provider).displayName}:`, err));
              }

              removeSessionToken(provider);
              setIsConnected(false);
              setFiles([]);
              setSelectedFiles([]);
              onSelectionChange([]);

              if (onDisconnect) {
                onDisconnect();
              }
            }}
            className="text-[#212121] hover:text-gray-700 font-medium text-xs underline"
          >
            Disconnect
          </button>
        </div>
      </div>

      <div className="border border-[#EEE6FF78] rounded-lg dark:border-[#6A6A6A] mt-3">
        <div className=" border-[#EEE6FF78] dark:border-[#6A6A6A] rounded-t-lg">
          {/* Breadcrumb navigation */}
          <div className="px-4 pt-4 bg-[#EEE6FF78] dark:bg-[#2A262E] rounded-t-lg">
            <div className="flex items-center gap-1 mb-2">
              {folderPath.map((path, index) => (
                <div key={path.id || 'root'} className="flex items-center gap-1">
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
                placeholder="Search files and folders..."
                value={searchQuery}
                onChange={(e) => handleSearchChange(e.target.value)}
                colorVariant="silver"
                borderVariant="thin"
                labelBgClassName="bg-[#EEE6FF78] dark:bg-[#2A262E]"
                leftIcon={<img src={SearchIcon} alt="Search" width={16} height={16} />}
              />
            </div>

            {/* Selected Files Message */}
            <div className="pb-3 text-sm text-gray-600 dark:text-gray-400">
              {selectedFiles.length + selectedFolders.length} selected
            </div>
          </div>

          <div className="h-72">
            <TableContainer
              ref={scrollContainerRef}
              height="288px"
              className="scrollbar-thin  md:w-4xl lg:w-5xl"
              bordered={false}
            >
              {(
                <>
                  <Table minWidth="1200px">
                    <TableHead>
                      <TableRow>
                        <TableHeader width="40px"></TableHeader>
                        <TableHeader width="60%">Name</TableHeader>
                        <TableHeader width="20%">Last Modified</TableHeader>
                        <TableHeader width="20%">Size</TableHeader>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {files.map((file, index) => (
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
                              className="flex h-5 w-5 text-sm shrink-0 items-center justify-center border border-[#EEE6FF78] p-[0.5px] dark:border-[#6A6A6A] cursor-pointer mx-auto"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleFileSelect(file.id, isFolder(file));
                              }}
                            >
                              {(isFolder(file) ? selectedFolders : selectedFiles).includes(file.id) && (
                                <img
                                  src={CheckIcon}
                                  alt="Selected"
                                  className="h-4 w-4"
                                />
                              )}
                            </div>
                          </TableCell>
                          <TableCell>
                            <div className="flex items-center gap-3 min-w-0">
                              <div className="flex-shrink-0">
                                <img
                                  src={isFolder(file) ? FolderIcon : FileIcon}
                                  alt={isFolder(file) ? "Folder" : "File"}
                                  className="h-6 w-6"
                                />
                              </div>
                              <span className="truncate">{file.name}</span>
                            </div>
                          </TableCell>
                          <TableCell className='text-xs'>
                            {formatDate(file.modifiedTime)}
                          </TableCell>
                          <TableCell className='text-xs'>
                            {file.size ? formatBytes(file.size) : '-'}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>

                  {isLoading && (
                    <div className="flex items-center justify-center p-4 border-t border-[#EEE6FF78] dark:border-[#6A6A6A]">
                      <div className="inline-flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400">
                        <div className="h-4 w-4 animate-spin rounded-full border-2 border-blue-500 border-t-transparent"></div>
                        Loading more files...
                      </div>
                    </div>
                  )}
                </>
              )}
            </TableContainer>
          </div>
        </div>
      </div>
    </div>
  );
};
