import React, { useState, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import DocumentChunks from './DocumentChunks';
import ContextMenu, { MenuOption } from './ContextMenu';
import userService from '../api/services/userService';
import FileIcon from '../assets/file.svg';
import FolderIcon from '../assets/folder.svg';
import ArrowLeft from '../assets/arrow-left.svg';
import ThreeDots from '../assets/three-dots.svg';
import EyeView from '../assets/eye-view.svg';
import OutlineSource from '../assets/outline-source.svg';
import Trash from '../assets/red-trash.svg';
import SearchIcon from '../assets/search.svg';
import { useOutsideAlerter } from '../hooks';
import ConfirmationModal from '../modals/ConfirmationModal';

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
  onBackToDocuments?: () => void;
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
  const token = useSelector((state: any) => state.auth?.token);
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
  const currentOpRef = useRef<null | 'add' | 'remove' | 'remove_directory'>(null);

  const [deleteModalState, setDeleteModalState] = useState<'ACTIVE' | 'INACTIVE'>('INACTIVE');
  const [itemToDelete, setItemToDelete] = useState<{ name: string; isFile: boolean } | null>(null);

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
    false
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

  const formatBytes = (bytes: number): string => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

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
        console.error('Error parsing directory structure in getCurrentDirectory:', e);
        return {};
      }
    }

    if (typeof structure !== 'object' || structure === null) {
      return {};
    }

    let current: any = structure;
    for (const dir of currentPath) {
      if (current[dir] && typeof current[dir] === 'object' && !current[dir].type) {
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

    if (isFile) {
      options.push({
        icon: EyeView,
        label: t('settings.documents.view'),
        onClick: (event: React.SyntheticEvent) => {
          event.stopPropagation();
          handleFileClick(name);
        },
        iconWidth: 18,
        iconHeight: 18,
        variant: 'primary',
      });
    }

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
          console.log('Directory deleted successfully:', result.removed_directory);
        }
        console.log('Reingest task started:', result.reingest_task_id);
        
        const maxAttempts = 30;
        const pollInterval = 2000;
        
        for (let attempt = 0; attempt < maxAttempts; attempt++) {
          try {
            const statusResponse = await userService.getTaskStatus(result.reingest_task_id, token);
            const statusData = await statusResponse.json();
            
            console.log(`Task status (attempt ${attempt + 1}):`, statusData.status);
            
            if (statusData.status === 'SUCCESS') {
              console.log('Task completed successfully');
              
              const structureResponse = await userService.getDirectoryStructure(docId, token);
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
            
            await new Promise(resolve => setTimeout(resolve, pollInterval));
          } catch (error) {
            console.error('Error polling task status:', error);
            break;
          }
        }
      } else {
        throw new Error(`Failed to ${operation} ${operation === 'remove_directory' ? 'directory' : 'file(s)'}`);
      }
    } catch (error) {
      const actionText = operation === 'add' ? 'uploading' : operation === 'remove_directory' ? 'deleting directory' : 'deleting file(s)';
      const errorText = operation === 'add' ? 'upload' : operation === 'remove_directory' ? 'delete directory' : 'delete file(s)';
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
    fileInput.accept = '.rst,.md,.pdf,.txt,.docx,.csv,.epub,.html,.mdx,.json,.xlsx,.pptx,.png,.jpg,.jpeg';

    fileInput.onchange = async (event) => {
      const fileList = (event.target as HTMLInputElement).files;
      if (!fileList || fileList.length === 0) return;
      const files = Array.from(fileList);
      enqueueOperation({ operation: 'add', files, parentDirPath: currentPath.join('/') });
    };

    fileInput.click();
  };

  const handleDeleteFile = async (name: string, isFile: boolean) => {
    // Construct the full path to the file or directory
    const itemPath = [...currentPath, name].join('/');

    if (isFile) {
      enqueueOperation({ operation: 'remove', filePath: itemPath });
    } else {
      enqueueOperation({ operation: 'remove_directory', directoryPath: itemPath });
    }
  };

  const renderPathNavigation = () => {
    return (
      <div className="mb-4 flex flex-col sm:flex-row sm:items-center sm:justify-between text-sm gap-3">
        <div className="flex items-center w-full sm:w-auto">
          <button
            className="mr-3 flex h-[29px] w-[29px] items-center justify-center rounded-full border p-2 text-sm text-gray-400 dark:border-0 dark:bg-[#28292D] dark:text-gray-500 dark:hover:bg-[#2E2F34]"
            onClick={handleBackNavigation}
          >
            <img src={ArrowLeft} alt="left-arrow" className="h-3 w-3" />
          </button>

          <div className="flex items-center flex-wrap">
            <img src={OutlineSource} alt="source" className="mr-2 h-5 w-5 flex-shrink-0" />
            <span className="text-purple-30 font-medium break-words">{sourceName}</span>
            {currentPath.length > 0 && (
              <>
                <span className="mx-1 text-gray-500 flex-shrink-0">/</span>
                {currentPath.map((dir, index) => (
                  <React.Fragment key={index}>
                    <span className="text-gray-700 dark:text-gray-300 break-words">
                      {dir}
                    </span>
                    {index < currentPath.length - 1 && (
                      <span className="mx-1 text-gray-500 flex-shrink-0">/</span>
                    )}
                  </React.Fragment>
                ))}
              </>
            )}
            {selectedFile && (
              <>
                <span className="mx-1 text-gray-500 flex-shrink-0">/</span>
                <span className="text-gray-700 dark:text-gray-300 break-words">
                  {selectedFile.name}
                </span>
              </>
            )}
          </div>
        </div>

        {!selectedFile && (
          <div className="flex items-center gap-2 w-full sm:w-auto">
            {(processingRef.current || queueLength > 0) && (
              <span className="text-xs text-gray-600 dark:text-gray-400">
                {processingRef.current ? (currentOpRef.current === 'add' ? 'Uploading…' : 'Deleting…') : null}
                {queueLength > 0 ? `${processingRef.current ? ' • ' : ''}Queued: ${queueLength}` : ''}
              </span>
            )}
            <button
              onClick={handleAddFile}
              className="bg-purple-30 hover:bg-violets-are-blue flex h-[32px] w-full sm:w-auto min-w-[108px] items-center justify-center rounded-full px-4 text-sm whitespace-normal text-white"
              title={processingRef.current ? (currentOpRef.current === 'add' ? 'Uploading files...' : 'Deleting...') : 'Add file'}
            >
              Add file
            </button>
          </div>
        )}
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
          <tr
            key="parent-dir"
            className="cursor-pointer border-b border-[#D1D9E0] hover:bg-[#ECEEEF] dark:border-[#6A6A6A] dark:hover:bg-[#27282D]"
            onClick={navigateUp}
          >
            <td className="px-2 lg:px-4 py-2">
              <div className="flex items-center">
                <img
                  src={FolderIcon}
                  alt={t('settings.documents.parentFolderAlt')}
                  className="mr-2 h-4 w-4 flex-shrink-0"
                />
                <span className="text-sm dark:text-[#E0E0E0] truncate">..</span>
              </div>
            </td>
            <td className="px-2 lg:px-4 py-2 text-sm dark:text-[#E0E0E0]">-</td>
            <td className="px-2 lg:px-4 py-2 text-sm dark:text-[#E0E0E0]">-</td>
            <td className="w-10 px-2 lg:px-4 py-2 text-sm"></td>
          </tr>,
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
          <tr
            key={itemId}
            className="cursor-pointer border-b border-[#D1D9E0] hover:bg-[#ECEEEF] dark:border-[#6A6A6A] dark:hover:bg-[#27282D]"
            onClick={() => navigateToDirectory(name)}
          >
            <td className="px-2 lg:px-4 py-2">
              <div className="flex items-center min-w-0">
                <img src={FolderIcon} alt={t('settings.documents.folderAlt')} className="mr-2 h-4 w-4 flex-shrink-0" />
                <span className="text-sm dark:text-[#E0E0E0] truncate">{name}</span>
              </div>
            </td>
            <td className="px-2 lg:px-4 py-2 text-sm dark:text-[#E0E0E0]">
              {dirStats.totalTokens > 0
                ? dirStats.totalTokens.toLocaleString()
                : '-'}
            </td>
            <td className="px-2 lg:px-4 py-2 text-sm dark:text-[#E0E0E0]">
              {dirStats.totalSize > 0 ? formatBytes(dirStats.totalSize) : '-'}
            </td>
            <td className="w-10 px-2 lg:px-4 py-2 text-sm">
              <div ref={menuRef} className="relative">
                <button
                  onClick={(e) => handleMenuClick(e, itemId)}
                  className="inline-flex h-[35px] w-[24px] shrink-0 items-center justify-center rounded-md transition-colors hover:bg-[#EBEBEB] dark:hover:bg-[#26272E]"
                  aria-label="Open menu"
                >
                  <img
                    src={ThreeDots}
                    alt={t('settings.documents.menuAlt')}
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
                  offset={{ x: -8, y: 8 }}
                />
              </div>
            </td>
          </tr>
        );
      }),
      ...files.map(([name, node]) => {
        const itemId = `file-${name}`;
        const menuRef = getMenuRef(itemId);

        return (
          <tr
            key={itemId}
            className="cursor-pointer border-b border-[#D1D9E0] hover:bg-[#ECEEEF] dark:border-[#6A6A6A] dark:hover:bg-[#27282D]"
            onClick={() => handleFileClick(name)}
          >
            <td className="px-2 lg:px-4 py-2">
              <div className="flex items-center min-w-0">
                <img src={FileIcon} alt={t('settings.documents.fileAlt')} className="mr-2 h-4 w-4 flex-shrink-0" />
                <span className="text-sm dark:text-[#E0E0E0] truncate">{name}</span>
              </div>
            </td>
            <td className="px-2 lg:px-4 py-2 text-sm dark:text-[#E0E0E0]">
              {node.token_count?.toLocaleString() || '-'}
            </td>
            <td className="px-2 md:px-4 py-2 text-sm dark:text-[#E0E0E0]">
              {node.size_bytes ? formatBytes(node.size_bytes) : '-'}
            </td>
            <td className="w-10 px-2 lg:px-4 py-2 text-sm">
              <div ref={menuRef} className="relative">
                <button
                  onClick={(e) => handleMenuClick(e, itemId)}
                  className="inline-flex h-[35px] w-[24px] shrink-0 items-center justify-center rounded-md transition-colors hover:bg-[#EBEBEB] dark:hover:bg-[#26272E]"
                  aria-label="Open menu"
                >
                  <img
                    src={ThreeDots}
                    alt={t('settings.documents.menuAlt')}
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
                  offset={{ x: -8, y: 8 }}
                />
              </div>
            </td>
          </tr>
        );
      }),
    ];
  };
  const currentDirectory = getCurrentDirectory();

  const searchFiles = (query: string, structure: DirectoryStructure, currentPath: string[] = []): SearchResult[] => {
    let results: SearchResult[] = [];

    Object.entries(structure).forEach(([name, node]) => {
      const fullPath = [...currentPath, name].join('/');

      if (name.toLowerCase().includes(query.toLowerCase())) {
        results.push({
          name,
          path: fullPath,
          isFile: !!node.type
        });
      }

      if (!node.type) {
        // If it's a directory, search recursively
        results = [...results, ...searchFiles(query, node as DirectoryStructure, [...currentPath, name])];
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
        name: fileName
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
      <div className="w-[283px]" ref={searchDropdownRef}>
        <div className="relative">
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => {
              setSearchQuery(e.target.value);
              if (directoryStructure) {
                setSearchResults(searchFiles(e.target.value, directoryStructure));
              }
            }}
            placeholder={t('settings.documents.searchFiles')}
            className={`w-full px-4 py-2 pl-10 border border-[#D1D9E0] dark:border-[#6A6A6A] ${
              searchQuery ? 'rounded-t-md rounded-b-none border-b-0' : 'rounded-md'
            } bg-transparent dark:text-[#E0E0E0] focus:outline-none`}
          />

          <img
            src={SearchIcon}
            alt="Search"
            className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 opacity-60"
          />

          {searchQuery && (
            <div className="absolute z-10 w-full border border-[#D1D9E0] dark:border-[#6A6A6A] rounded-b-md bg-white dark:bg-[#1F2023] shadow-lg max-h-[calc(100vh-200px)] overflow-y-auto">
              {searchResults.length === 0 ? (
                <div className="text-sm text-gray-500 dark:text-gray-400 text-center py-2">
                  {t('settings.documents.noResults')}
                </div>
              ) : (
                searchResults.map((result, index) => (
                  <div
                    key={index}
                    onClick={() => handleSearchSelect(result)}
                    title={result.path}
                    className={`flex items-center px-3 py-2 cursor-pointer hover:bg-[#ECEEEF] dark:hover:bg-[#27282D] ${
                      index !== searchResults.length - 1 ? "border-b border-[#D1D9E0] dark:border-[#6A6A6A]" : ""
                    }`}
                  >
                    <img
                      src={result.isFile ? FileIcon : FolderIcon}
                      alt={result.isFile ? t('settings.documents.fileAlt') : t('settings.documents.folderAlt')}
                      className="flex-shrink-0 w-4 h-4 mr-2"
                    />
                    <span className="text-sm dark:text-[#E0E0E0]">
                      {result.path.split('/').pop() || result.path}
                    </span>
                  </div>
                ))
              )}
            </div>
          )}
        </div>
      </div>
    );
  };

  return (
    <div>
      {selectedFile ? (
        <div className="flex">
          <div className="flex-1">
            <DocumentChunks
              documentId={docId}
              documentName={sourceName}
              handleGoBack={() => setSelectedFile(null)}
              path={selectedFile.id}
              renderFileSearch={renderFileSearch}
            />
          </div>
        </div>
      ) : (
        <div className="flex flex-col w-full max-w-full overflow-hidden">
          <div className="mb-4">
            {renderPathNavigation()}
          </div>

          <div className="flex gap-4 min-w-0">
            {/* Left side: Search dropdown */}
            <div className="hidden lg:block flex-shrink-0">
              {renderFileSearch()}
            </div>

            {/* Right side: File table */}
            <div className="flex-1 min-w-0">
              <div className="overflow-x-auto rounded-[6px] border border-[#D1D9E0] dark:border-[#6A6A6A]">
                <table className="w-full table-auto bg-transparent min-w-[600px]">
                  <thead className="bg-gray-100 dark:bg-[#27282D]">
                    <tr className="border-b border-[#D1D9E0] dark:border-[#6A6A6A]">
                      <th className="min-w-[200px] px-2 lg:px-4 py-3 text-left text-sm font-medium text-gray-700 dark:text-[#59636E]">
                        {t('settings.documents.fileName')}
                      </th>
                      <th className="min-w-[80px] px-2 lg:px-4 py-3 text-left text-sm font-medium text-gray-700 dark:text-[#59636E]">
                        {t('settings.documents.tokens')}
                      </th>
                      <th className="min-w-[80px] px-2 lg:px-4 py-3 text-left text-sm font-medium text-gray-700 dark:text-[#59636E]">
                        {t('settings.documents.size')}
                      </th>
                      <th className="w-[60px] px-2 lg:px-4 py-3 text-left text-sm font-medium text-gray-700 dark:text-[#59636E]">
                        <span className="sr-only">{t('settings.documents.actions')}</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody className="[&>tr:last-child]:border-b-0">
                    {renderFileTree(currentDirectory)}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      )}
      <ConfirmationModal
        message={
          itemToDelete?.isFile
            ? t('settings.documents.confirmDelete')
            : `Are you sure you want to delete the directory "${itemToDelete?.name}" and all its contents? This action cannot be undone.`
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

