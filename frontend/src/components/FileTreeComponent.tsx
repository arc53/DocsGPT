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

    let current: any = directoryStructure;
    for (const dir of currentPath) {
      if (current[dir] && !current[dir].type) {
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
    itemId: string,
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
        console.log('Delete item:', name);
        // Delete action will be implemented later
      },
      iconWidth: 18,
      iconHeight: 18,
      variant: 'danger',
    });

    return options;
  };

  const renderPathNavigation = () => {
    return (
      <div className="mb-4 flex items-center text-sm">
        <button
          className="mr-3 flex h-[29px] w-[29px] items-center justify-center rounded-full border p-2 text-sm text-gray-400 dark:border-0 dark:bg-[#28292D] dark:text-gray-500 dark:hover:bg-[#2E2F34]"
          onClick={handleBackNavigation}
        >
          <img src={ArrowLeft} alt="left-arrow" className="h-3 w-3" />
        </button>

        <div className="flex items-center">
          <img src={OutlineSource} alt="source" className="mr-2 h-5 w-5" />
          <span className="text-purple-30 font-medium">{sourceName}</span>
          {currentPath.length > 0 && (
            <>
              <span className="mx-1 text-gray-500">/</span>
              {currentPath.map((dir, index) => (
                <React.Fragment key={index}>
                  <span className="text-gray-700 dark:text-gray-300">
                    {dir}
                  </span>
                  {index < currentPath.length - 1 && (
                    <span className="mx-1 text-gray-500">/</span>
                  )}
                </React.Fragment>
              ))}
            </>
          )}
          {selectedFile && (
            <>
              <span className="mx-1 text-gray-500">/</span>
              <span className="text-gray-700 dark:text-gray-300">
                {selectedFile.name}
              </span>
            </>
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
          <tr
            key="parent-dir"
            className="cursor-pointer border-b border-[#D1D9E0] hover:bg-[#ECEEEF] dark:border-[#6A6A6A] dark:hover:bg-[#27282D]"
            onClick={navigateUp}
          >
            <td className="px-4 py-2">
              <div className="flex items-center">
                <img
                  src={FolderIcon}
                  alt="Parent folder"
                  className="mr-2 h-4 w-4"
                />
                <span className="text-sm dark:text-[#E0E0E0]">..</span>
              </div>
            </td>
            <td className="px-4 py-2 text-sm dark:text-[#E0E0E0]">-</td>
            <td className="px-4 py-2 text-sm dark:text-[#E0E0E0]">-</td>
            <td className="w-10 px-4 py-2 text-sm"></td>
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
            <td className="px-4 py-2">
              <div className="flex items-center">
                <img src={FolderIcon} alt="Folder" className="mr-2 h-4 w-4" />
                <span className="text-sm dark:text-[#E0E0E0]">{name}</span>
              </div>
            </td>
            <td className="px-4 py-2 text-sm dark:text-[#E0E0E0]">
              {dirStats.totalTokens > 0
                ? dirStats.totalTokens.toLocaleString()
                : '-'}
            </td>
            <td className="px-4 py-2 text-sm dark:text-[#E0E0E0]">
              {dirStats.totalSize > 0 ? formatBytes(dirStats.totalSize) : '-'}
            </td>
            <td className="w-10 px-4 py-2 text-sm">
              <div ref={menuRef} className="relative">
                <button
                  onClick={(e) => handleMenuClick(e, itemId)}
                  className="inline-flex h-[35px] w-[24px] shrink-0 items-center justify-center rounded-md transition-colors hover:bg-[#EBEBEB] dark:hover:bg-[#26272E]"
                  aria-label="Open menu"
                >
                  <img
                    src={ThreeDots}
                    alt="Menu"
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
                  offset={{ x: 0, y: 8 }}
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
            <td className="px-4 py-2">
              <div className="flex items-center">
                <img src={FileIcon} alt="File" className="mr-2 h-4 w-4" />
                <span className="text-sm dark:text-[#E0E0E0]">{name}</span>
              </div>
            </td>
            <td className="px-4 py-2 text-sm dark:text-[#E0E0E0]">
              {node.token_count?.toLocaleString() || '-'}
            </td>
            <td className="px-4 py-2 text-sm dark:text-[#E0E0E0]">
              {node.size_bytes ? formatBytes(node.size_bytes) : '-'}
            </td>
            <td className="w-10 px-4 py-2 text-sm">
              <div ref={menuRef} className="relative">
                <button
                  onClick={(e) => handleMenuClick(e, itemId)}
                  className="inline-flex h-[35px] w-[24px] shrink-0 items-center justify-center rounded-md transition-colors hover:bg-[#EBEBEB] dark:hover:bg-[#26272E]"
                  aria-label="Open menu"
                >
                  <img
                    src={ThreeDots}
                    alt="Menu"
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
                  offset={{ x: 0, y: 8 }}
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


  return (
    <>
      <div className="mb-4">{renderPathNavigation()}</div>
      {selectedFile ? (
        <div className="flex">
          {/* Search Panel */}
          <div className="w-[283px] min-w-[283px] pr-4">
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
                className={`w-full px-4 py-2 pl-10 border border-[#D1D9E0] dark:border-[#6A6A6A] ${searchQuery ? 'rounded-t-md rounded-b-none border-b-0' : 'rounded-md'
                  } bg-transparent dark:text-[#E0E0E0] focus:outline-none`}
              />

              <img
                src={SearchIcon}
                alt="Search"
                className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 opacity-60"
              />

              {searchQuery && (
                <div className="absolute z-10 w-full border border-[#D1D9E0] dark:border-[#6A6A6A] rounded-b-md bg-white dark:bg-[#1F2023] shadow-lg max-h-[calc(100vh-200px)] overflow-y-auto">
                  {searchResults.map((result, index) => {
                    const name = result.path.split('/').pop() || result.path;

                    return (
                      <div
                        key={index}
                        onClick={() => handleSearchSelect(result)}
                        title={result.path}
                        className={`flex items-center px-3 py-2 cursor-pointer hover:bg-[#ECEEEF] dark:hover:bg-[#27282D] ${index !== searchResults.length - 1 ? "border-b border-[#D1D9E0] dark:border-[#6A6A6A]" : ""
                          }`}
                      >
                        <img
                          src={result.isFile ? FileIcon : FolderIcon}
                          alt={result.isFile ? "File" : "Folder"}
                          className="flex-shrink-0 w-4 h-4 mr-2"
                        />
                        <span className="text-sm dark:text-[#E0E0E0]">
                          {name}
                        </span>
                      </div>
                    );
                  })}
                  {searchResults.length === 0 && (
                    <div className="text-sm text-gray-500 dark:text-gray-400 text-center py-2">
                      {t('settings.documents.noResults')}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
          <div className="flex-1 pl-4 pt-0">
            <DocumentChunks
              documentId={docId}
              documentName={sourceName}
              handleGoBack={() => setSelectedFile(null)}
              path={selectedFile.id}
              showHeader={false}
            />
          </div>
        </div>
      ) : (
        <div className="mt-8 flex flex-col">
          <div className="overflow-x-auto rounded-[6px] border border-[#D1D9E0] dark:border-[#6A6A6A]">
            <table className="min-w-full table-fixed bg-transparent">
              <thead className="bg-gray-100 dark:bg-[#27282D]">
                <tr className="border-b border-[#D1D9E0] dark:border-[#6A6A6A]">
                  <th className="w-3/5 px-4 py-3 text-left text-sm font-medium text-gray-700 dark:text-[#59636E]">
                    Name
                  </th>
                  <th className="w-1/5 px-4 py-3 text-left text-sm font-medium text-gray-700 dark:text-[#59636E]">
                    Tokens
                  </th>
                  <th className="w-1/5 px-4 py-3 text-left text-sm font-medium text-gray-700 dark:text-[#59636E]">
                    Size
                  </th>
                  <th className="w-[60px] px-4 py-3 text-left text-sm font-medium text-gray-700 dark:text-[#59636E]">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody className="[&>tr:last-child]:border-b-0">
                {renderFileTree(currentDirectory)}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
};

export default FileTreeComponent;

