import React, { useState, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { selectToken } from '../preferences/preferenceSlice';
import { formatBytes } from '../utils/stringUtils';
import Chunks from './Chunks';
import ContextMenu, { MenuOption } from './ContextMenu';
import userService from '../api/services/userService';
import FileIcon from '../assets/file.svg';
import FolderIcon from '../assets/folder.svg';
import ArrowLeft from '../assets/arrow-left.svg';
import ThreeDots from '../assets/three-dots.svg';
import EyeView from '../assets/eye-view.svg';
import Trash from '../assets/red-trash.svg';
import { useOutsideAlerter } from '../hooks';
import ConfirmationModal from '../modals/ConfirmationModal';
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

interface FileTreeComponentProps {
  docId: string;
  sourceName: string;
  onBackToDocuments: () => void;
}

interface SearchResult {
  name: string;
  path: string;
  isFile: boolean;
}

const FileTreeComponent: React.FC<FileTreeComponentProps> = ({
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
  const currentOpRef = useRef<null | 'add' | 'remove' | 'remove_directory'>(
    null,
  );

  const [deleteModalState, setDeleteModalState] = useState<
    'ACTIVE' | 'INACTIVE'
  >('INACTIVE');
  const [itemToDelete, setItemToDelete] = useState<{
    name: string;
    isFile: boolean;
  } | null>(null);

  type QueuedOperation = {
    operation: 'add' | 'remove' | 'remove_directory';
    files?: File[];
    filePath?: string;
    directoryPath?: string;
    parentDirPath?: string;
  };
  const opQueueRef = useRef<QueuedOperation[]>([]);
  const processingRef = useRef(false);
  const [queueLength, setQueueLength] = useState(0);

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

  useEffect(() => {
    const fetchDirectoryStructure = async () => {
      try {
        setLoading(true);
        const response = await userService.getDirectoryStructure(docId, token);
        const data = await response.json();

        if (data && data.directory_structure) {
          setDirectoryStructure(data.directory_structure);
        } else {
          setError('Invalid response format');
        }
      } catch (err) {
        setError('Failed to load directory structure');
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
    setCurrentPath((prev) => [...prev, dirName]);
  };

  const navigateUp = () => {
    setCurrentPath((prev) => prev.slice(0, -1));
  };

  const getCurrentDirectory = (): DirectoryStructure => {
    if (!directoryStructure) return {};

    let structure = directoryStructure;
    if (typeof structure === 'string') {
      try {
        structure = JSON.parse(structure);
      } catch (e) {
        console.error(
          'Error parsing directory structure in getCurrentDirectory:',
          e,
        );
        return {};
      }
    }

    if (typeof structure !== 'object' || structure === null) {
      return {};
    }

    let current: any = structure;
    for (const dir of currentPath) {
      if (
        current[dir] &&
        typeof current[dir] === 'object' &&
        !current[dir].type
      ) {
        current = current[dir];
      } else {
        return {};
      }
    }
    return current;
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

  const getMenuRef = (itemId: string) => {
    if (!menuRefs.current[itemId]) {
      menuRefs.current[itemId] = React.createRef<HTMLDivElement>();
    }
    return menuRefs.current[itemId];
  };

  const handleMenuClick = (e: React.MouseEvent, itemId: string) => {
    e.preventDefault();
    e.stopPropagation();

    if (activeMenuId === itemId) {
      setActiveMenuId(null);
      return;
    }
    setActiveMenuId(itemId);
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

    options.push({
      icon: Trash,
      label: t('convTile.delete'),
      onClick: (event: React.SyntheticEvent) => {
        event.stopPropagation();
        confirmDeleteItem(name, isFile);
      },
      iconWidth: 18,
      iconHeight: 18,
      variant: 'danger',
    });

    return options;
  };

  const confirmDeleteItem = (name: string, isFile: boolean) => {
    setItemToDelete({ name, isFile });
    setDeleteModalState('ACTIVE');
    setActiveMenuId(null);
  };

  const handleConfirmedDelete = async () => {
    if (itemToDelete) {
      await handleDeleteFile(itemToDelete.name, itemToDelete.isFile);
      setDeleteModalState('INACTIVE');
      setItemToDelete(null);
    }
  };

  const handleCancelDelete = () => {
    setDeleteModalState('INACTIVE');
    setItemToDelete(null);
  };

  const manageSource = async (
    operation: 'add' | 'remove' | 'remove_directory',
    files?: File[] | null,
    filePath?: string,
    directoryPath?: string,
    parentDirPath?: string,
  ) => {
    currentOpRef.current = operation;

    try {
      const formData = new FormData();
      formData.append('source_id', docId);
      formData.append('operation', operation);

      if (operation === 'add' && files && files.length) {
        formData.append('parent_dir', parentDirPath ?? currentPath.join('/'));

        for (let i = 0; i < files.length; i++) {
          formData.append('file', files[i]);
        }
      } else if (operation === 'remove' && filePath) {
        const filePaths = JSON.stringify([filePath]);
        formData.append('file_paths', filePaths);
      } else if (operation === 'remove_directory' && directoryPath) {
        formData.append('directory_path', directoryPath);
      }

      const response = await userService.manageSourceFiles(formData, token);
      const result = await response.json();

      if (result.success && result.reingest_task_id) {
        if (operation === 'add') {
          console.log('Files uploaded successfully:', result.added_files);
        } else if (operation === 'remove') {
          console.log('Files deleted successfully:', result.removed_files);
        } else if (operation === 'remove_directory') {
          console.log(
            'Directory deleted successfully:',
            result.removed_directory,
          );
        }
        console.log('Reingest task started:', result.reingest_task_id);

        const maxAttempts = 30;
        const pollInterval = 2000;

        for (let attempt = 0; attempt < maxAttempts; attempt++) {
          try {
            const statusResponse = await userService.getTaskStatus(
              result.reingest_task_id,
              token,
            );
            const statusData = await statusResponse.json();

            console.log(
              `Task status (attempt ${attempt + 1}):`,
              statusData.status,
            );

            if (statusData.status === 'SUCCESS') {
              console.log('Task completed successfully');

              const structureResponse = await userService.getDirectoryStructure(
                docId,
                token,
              );
              const structureData = await structureResponse.json();

              if (structureData && structureData.directory_structure) {
                setDirectoryStructure(structureData.directory_structure);
                currentOpRef.current = null;
                return true;
              }
              break;
            } else if (statusData.status === 'FAILURE') {
              console.error('Task failed');
              break;
            }

            await new Promise((resolve) => setTimeout(resolve, pollInterval));
          } catch (error) {
            console.error('Error polling task status:', error);
            break;
          }
        }
      } else {
        throw new Error(
          `Failed to ${operation} ${operation === 'remove_directory' ? 'directory' : 'file(s)'}`,
        );
      }
    } catch (error) {
      const actionText =
        operation === 'add'
          ? 'uploading'
          : operation === 'remove_directory'
            ? 'deleting directory'
            : 'deleting file(s)';
      const errorText =
        operation === 'add'
          ? 'upload'
          : operation === 'remove_directory'
            ? 'delete directory'
            : 'delete file(s)';
      console.error(`Error ${actionText}:`, error);
      setError(`Failed to ${errorText}`);
    } finally {
      currentOpRef.current = null;
    }

    return false;
  };

  const processQueue = async () => {
    if (processingRef.current) return;
    processingRef.current = true;
    try {
      while (opQueueRef.current.length > 0) {
        const nextOp = opQueueRef.current.shift()!;
        setQueueLength(opQueueRef.current.length);
        await manageSource(
          nextOp.operation,
          nextOp.files,
          nextOp.filePath,
          nextOp.directoryPath,
          nextOp.parentDirPath,
        );
      }
    } finally {
      processingRef.current = false;
    }
  };

  const enqueueOperation = (op: QueuedOperation) => {
    opQueueRef.current.push(op);
    setQueueLength(opQueueRef.current.length);
    if (!processingRef.current) {
      void processQueue();
    }
  };

  const handleAddFile = () => {
    const fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.multiple = true;
    fileInput.accept =
      '.rst,.md,.pdf,.txt,.docx,.csv,.epub,.html,.mdx,.json,.xlsx,.pptx,.png,.jpg,.jpeg';

    fileInput.onchange = async (event) => {
      const fileList = (event.target as HTMLInputElement).files;
      if (!fileList || fileList.length === 0) return;
      const files = Array.from(fileList);
      enqueueOperation({
        operation: 'add',
        files,
        parentDirPath: currentPath.join('/'),
      });
    };

    fileInput.click();
  };

  const handleDeleteFile = async (name: string, isFile: boolean) => {
    // Construct the full path to the file or directory
    const itemPath = [...currentPath, name].join('/');

    if (isFile) {
      enqueueOperation({ operation: 'remove', filePath: itemPath });
    } else {
      enqueueOperation({
        operation: 'remove_directory',
        directoryPath: itemPath,
      });
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
                    <span className="break-words text-gray-700 dark:text-gray-300">
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
            {selectedFile && (
              <>
                <span className="mx-1 flex-shrink-0 text-gray-500">/</span>
                <span className="break-words text-gray-700 dark:text-gray-300">
                  {selectedFile.name}
                </span>
              </>
            )}
          </div>
        </div>

        <div className="relative mt-2 flex w-full flex-row flex-nowrap items-center justify-end gap-2 sm:mt-0 sm:w-auto">
          {processingRef.current && (
            <div className="text-sm text-gray-500">
              {currentOpRef.current === 'add'
                ? t('settings.sources.uploadingFilesTitle')
                : t('settings.sources.deletingTitle')}
            </div>
          )}

          {renderFileSearch()}

          {/* Add file button */}
          {!processingRef.current && (
            <button
              onClick={handleAddFile}
              className="bg-purple-30 hover:bg-violets-are-blue flex h-[38px] min-w-[108px] items-center justify-center rounded-full px-4 text-[14px] font-medium whitespace-nowrap text-white"
              title={t('settings.sources.addFile')}
            >
              {t('settings.sources.addFile')}
            </button>
          )}
        </div>
      </div>
    );
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

  const renderFileTree = (structure: DirectoryStructure): React.ReactNode[] => {
    // Separate directories and files
    const entries = Object.entries(structure);
    const directories = entries.filter(([_, node]) => !node.type);
    const files = entries.filter(([_, node]) => node.type);

    // Create parent directory row
    const parentRow =
      currentPath.length > 0
        ? [
          <TableRow
            key="parent-dir"
            onClick={navigateUp}
          >
            <TableCell width="40%" align="left">
              <div className="flex items-center">
                <img
                  src={FolderIcon}
                  alt={t('settings.sources.parentFolderAlt')}
                  className="mr-2 h-4 w-4 flex-shrink-0"
                />
                <span className="truncate">
                  ..
                </span>
              </div>
            </TableCell>
            <TableCell width="30%" align="left">
              -
            </TableCell>
            <TableCell width="20%" align="right">
              -
            </TableCell>
            <TableCell width="10%" align="right"></TableCell>
          </TableRow>,
        ]
        : [];

    // Render directories first, then files
    return [
      ...parentRow,
      ...directories.map(([name, node]) => {
        const itemId = `dir-${name}`;
        const menuRef = getMenuRef(itemId);
        const dirStats = calculateDirectoryStats(node as DirectoryStructure);

        return (
          <TableRow
            key={itemId}
            onClick={() => navigateToDirectory(name)}
          >
            <TableCell width="40%" align="left">
              <div className="flex min-w-0 items-center">
                <img
                  src={FolderIcon}
                  alt={t('settings.sources.folderAlt')}
                  className="mr-2 h-4 w-4 flex-shrink-0"
                />
                <span className="truncate">
                  {name}
                </span>
              </div>
            </TableCell>
            <TableCell width="30%" align="left">
              {dirStats.totalSize > 0 ? formatBytes(dirStats.totalSize) : '-'}
            </TableCell>
            <TableCell width="20%" align="right">
              {dirStats.totalTokens > 0
                ? dirStats.totalTokens.toLocaleString()
                : '-'}
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
      }),
      ...files.map(([name, node]) => {
        const itemId = `file-${name}`;
        const menuRef = getMenuRef(itemId);

        return (
          <TableRow
            key={itemId}
            onClick={() => handleFileClick(name)}
          >
            <TableCell width="40%" align="left">
              <div className="flex min-w-0 items-center">
                <img
                  src={FileIcon}
                  alt={t('settings.sources.fileAlt')}
                  className="mr-2 h-4 w-4 flex-shrink-0"
                />
                <span className="truncate">
                  {name}
                </span>
              </div>
            </TableCell>
            <TableCell width="30%" align="left">
              {node.size_bytes ? formatBytes(node.size_bytes) : '-'}
            </TableCell>
            <TableCell width="20%" align="right">
              {node.token_count?.toLocaleString() || '-'}
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
      }),
    ];
  };
  const currentDirectory = getCurrentDirectory();

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
                      {t('settings.sources.size')}
                    </TableHeader>
                    <TableHeader width="20%" align="right">
                      {t('settings.sources.tokens')}
                    </TableHeader>
                    <TableHeader width="10%" align="right">
                      <span className="sr-only">
                        {t('settings.sources.actions')}
                      </span>
                    </TableHeader>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {renderFileTree(currentDirectory)}
                </TableBody>
              </Table>
            </TableContainer>
          </div>
        </div>
      )}
      <ConfirmationModal
        message={
          itemToDelete?.isFile
            ? t('settings.sources.confirmDelete')
            : t('settings.sources.deleteDirectoryWarning', {
                name: itemToDelete?.name,
              })
        }
        modalState={deleteModalState}
        setModalState={setDeleteModalState}
        handleSubmit={handleConfirmedDelete}
        handleCancel={handleCancelDelete}
        submitLabel={t('convTile.delete')}
        variant="danger"
      />
    </div>
  );
};

export default FileTreeComponent;
