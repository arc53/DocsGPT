import React, {
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
import { Eye, File, Folder } from 'lucide-react';
import { useLoaderState, useOutsideAlerter } from '../../hooks';
import Chunks from '../Chunks';
import PathHeader from './PathHeader';
import SkeletonLoader from '../SkeletonLoader';
import { cn, fieldFrame } from '@/lib/utils';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '../ui/command';
import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
} from '../ui/table';
import { ActionMenu, type MenuOption } from '../ui/dropdown-menu';
import type {
  DirectoryStructure,
  FileNode,
  RowMenuContext,
  SearchResult,
  TreeBrowserController,
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
  getRowMenuOptions?: (ctx: RowMenuContext) => MenuOption[];
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

// The search field's frame: the pill Input look around a CommandInput
// (38px, focus ring while the input has keyboard focus). CommandInput's row
// is 36px with a bottom rule; pt-px + overflow-hidden clips that rule.
const SEARCH_FRAME = cn(
  fieldFrame,
  'border-border has-[input:focus-visible]:border-ring has-[input:focus-visible]:ring-ring/50 h-9.5 overflow-hidden rounded-full px-2 pt-px has-[input:focus-visible]:ring-3',
);

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
  ): MenuOption => ({
    icon: Eye,
    label: t('settings.sources.view'),
    onClick: () => {
      if (isFile) {
        handleFileClick(name, displayName);
      } else {
        navigateToDirectory(name);
      }
    },
  });

  const resolveRowMenuOptions = (
    name: string,
    isFile: boolean,
    itemId: string,
    displayName?: string,
  ): MenuOption[] => {
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
    <ActionMenu
      options={resolveRowMenuOptions(name, isFile, itemId, displayName)}
      triggerLabel={t('settings.sources.menuAlt')}
      className="shrink-0"
    />
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
                <div className="flex items-center gap-2">
                  <Folder className="text-primary size-4 shrink-0" />
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
            <div className="flex min-w-0 items-center gap-2">
              <Folder className="text-primary size-4 shrink-0" />
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
            <div className="flex min-w-0 items-center gap-2">
              <File className="text-muted-foreground size-4 shrink-0" />
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
      {/* `contents`: the Command only scopes cmdk (the arrow keys move from
          the input to the rows); the frame and the dropdown draw the look. */}
      <Command shouldFilter={false} className="contents">
        <div className={SEARCH_FRAME}>
          <CommandInput
            value={searchQuery}
            onValueChange={(value) => {
              setSearchQuery(value);
              if (directoryStructure) {
                setSearchResults(searchFiles(value, directoryStructure));
              }
            }}
            placeholder={t('settings.sources.searchFiles')}
          />
        </div>

        {searchQuery && (
          <div className="border-border bg-popover text-popover-foreground absolute top-full right-0 left-0 z-20 mt-1 w-full overflow-hidden rounded-xl border shadow-md">
            <CommandList className="max-h-[calc(100dvh-200px)] overscroll-contain">
              {searchResults.length === 0 ? (
                <CommandEmpty>{t('settings.sources.noResults')}</CommandEmpty>
              ) : (
                <CommandGroup>
                  {searchResults.map((result) => (
                    <CommandItem
                      key={result.path}
                      value={result.path}
                      title={result.path}
                      onSelect={() => handleSearchSelect(result)}
                    >
                      {result.isFile ? (
                        <File />
                      ) : (
                        <Folder className="text-primary" />
                      )}
                      <span className="min-w-0 flex-1 truncate">
                        {result.name}
                      </span>
                    </CommandItem>
                  ))}
                </CommandGroup>
              )}
            </CommandList>
          </div>
        )}
      </Command>
    </div>
  );

  // Crumb n opens the folder made of the first n path segments (0 = root).
  const openPathDepth = useCallback((depth: number) => {
    setSelectedFile(null);
    setCurrentPath((prev) => prev.slice(0, depth));
  }, []);

  const renderPathNavigation = () => (
    <PathHeader
      root={{
        label: sourceName,
        onSelect: currentPath.length > 0 ? () => openPathDepth(0) : undefined,
      }}
      segments={currentPath.map((dir, index) => ({
        label: dir,
        onSelect:
          index < currentPath.length - 1
            ? () => openPathDepth(index + 1)
            : undefined,
      }))}
      onBack={handleBackNavigation}
      backLabel={t('settings.sources.back')}
      actions={
        <>
          {statusLabel && (
            <div className="text-muted-foreground text-sm">{statusLabel}</div>
          )}
          {renderFileSearch()}
          {topRightAction}
        </>
      }
    />
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
              onPathSelect={openPathDepth}
            />
          </div>
        </div>
      ) : (
        <div className="flex w-full max-w-full flex-col overflow-x-clip">
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
