import React, { useState, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { selectToken } from '../preferences/preferenceSlice';
import Chunks from './Chunks';
import ContextMenu, { MenuOption } from './ContextMenu';
import userService from '../api/services/userService';
import FileIcon from '../assets/file.svg';
import FolderIcon from '../assets/folder.svg';
import ArrowLeft from '../assets/arrow-left.svg';
import ThreeDots from '../assets/three-dots.svg';
import EyeView from '../assets/eye-view.svg';
import { useOutsideAlerter } from '../hooks';

interface ConnectorFileNode {
  id: string;
  name: string;
  type: string;
  size: string;
  modifiedTime: string;
  token_count?: number;
  mimeType?: string;
  isFolder?: boolean;
}

interface ConnectorDirectoryStructure {
  [key: string]: ConnectorFileNode;
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
  id: string;
}

const ConnectorTree: React.FC<ConnectorTreeProps> = ({
  docId,
  sourceName,
  onBackToDocuments,
}) => {
  const { t } = useTranslation();
  const [directoryStructure, setDirectoryStructure] = useState<ConnectorDirectoryStructure | null>(null);
  const [currentPath, setCurrentPath] = useState<string[]>([]);
  const token = useSelector(selectToken);
  const [selectedFile, setSelectedFile] = useState<{ id: string; name: string } | null>(null);
  const [activeMenuId, setActiveMenuId] = useState<string | null>(null);
  const menuRefs = useRef<{ [key: string]: React.RefObject<HTMLDivElement | null> }>({});
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const searchDropdownRef = useRef<HTMLDivElement>(null);

  useOutsideAlerter(
    searchDropdownRef,
    () => {
      setSearchQuery('');
      setSearchResults([]);
    },
    [],
    false,
  );



  useEffect(() => {
    const fetchDirectoryStructure = async () => {
      try {
        const response = await userService.getDirectoryStructure(docId, token);
        const data = await response.json();

        if (data && data.directory_structure) {
          const structure: ConnectorDirectoryStructure = {};
          // Convert the directory structure to our format
          Object.entries(data.directory_structure).forEach(([key, value]: [string, any]) => {
            structure[key] = {
              id: key,
              name: key,
              type: value.type || 'file',
              size: value.size_bytes ? `${value.size_bytes} bytes` : '-',
              modifiedTime: '-',
              token_count: value.token_count,
              isFolder: !value.type,
            };
          });
          setDirectoryStructure(structure);

          // Update search results when directory structure changes
          if (searchQuery && structure) {
            setSearchResults(searchFiles(searchQuery, structure));
          }
        } else {
          // Handle invalid response format
          console.log('Invalid response format');
        }
      } catch (err) {
        console.error('Failed to load directory structure', err);
      }
    };

    if (docId) {
      fetchDirectoryStructure();
    }
  }, [docId, token, searchQuery]);

  const handleFileClick = (fileId: string, fileName: string) => {
    setSelectedFile({ id: fileId, name: fileName });
  };

  const navigateToDirectory = (_folderId: string, folderName: string) => {
    setCurrentPath(prev => [...prev, folderName]);
  };

  const navigateUp = () => {
    if (currentPath.length > 0) {
      setCurrentPath(prev => prev.slice(0, -1));
    }
  };

  const getCurrentDirectory = (): ConnectorDirectoryStructure => {
    return directoryStructure || {};
  };

  const searchFiles = (
    query: string,
    structure: ConnectorDirectoryStructure,
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
          id: node.id,
        });
      }

      if (!node.type) {
        // If it's a directory, search recursively
        results = [
          ...results,
          ...searchFiles(query, node as unknown as ConnectorDirectoryStructure, [
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
        id: result.id,
        name: fileName,
      });
    } else {
      setCurrentPath(result.path.split('/'));
      setSelectedFile(null);
    }
    setSearchQuery('');
    setSearchResults([]);
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
    id: string,
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
          handleFileClick(id, name);
        } else {
          navigateToDirectory(id, name);
        }
      },
      iconWidth: 18,
      iconHeight: 18,
      variant: 'primary',
    });

    // Remove delete option for connector files since they're not on our servers
    // Connector files will be managed through the main Google Drive integration

    return options;
  };



  const currentDirectory = getCurrentDirectory();

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
          className={`w-full h-[38px] border border-[#D1D9E0] px-4 py-2 dark:border-[#6A6A6A]
              ${searchQuery ? 'rounded-t-[24px]' : 'rounded-[24px]'}
              bg-transparent focus:outline-none dark:text-[#E0E0E0]`}
        />

        {searchQuery && (
          <div className="absolute top-full left-0 right-0 z-10 max-h-[calc(100vh-200px)] w-full overflow-hidden rounded-b-[12px] border border-t-0 border-[#D1D9E0] bg-white shadow-lg dark:border-[#6A6A6A] dark:bg-[#1F2023] transition-all duration-200">
            <div className="max-h-[calc(100vh-200px)] overflow-y-auto overflow-x-hidden overscroll-contain">
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
                    className={`flex min-w-0 cursor-pointer items-center px-3 py-2 hover:bg-[#ECEEEF] dark:hover:bg-[#27282D] ${index !== searchResults.length - 1
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
                    <span className="text-sm dark:text-[#E0E0E0] truncate flex-1">
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

  const renderConnectorFileTree = (structure: ConnectorDirectoryStructure): React.ReactNode[] => {
    const entries = Object.entries(structure);
    const directories = entries.filter(([_, node]) => node.isFolder);
    const files = entries.filter(([_, node]) => !node.isFolder);

    return [
      ...directories.map(([name, node]) => {
        const itemId = `dir-${node.id}`;
        const menuRef = getMenuRef(itemId);

        return (
          <tr
            key={itemId}
            className="cursor-pointer border-b border-[#D1D9E0] hover:bg-[#ECEEEF] dark:border-[#6A6A6A] dark:hover:bg-[#27282D]"
            onClick={() => navigateToDirectory(node.id, name)}
          >
            <td className="px-2 py-2 lg:px-4">
              <div className="flex min-w-0 items-center">
                <img
                  src={FolderIcon}
                  alt={t('settings.sources.folderAlt')}
                  className="mr-2 h-4 w-4 flex-shrink-0"
                />
                <span className="truncate text-sm dark:text-[#E0E0E0]">
                  {name}
                </span>
              </div>
            </td>
            <td className="px-2 py-2 text-sm lg:px-4 dark:text-[#E0E0E0]">
              -
            </td>
            <td className="px-2 py-2 text-sm lg:px-4 dark:text-[#E0E0E0]">
              {node.modifiedTime || '-'}
            </td>
            <td className="w-10 px-2 py-2 text-sm lg:px-4">
              <div ref={menuRef} className="relative">
                <button
                  onClick={(e) => handleMenuClick(e, itemId)}
                  className="inline-flex h-[35px] w-[24px] shrink-0 items-center justify-center rounded-md transition-colors hover:bg-[#EBEBEB] dark:hover:bg-[#26272E] font-medium"
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
                  options={getActionOptions(name, node.id, false, itemId)}
                  anchorRef={menuRef}
                  position="bottom-left"
                  offset={{ x: -4, y: 4 }}
                />
              </div>
            </td>
          </tr>
        );
      }),
      ...files.map(([name, node]) => {
        const itemId = `file-${node.id}`;
        const menuRef = getMenuRef(itemId);

        return (
          <tr
            key={itemId}
            className="cursor-pointer border-b border-[#D1D9E0] hover:bg-[#ECEEEF] dark:border-[#6A6A6A] dark:hover:bg-[#27282D]"
            onClick={() => handleFileClick(node.id, name)}
          >
            <td className="px-2 py-2 lg:px-4">
              <div className="flex min-w-0 items-center">
                <img
                  src={FileIcon}
                  alt={t('settings.sources.fileAlt')}
                  className="mr-2 h-4 w-4 flex-shrink-0"
                />
                <span className="truncate text-sm dark:text-[#E0E0E0]">
                  {name}
                </span>
              </div>
            </td>
            <td className="px-2 py-2 text-sm lg:px-4 dark:text-[#E0E0E0]">
              {node.token_count?.toLocaleString() || '-'}
            </td>
            <td className="px-2 py-2 text-sm md:px-4 dark:text-[#E0E0E0]">
              {node.size || '-'}
            </td>
            <td className="w-10 px-2 py-2 text-sm lg:px-4">
              <div ref={menuRef} className="relative">
                <button
                  onClick={(e) => handleMenuClick(e, itemId)}
                  className="inline-flex h-[35px] w-[24px] shrink-0 items-center justify-center rounded-md transition-colors hover:bg-[#EBEBEB] dark:hover:bg-[#26272E] font-medium"
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
                  options={getActionOptions(name, node.id, true, itemId)}
                  anchorRef={menuRef}
                  position="bottom-left"
                  offset={{ x: -4, y: 4 }}
                />
              </div>
            </td>
          </tr>
        );
      }),
    ];
  };

  const renderPathNavigation = () => {
    return (
      <div className="mb-0 min-h-[38px] flex flex-col gap-2 text-base sm:flex-row sm:items-center sm:justify-between">
        {/* Left side with path navigation */}
        <div className="flex w-full items-center sm:w-auto">
          <button
            className="mr-3 flex h-[29px] w-[29px] items-center justify-center rounded-full border p-2 text-sm text-gray-400 dark:border-0 dark:bg-[#28292D] dark:text-gray-500 dark:hover:bg-[#2E2F34] font-medium"
            onClick={handleBackNavigation}
          >
            <img src={ArrowLeft} alt="left-arrow" className="h-3 w-3" />
          </button>

          <div className="flex flex-wrap items-center">
            <span className="text-[#7D54D1] font-semibold break-words">
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

        {/* Right side with search */}
        <div className="flex relative flex-row flex-nowrap items-center gap-2 w-full sm:w-auto justify-end mt-2 sm:mt-0">
          {renderFileSearch()}
        </div>
      </div>
    );
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
            />
          </div>
        </div>
      ) : (
        <div className="flex w-full max-w-full flex-col overflow-hidden">
          <div className="mb-2">{renderPathNavigation()}</div>

          <div className="w-full">
            <div className="overflow-x-auto rounded-[6px] border border-[#D1D9E0] dark:border-[#6A6A6A]">
              <table className="w-full min-w-[600px] table-auto bg-transparent">
                <thead className="bg-gray-100 dark:bg-[#27282D]">
                  <tr className="border-b border-[#D1D9E0] dark:border-[#6A6A6A]">
                    <th className="min-w-[200px] px-2 py-3 text-left text-sm font-medium text-gray-700 lg:px-4 dark:text-[#59636E]">
                      {t('settings.sources.fileName')}
                    </th>
                    <th className="min-w-[80px] px-2 py-3 text-left text-sm font-medium text-gray-700 lg:px-4 dark:text-[#59636E]">
                      {t('settings.sources.tokens')}
                    </th>
                    <th className="min-w-[80px] px-2 py-3 text-left text-sm font-medium text-gray-700 lg:px-4 dark:text-[#59636E]">
                      {t('settings.sources.size')}
                    </th>
                    <th className="w-[60px] px-2 py-3 text-left text-sm font-medium text-gray-700 lg:px-4 dark:text-[#59636E]">
                      <span className="sr-only">
                        {t('settings.sources.actions')}
                      </span>
                    </th>
                  </tr>
                </thead>
                <tbody className="[&>tr:last-child]:border-b-0">
                  {renderConnectorFileTree(currentDirectory)}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ConnectorTree;
