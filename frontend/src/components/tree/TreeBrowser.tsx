import { createPortal } from 'react-dom';
import React, {
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { selectToken } from '../../preferences/preferenceSlice';
import { formatCount } from '../../utils/dateTimeUtils';
import { formatBytes } from '../../utils/stringUtils';
import userService from '../../api/services/userService';
import { Eye, File, Folder } from 'lucide-react';
import { EmptyState } from '../ui/empty-state';
import { useLoaderState } from '../../hooks';
import Chunks, {
  type ChunksController,
  type OpenChunkPosition,
} from '../Chunks';
import PathHeader, { type Crumb } from './PathHeader';
import SourceNavigator from './SourceNavigator';
import SkeletonLoader from '../SkeletonLoader';
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
import {
  countLeaves,
  directoryToNavigator,
  type NavigatorNode,
} from './navigatorUtils';
import type {
  DirectoryStructure,
  FileNode,
  RowMenuContext,
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
  /** The source kind (a neutral Badge) after the crumbs. */
  badge?: React.ReactNode;
  /**
   * Rendered inside another source view (the graph source's Files tab): no
   * Sources crumb, no badge and no byline.
   */
  embedded?: boolean;
  /**
   * Embedded only: the tree's crumbs (the source, its folders, the open file
   * and chunk), for a host that draws them in its own header.
   */
  onCrumbsChange?: (crumbs: Crumb[]) => void;
  /**
   * Embedded only: the host header's action slot. The tree then draws no row
   * of its own and portals its status and `topRightAction` (Add file, Sync)
   * into the slot, so a tab's action sits in the page header.
   */
  actionsTarget?: HTMLElement | null;
  /**
   * A file to open once the structure loads (the graph's "Open in Files"):
   * its full path, its file name or its display name. Applied again when it
   * changes.
   */
  initialPath?: string;
  /**
   * Whether the caller may change the source (`can(source, 'edit')`).
   * False hides the chunk list's Add, Edit and Delete; browsing stays.
   */
  canEdit?: boolean;
}

/**
 * Every file in the navigator tree, in tree order.
 *
 * @param nodes The navigator tree.
 * @returns The leaves.
 */
function collectLeaves(nodes: NavigatorNode[]): NavigatorNode[] {
  const leaves: NavigatorNode[] = [];
  const walk = (list: NavigatorNode[]) => {
    for (const node of list) {
      if (node.kind === 'leaf') leaves.push(node);
      else walk(node.children ?? []);
    }
  };
  walk(nodes);
  return leaves;
}

/**
 * The file an `initialPath` names: an exact path first, then a file whose
 * name (last path segment) or display name matches.
 *
 * @param nodes The navigator tree.
 * @param target The path or name to look for.
 * @returns The leaf, or undefined.
 */
function findFileByPathOrName(
  nodes: NavigatorNode[],
  target: string,
): NavigatorNode | undefined {
  const leaves = collectLeaves(nodes);
  return (
    leaves.find((leaf) => leaf.path === target) ??
    leaves.find(
      (leaf) => leaf.path.split('/').pop() === target || leaf.label === target,
    )
  );
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
  badge,
  embedded = false,
  actionsTarget,
  initialPath,
  onCrumbsChange,
  canEdit = true,
}) => {
  const { t } = useTranslation();
  const [loading, setLoading] = useLoaderState(true, 500);
  const [loadFailed, setLoadFailed] = useState(false);
  // Bumped to refetch the structure (Retry).
  const [reloadKey, setReloadKey] = useState(0);
  const [directoryStructure, setDirectoryStructure] =
    useState<DirectoryStructure | null>(null);
  const [currentPath, setCurrentPath] = useState<string[]>([]);
  const token = useSelector(selectToken);
  const [selectedFile, setSelectedFile] = useState<{
    id: string;
    name: string;
  } | null>(null);
  const mountedRef = useRef(true);
  // The open file's open chunk (its crumb), reported by Chunks.
  const [openChunkPosition, setOpenChunkPosition] =
    useState<OpenChunkPosition>(null);
  const chunksControllerRef = useRef<ChunksController | null>(null);

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
    setSelectedFile(null);
    setCurrentPath([]);
  }, []);

  useImperativeHandle(
    controllerRef as React.MutableRefObject<TreeBrowserController | null>,
    () => ({ refreshDirectory, resetPath }),
    [refreshDirectory, resetPath],
  );

  useEffect(() => {
    if (!docId) return;
    let cancelled = false;
    const fetchDirectoryStructure = async () => {
      try {
        setLoading(true);
        setLoadFailed(false);
        const response = await userService.getDirectoryStructure(docId, token);
        const data = await response.json();
        if (cancelled) return;
        if (data && data.directory_structure) {
          setDirectoryStructure(data.directory_structure);
          onDirectoryDataLoadedRef.current?.(data);
        } else {
          setLoadFailed(true);
        }
      } catch (err) {
        console.error(err);
        if (!cancelled) setLoadFailed(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    fetchDirectoryStructure();
    return () => {
      cancelled = true;
    };
  }, [docId, token, reloadKey]);

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

  // The navigator's tree; a source with exactly one file (at any depth)
  // opens straight on that file, with no navigator and no table.
  const navigatorNodes = useMemo(
    () => directoryToNavigator(directoryStructure),
    [directoryStructure],
  );
  const singleFile = useMemo(() => {
    const leaves = collectLeaves(navigatorNodes);
    return leaves.length === 1 ? leaves[0] : null;
  }, [navigatorNodes]);
  const openFile = singleFile
    ? { id: singleFile.path, name: singleFile.label }
    : selectedFile;

  const byline = useMemo(() => {
    if (embedded || !directoryStructure) return undefined;
    let structure: unknown = directoryStructure;
    if (typeof structure === 'string') {
      try {
        structure = JSON.parse(structure);
      } catch {
        structure = {};
      }
    }
    const { totalTokens } = calculateDirectoryStats(
      structure && typeof structure === 'object'
        ? (structure as DirectoryStructure)
        : {},
    );
    const files = countLeaves(navigatorNodes);
    return t('settings.sources.filesByline', {
      count: files,
      files: formatCount(files),
      tokens: formatCount(totalTokens),
    });
  }, [embedded, directoryStructure, navigatorNodes, t]);

  const handleNavigatorSelect = (node: NavigatorNode) => {
    const parts = node.path.split('/');
    if (node.kind === 'folder') {
      setSelectedFile(null);
      setCurrentPath(parts);
    } else {
      setCurrentPath(parts.slice(0, -1));
      setSelectedFile({ id: node.path, name: node.label });
    }
  };

  // Open the file the caller asked for, once per new initialPath; a path not
  // found yet is tried again when the structure reloads.
  const appliedInitialPath = useRef<string | null>(null);
  useEffect(() => {
    if (!initialPath || !directoryStructure) return;
    if (appliedInitialPath.current === initialPath) return;
    const file = findFileByPathOrName(navigatorNodes, initialPath);
    if (!file) return;
    appliedInitialPath.current = initialPath;
    setCurrentPath(file.path.split('/').slice(0, -1));
    setSelectedFile({ id: file.path, name: file.label });
  }, [initialPath, directoryStructure, navigatorNodes]);

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
    const tokensDisplay = tokens > 0 ? formatCount(tokens) : '-';

    // Numbers read down a column: right-aligned, tabular figures.
    const size = (
      <TableCell
        width={columnOrder === 'size-first' ? '30%' : '20%'}
        align="right"
        className="whitespace-nowrap tabular-nums"
      >
        {sizeDisplay}
      </TableCell>
    );
    const tokenCell = (
      <TableCell
        width={columnOrder === 'size-first' ? '20%' : '30%'}
        align="right"
        className="tabular-nums"
      >
        {tokensDisplay}
      </TableCell>
    );
    return columnOrder === 'size-first' ? (
      <>
        {size}
        {tokenCell}
      </>
    ) : (
      <>
        {tokenCell}
        {size}
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

    return [...directoryRows, ...fileRows];
  };

  // Crumb n opens the folder made of the first n path segments (0 = root).
  const openPathDepth = useCallback((depth: number) => {
    setSelectedFile(null);
    setCurrentPath((prev) => prev.slice(0, depth));
  }, []);

  // The source, the open folder's path, the open file, then the open chunk;
  // every crumb but the current (last) one opens its level.
  const folderPath = singleFile ? [] : currentPath;
  const chunkOpen = !!openFile && openChunkPosition !== null;
  const depth = folderPath.length + (openFile ? 1 : 0) + (chunkOpen ? 1 : 0);
  const treeCrumbs: Crumb[] = [
    {
      label: sourceName,
      onSelect: !singleFile && depth > 0 ? () => openPathDepth(0) : undefined,
    },
    ...folderPath.map((dir, index) => ({
      label: dir,
      onSelect: index < depth - 1 ? () => openPathDepth(index + 1) : undefined,
    })),
    ...(openFile
      ? [
          {
            label: openFile.name,
            onSelect: chunkOpen
              ? () => chunksControllerRef.current?.closeChunk()
              : undefined,
          },
        ]
      : []),
    ...(chunkOpen
      ? [
          {
            label:
              openChunkPosition === 'unplaced'
                ? t('settings.sources.chunkCrumbUnplaced')
                : t('settings.sources.chunkCrumb', { n: openChunkPosition }),
          },
        ]
      : []),
  ];

  // An embedded tree's host draws the crumbs; report them when they change.
  const treeCrumbsRef = useRef(treeCrumbs);
  const onCrumbsChangeRef = useRef(onCrumbsChange);
  useEffect(() => {
    treeCrumbsRef.current = treeCrumbs;
    onCrumbsChangeRef.current = onCrumbsChange;
  });
  const crumbsKey = treeCrumbs
    .map((crumb) => `${crumb.label}${crumb.onSelect ? '>' : ''}`)
    .join('/');
  useEffect(() => {
    onCrumbsChangeRef.current?.(treeCrumbsRef.current);
  }, [crumbsKey]);
  // Leaving (the host's tab changes) clears them, so a remount never shows
  // the previous trail.
  useEffect(() => () => onCrumbsChangeRef.current?.([]), []);

  // A single-file source shows no table, so its row menu (Delete) moves to
  // the header, less the View option (the file is already open). The path
  // sits at the root, so the file's name is its full path.
  useEffect(() => {
    if (singleFile) setCurrentPath((prev) => (prev.length ? [] : prev));
  }, [singleFile]);
  const singleFileMenu = (() => {
    if (!singleFile || !getRowMenuOptions) return null;
    const defaultViewOption = buildDefaultViewOption(
      singleFile.path,
      true,
      singleFile.label,
    );
    const options = getRowMenuOptions({
      name: singleFile.path,
      isFile: true,
      itemId: `file-${singleFile.path}`,
      displayName: singleFile.label,
      defaultViewOption,
    }).filter((option) => option !== defaultViewOption);
    if (options.length === 0) return null;
    return (
      <ActionMenu
        size="toolbar"
        options={options}
        triggerLabel={t('settings.sources.menuAlt')}
      />
    );
  })();

  const headerActions = (
    <>
      {statusLabel && (
        <div className="text-muted-foreground text-sm">{statusLabel}</div>
      )}
      {singleFileMenu}
      {topRightAction}
    </>
  );

  const renderPathNavigation = () => {
    const [sourceCrumb, ...rest] = treeCrumbs;
    return (
      <PathHeader
        root={
          embedded
            ? sourceCrumb
            : {
                label: t('settings.sources.label'),
                onSelect: onBackToDocuments,
              }
        }
        segments={embedded ? rest : treeCrumbs}
        badge={embedded ? undefined : badge}
        byline={byline}
        actions={headerActions}
      />
    );
  };

  const currentDirectory = getCurrentDirectory();

  const renderChunks = (file: { id: string; name: string }) => (
    <Chunks
      key={file.id}
      embedded
      documentId={docId}
      documentName={sourceName}
      handleGoBack={() => setSelectedFile(null)}
      path={file.id}
      fileName={file.name}
      controllerRef={chunksControllerRef}
      onOpenChunkChange={setOpenChunkPosition}
      canEdit={canEdit}
    />
  );

  const renderTable = () => (
    <TableContainer>
      <Table>
        <TableHead>
          <TableRow>
            <TableHeader width="40%" align="left">
              {t('settings.sources.fileName')}
            </TableHeader>
            {columnOrder === 'size-first' ? (
              <>
                <TableHeader width="30%" align="right">
                  {t('settings.sources.size')}
                </TableHeader>
                <TableHeader width="20%" align="right">
                  {t('settings.sources.tokens')}
                </TableHeader>
              </>
            ) : (
              <>
                <TableHeader width="30%" align="right">
                  {t('settings.sources.tokens')}
                </TableHeader>
                <TableHeader width="20%" align="right">
                  {t('settings.sources.size')}
                </TableHeader>
              </>
            )}
            <TableHeader width="10%" align="right">
              <span className="sr-only">{t('settings.sources.actions')}</span>
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
  );

  const renderContent = () => {
    if (loading) return renderTable();
    if (loadFailed) {
      return (
        <EmptyState
          tone="destructive"
          illustration="none"
          title={t('settings.sources.filesLoadError')}
          onRetry={() => setReloadKey((key) => key + 1)}
        />
      );
    }
    if (singleFile) return renderChunks(openFile!);
    if (navigatorNodes.length === 0) return renderTable();
    return (
      <div className="flex flex-col gap-4 lg:flex-row lg:gap-6">
        <SourceNavigator
          nodes={navigatorNodes}
          selectedId={
            selectedFile?.id ??
            (currentPath.length > 0 ? currentPath.join('/') : null)
          }
          onSelect={handleNavigatorSelect}
          folderMode="tree"
          filterLabel={t('settings.sources.filterFiles')}
          emptyLabel={t('settings.sources.noResults')}
          title={t('settings.sources.files')}
        />
        <div className="min-w-0 flex-1">
          {selectedFile ? renderChunks(selectedFile) : renderTable()}
        </div>
      </div>
    );
  };

  return (
    <div className="flex w-full max-w-full min-w-0 flex-col gap-4">
      {embedded && actionsTarget
        ? createPortal(headerActions, actionsTarget)
        : renderPathNavigation()}
      {renderContent()}
      {extraContent}
    </div>
  );
};

export default TreeBrowser;
