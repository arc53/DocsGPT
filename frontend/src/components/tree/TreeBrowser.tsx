import React, {
  SyntheticEvent,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { selectToken } from '../../preferences/preferenceSlice';
import { formatBytes } from '../../utils/stringUtils';
import userService from '../../api/services/userService';
import ArrowLeft from '../../assets/arrow-left.svg';
import EyeView from '../../assets/eye-view.svg';
import FileIcon from '../../assets/file.svg';
import FolderIcon from '../../assets/folder.svg';
import ThreeDots from '../../assets/three-dots.svg';
import { useLoaderState, useOutsideAlerter } from '../../hooks';
import Chunks from '../Chunks';
import SkeletonLoader from '../SkeletonLoader';
import { Button } from '../ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
} from '../ui/table';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '../ui/dropdown-menu';
import type {
  DirectoryStructure,
  FileNode,
  RowMenuContext,
  SearchResult,
  TreeBrowserController,
  TreeMenuOption,
} from './types';

/** Column ordering for the size/tokens pair. */
export type ColumnOrder = 'size-first' | 'tokens-first';

export interface TreeBrowserProps {
  docId: string;
  sourceName: string;
  onBackToDocuments: () => void;
  /**
   * "size-first" = file name | size | tokens | actions (FileTree).
   * "tokens-first" = file name | tokens | size | actions (ConnectorTree).
   */
  columnOrder: ColumnOrder;
  /** When true, directory entries are sorted alphabetically within group. */
  sortEntries?: boolean;
  /** Top-right action area (e.g. Add File button, Sync button). */
  topRightAction: React.ReactNode;
  /**
   * Optional status text shown to the left of the search field while a
   * mutation is in progress (e.g. "Uploading files...").
   */
  statusLabel?: string | null;
  /**
   * Builds the row action menu. Defaults to a single "View" option.
   * Wrappers can extend this with Delete, etc.
   */
  getRowMenuOptions?: (ctx: RowMenuContext) => TreeMenuOption[];
  /** Modals / overlays the wrapper wants rendered alongside the tree. */
  extraContent?: React.ReactNode;
  /**
   * Called after a directory structure response is parsed. Useful for
   * connectors that need the provider field exposed on the response.
   */
  onDirectoryDataLoaded?: (data: any) => void;
  /**
   * Imperative handle so wrappers can trigger a refresh after a
   * successful mutation.
   */
  controllerRef?: React.MutableRefObject<TreeBrowserController | null>;
  /**
   * Mirrors the current breadcrumb path back to the wrapper so it can
   * construct paths for upload / delete mutations without owning the
   * navigation state.
   */
  onCurrentPathChange?: (path: string[]) => void;
}

function calculateDirectoryStats(structure: DirectoryStructure): {
  totalSize: number;
  totalTokens: number;
} {
  let totalSize = 0;
  let totalTokens = 0;

  Object.entries(structure).forEach(([, node]) => {
    if (node.type) {
      totalSize += node.size_bytes || 0;
      totalTokens += node.token_count || 0;
    } else {
      const stats = calculateDirectoryStats(node);
      totalSize += stats.totalSize;
      totalTokens += stats.totalTokens;
    }
  });

  return { totalSize, totalTokens };
}

function searchFiles(
  query: string,
  structure: DirectoryStructure,
  currentPath: string[] = [],
): SearchResult[] {
  let results: SearchResult[] = [];

  Object.entries(structure).forEach(([name, node]) => {
    const fullPath = [...currentPath, name].join('/');
    const displayName =
      typeof node.display_name === 'string' && node.display_name.trim()
        ? node.display_name
        : '';
    const queryLower = query.toLowerCase();
    const matchTarget = displayName ? `${name} ${displayName}` : name;

    if (matchTarget.toLowerCase().includes(queryLower)) {
      results.push({
        name: displayName || name,
        path: fullPath,
        isFile: !!node.type,
      });
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
}

function resolveDisplayName(
  directoryStructure: DirectoryStructure | null,
  path: string,
): string {
  if (!directoryStructure) {
    return path.split('/').pop() || path;
  }
  let structure: any = directoryStructure;
  if (typeof structure === 'string') {
    try {
      structure = JSON.parse(structure);
    } catch (e) {
      return path.split('/').pop() || path;
    }
  }
  if (typeof structure !== 'object' || structure === null) {
    return path.split('/').pop() || path;
  }
  const parts = path.split('/').filter(Boolean);
  let current: any = structure;
  for (const part of parts) {
    if (!current || typeof current !== 'object') {
      return parts[parts.length - 1] || path;
    }
    current = current[part];
  }
  if (
    current &&
    typeof current === 'object' &&
    typeof current.display_name === 'string' &&
    current.display_name.trim()
  ) {
    return current.display_name;
  }
  return parts[parts.length - 1] || path;
}

const TreeBrowser: React.FC<TreeBrowserProps> = ({
  docId,
  sourceName,
  onBackToDocuments,
  columnOrder,
  sortEntries = false,
  topRightAction,
  statusLabel,
  getRowMenuOptions,
  extraContent,
  onDirectoryDataLoaded,
  controllerRef,
  onCurrentPathChange,
}) => {
  const { t } = useTranslation();
  const [loading, setLoading] = useLoaderState(true, 500);
  const [, setError] = useState<string | null>(null);
  const [directoryStructure, setDirectoryStructure] =
    useState<DirectoryStructure | null>(null);
  const [currentPath, setCurrentPath] = useState<string[]>([]);
  const token = useSelector(selectToken);
  const [selectedFile, setSelectedFile] = useState<{
    id: string;
    name: string;
  } | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const searchDropdownRef = useRef<HTMLDivElement>(null);
  const mountedRef = useRef(true);

  useEffect(
    () => () => {
      mountedRef.current = false;
    },
    [],
  );

  const onCurrentPathChangeRef = useRef(onCurrentPathChange);
  const onDirectoryDataLoadedRef = useRef(onDirectoryDataLoaded);
  useEffect(() => {
    onCurrentPathChangeRef.current = onCurrentPathChange;
    onDirectoryDataLoadedRef.current = onDirectoryDataLoaded;
  });
  useEffect(() => {
    onCurrentPathChangeRef.current?.(currentPath);
  }, [currentPath]);

  useOutsideAlerter(
    searchDropdownRef,
    () => {
      setSearchQuery('');
      setSearchResults([]);
    },
    [],
    false,
  );

  const handleFileClick = useCallback(
    (fileName: string, displayName?: string) => {
      const fullPath = [...currentPath, fileName].join('/');
      setSelectedFile({ id: fullPath, name: displayName ?? fileName });
    },
    [currentPath],
  );

  const navigateToDirectory = useCallback((dirName: string) => {
    setCurrentPath((prev) => [...prev, dirName]);
  }, []);

  const navigateUp = useCallback(() => {
    setCurrentPath((prev) => prev.slice(0, -1));
  }, []);

  const refreshDirectory = useCallback(async () => {
    try {
      const response = await userService.getDirectoryStructure(docId, token);
      const data = await response.json();
      if (!mountedRef.current) return false;
      if (data && data.directory_structure) {
        setDirectoryStructure(data.directory_structure);
        onDirectoryDataLoadedRef.current?.(data);
        return true;
      }
      return false;
    } catch (err) {
      console.error('Error refreshing directory structure:', err);
      return false;
    }
  }, [docId, token]);

  const resetPath = useCallback(() => {
    setCurrentPath([]);
  }, []);

  useImperativeHandle(
    controllerRef as React.MutableRefObject<TreeBrowserController | null>,
    () => ({ refreshDirectory, resetPath }),
    [refreshDirectory, resetPath],
  );

  useEffect(() => {
    const fetchDirectoryStructure = async () => {
      try {
        setLoading(true);
        const response = await userService.getDirectoryStructure(docId, token);
        const data = await response.json();

        if (data && data.directory_structure) {
          setDirectoryStructure(data.directory_structure);
          onDirectoryDataLoadedRef.current?.(data);
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

  const getCurrentDirectory = useCallback((): DirectoryStructure => {
    if (!directoryStructure) return {};

    let structure: any = directoryStructure;
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
  }, [directoryStructure, currentPath]);

  const handleBackNavigation = () => {
    if (selectedFile) {
      setSelectedFile(null);
    } else if (currentPath.length === 0) {
      onBackToDocuments?.();
    } else {
      navigateUp();
    }
  };

  const handleSearchSelect = (result: SearchResult) => {
    if (result.isFile) {
      const pathParts = result.path.split('/');
      const fileName = pathParts.pop() || '';
      setCurrentPath(pathParts);

      setSelectedFile({
        id: result.path,
        name: result.name || fileName,
      });
    } else {
      setCurrentPath(result.path.split('/'));
      setSelectedFile(null);
    }
    setSearchQuery('');
    setSearchResults([]);
  };

  const handleFileSearch = (q: string): SearchResult[] => {
    if (directoryStructure) {
      return searchFiles(q, directoryStructure);
    }
    return [];
  };

  const handleFileSelect = (path: string) => {
    const pathParts = path.split('/');
    const fileName = pathParts.pop() || '';
    setCurrentPath(pathParts);
    setSelectedFile({
      id: path,
      name: resolveDisplayName(directoryStructure, path) || fileName,
    });
  };

  const buildDefaultViewOption = (
    name: string,
    isFile: boolean,
    displayName?: string,
  ): TreeMenuOption => ({
    icon: EyeView,
    label: t('settings.sources.view'),
    onClick: (event: SyntheticEvent) => {
      event.stopPropagation();
      if (isFile) {
        handleFileClick(name, displayName);
      } else {
        navigateToDirectory(name);
      }
    },
    iconWidth: 18,
    iconHeight: 18,
    variant: 'default',
  });

  const resolveRowMenuOptions = (
    name: string,
    isFile: boolean,
    itemId: string,
    displayName?: string,
  ): TreeMenuOption[] => {
    const defaultViewOption = buildDefaultViewOption(name, isFile, displayName);
    if (getRowMenuOptions) {
      return getRowMenuOptions({
        name,
        isFile,
        itemId,
        displayName,
        defaultViewOption,
      });
    }
    return [defaultViewOption];
  };

  const renderRowActionsCell = (
    name: string,
    isFile: boolean,
    itemId: string,
    displayName?: string,
  ) => (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          onClick={(e) => e.stopPropagation()}
          className="dark:hover:bg-muted h-[35px] w-6 shrink-0 p-0 hover:bg-[#EBEBEB]"
          aria-label={t('settings.sources.menuAlt')}
        >
          <img
            src={ThreeDots}
            alt={t('settings.sources.menuAlt')}
            className="opacity-60 hover:opacity-100"
          />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-[144px]">
        {resolveRowMenuOptions(name, isFile, itemId, displayName).map(
          (option, idx) => (
            <DropdownMenuItem
              key={idx}
              variant={option.variant}
              onSelect={(event) => {
                option.onClick(event as unknown as SyntheticEvent);
              }}
            >
              <img
                src={option.icon}
                alt=""
                width={option.iconWidth ?? 16}
                height={option.iconHeight ?? 16}
              />
              <span>{option.label}</span>
            </DropdownMenuItem>
          ),
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );

  /**
   * Renders the size + tokens column pair in the right order for the
   * configured columnOrder. Sizes/tokens of 0 (or undefined) render as
   * "-" — matches the pre-refactor behavior of both trees.
   */
  const renderColumnPair = (sizeBytes: number, tokens: number) => {
    const sizeDisplay = sizeBytes > 0 ? formatBytes(sizeBytes) : '-';
    const tokensDisplay = tokens > 0 ? tokens.toLocaleString() : '-';

    if (columnOrder === 'size-first') {
      return (
        <>
          <TableCell width="30%" align="left">
            {sizeDisplay}
          </TableCell>
          <TableCell width="20%" align="right">
            {tokensDisplay}
          </TableCell>
        </>
      );
    }
    return (
      <>
        <TableCell width="30%" align="left">
          {tokensDisplay}
        </TableCell>
        <TableCell width="20%" align="left">
          {sizeDisplay}
        </TableCell>
      </>
    );
  };

  const renderFileTree = (structure: DirectoryStructure): React.ReactNode[] => {
    const entries = Object.entries(structure);

    const sortedEntries = sortEntries
      ? entries.sort(([nameA, nodeA], [nameB, nodeB]) => {
          const isFileA = !!nodeA.type;
          const isFileB = !!nodeB.type;
          if (isFileA !== isFileB) {
            return isFileA ? 1 : -1; // Directories first
          }
          return nameA.localeCompare(nameB);
        })
      : entries;

    const directories = sortedEntries.filter(([, node]) => !node.type);
    const files = sortedEntries.filter(([, node]) => node.type);

    const parentRow =
      currentPath.length > 0
        ? [
            <TableRow key="parent-dir" onClick={navigateUp}>
              <TableCell width="40%" align="left">
                <div className="flex items-center">
                  <img
                    src={FolderIcon}
                    alt={t('settings.sources.parentFolderAlt')}
                    className="mr-2 h-4 w-4 shrink-0"
                  />
                  <span className="truncate">..</span>
                </div>
              </TableCell>
              <TableCell width="30%" align="left">
                -
              </TableCell>
              <TableCell
                width="20%"
                align={columnOrder === 'size-first' ? 'right' : 'left'}
              >
                -
              </TableCell>
              <TableCell width="10%" align="right"></TableCell>
            </TableRow>,
          ]
        : [];

    const directoryRows = directories.map(([name, node]) => {
      const itemId = `dir-${name}`;
      const dirStats = calculateDirectoryStats(node as DirectoryStructure);

      return (
        <TableRow key={itemId} onClick={() => navigateToDirectory(name)}>
          <TableCell width="40%" align="left">
            <div className="flex min-w-0 items-center">
              <img
                src={FolderIcon}
                alt={t('settings.sources.folderAlt')}
                className="mr-2 h-4 w-4 shrink-0"
              />
              <span className="truncate">{name}</span>
            </div>
          </TableCell>
          {renderColumnPair(dirStats.totalSize, dirStats.totalTokens)}
          <TableCell width="10%" align="right">
            {renderRowActionsCell(name, false, itemId)}
          </TableCell>
        </TableRow>
      );
    });

    const fileRows = files.map(([name, node]) => {
      const itemId = `file-${name}`;
      const displayName =
        typeof node.display_name === 'string' && node.display_name.trim()
          ? node.display_name
          : name;
      const fileNode = node as FileNode;

      return (
        <TableRow
          key={itemId}
          onClick={() => handleFileClick(name, displayName)}
        >
          <TableCell width="40%" align="left">
            <div className="flex min-w-0 items-center">
              <img
                src={FileIcon}
                alt={t('settings.sources.fileAlt')}
                className="mr-2 h-4 w-4 shrink-0"
              />
              <span className="truncate">{displayName}</span>
            </div>
          </TableCell>
          {renderColumnPair(
            fileNode.size_bytes || 0,
            fileNode.token_count || 0,
          )}
          <TableCell width="10%" align="right">
            {renderRowActionsCell(name, true, itemId, displayName)}
          </TableCell>
        </TableRow>
      );
    });

    return [...parentRow, ...directoryRows, ...fileRows];
  };

  const renderFileSearch = () => (
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
        className={`border-border dark:border-border h-[38px] w-full border px-4 py-2 ${searchQuery ? 'rounded-t-3xl' : 'rounded-3xl'} bg-transparent focus:outline-none`}
      />

      {searchQuery && (
        <div className="border-border bg-card dark:border-border dark:bg-card absolute top-full right-0 left-0 z-10 max-h-[calc(100vh-200px)] w-full overflow-hidden rounded-b-xl border border-t-0 shadow-lg transition-all duration-200">
          <div className="max-h-[calc(100vh-200px)] overflow-x-hidden overflow-y-auto overscroll-contain">
            {searchResults.length === 0 ? (
              <div className="text-muted-foreground py-2 text-center text-sm">
                {t('settings.sources.noResults')}
              </div>
            ) : (
              searchResults.map((result, index) => (
                <div
                  key={index}
                  onClick={() => handleSearchSelect(result)}
                  title={result.path}
                  className={`hover:bg-muted dark:hover:bg-muted flex min-w-0 cursor-pointer items-center px-3 py-2 ${
                    index !== searchResults.length - 1
                      ? 'border-border dark:border-border border-b'
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
                    className="mr-2 h-4 w-4 shrink-0"
                  />
                  <span className="flex-1 truncate text-sm">{result.name}</span>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );

  const renderPathNavigation = () => (
    <div className="mb-0 flex min-h-[38px] flex-col gap-2 text-base sm:flex-row sm:items-center sm:justify-between">
      <div className="flex w-full items-center sm:w-auto">
        <Button
          type="button"
          variant="outline"
          size="icon-sm"
          className="text-muted-foreground mr-3 h-[29px] w-[29px] rounded-full p-2 dark:border-0"
          onClick={handleBackNavigation}
        >
          <img src={ArrowLeft} alt="left-arrow" className="h-3 w-3" />
        </Button>

        <div className="flex flex-wrap items-center">
          <span className="text-primary font-semibold wrap-break-word">
            {sourceName}
          </span>
          {currentPath.length > 0 && (
            <>
              <span className="text-muted-foreground mx-1 shrink-0">/</span>
              {currentPath.map((dir, index) => (
                <React.Fragment key={index}>
                  <span className="dark:text-foreground wrap-break-word text-gray-700">
                    {dir}
                  </span>
                  {index < currentPath.length - 1 && (
                    <span className="text-muted-foreground mx-1 shrink-0">
                      /
                    </span>
                  )}
                </React.Fragment>
              ))}
            </>
          )}
          {selectedFile && (
            <>
              <span className="text-muted-foreground mx-1 shrink-0">/</span>
              <span className="dark:text-foreground wrap-break-word text-gray-700">
                {selectedFile.name}
              </span>
            </>
          )}
        </div>
      </div>

      <div className="relative mt-2 flex w-full flex-row flex-nowrap items-center justify-end gap-2 sm:mt-0 sm:w-auto">
        {statusLabel && (
          <div className="text-muted-foreground text-sm">{statusLabel}</div>
        )}
        {renderFileSearch()}
        {topRightAction}
      </div>
    </div>
  );

  const currentDirectory = getCurrentDirectory();

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
              displayPath={[...currentPath, selectedFile.name].join('/')}
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
                    {columnOrder === 'size-first' ? (
                      <>
                        <TableHeader width="30%" align="left">
                          {t('settings.sources.size')}
                        </TableHeader>
                        <TableHeader width="20%" align="right">
                          {t('settings.sources.tokens')}
                        </TableHeader>
                      </>
                    ) : (
                      <>
                        <TableHeader width="30%" align="left">
                          {t('settings.sources.tokens')}
                        </TableHeader>
                        <TableHeader width="20%" align="left">
                          {t('settings.sources.size')}
                        </TableHeader>
                      </>
                    )}
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
                    renderFileTree(currentDirectory)
                  )}
                </TableBody>
              </Table>
            </TableContainer>
          </div>
        </div>
      )}
      {extraContent}
    </div>
  );
};

export default TreeBrowser;
