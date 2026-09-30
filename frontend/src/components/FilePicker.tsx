import { ChevronRight, File, Folder } from 'lucide-react';
import React, {
  Fragment,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import connectorsService from '../api/services/connectorsService';
import userService from '../api/services/userService';
import ConnectorAuth from '../components/ConnectorAuth';
import ConnectorIcon from '../connectors/ConnectorIcon';
import {
  loadConnectors,
  selectConnections,
} from '../connectors/connectorsSlice';
import { connectorIconKey } from '../connectors/i18n';
import { useDebouncedCallback } from '../hooks';
import { useLoadMore, type LoadMorePage } from '../hooks/useLoadMore';
import type { AppDispatch } from '../store';
import { formatCount, formatDateOnly } from '../utils/dateTimeUtils';
import { formatBytes } from '../utils/stringUtils';
import SearchInput from './SearchInput';
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from './ui/breadcrumb';
import { Button } from './ui/button';
import { Card } from './ui/card';
import { Checkbox } from './ui/checkbox';
import { EmptyState } from './ui/empty-state';
import { IconButton } from './ui/icon-button';
import { ListRow, ListRows } from './ui/list-row';
import { LoadMoreStatus } from './ui/load-more-status';
import { LoadingState } from './ui/loading-state';
import { Tabs, TabsContent, TabsList, TabsTrigger } from './ui/tabs';

interface CloudFile {
  id: string;
  name: string;
  type: string;
  size?: number;
  modifiedTime: string;
  isFolder?: boolean;
}

type Crumb = { id: string | null; name: string };
type DriveTab = 'my_files' | 'shared';

// One page of a folder listing.
const PAGE_SIZE = 10;

// Brand names, not translated.
const PROVIDER_NAMES: Record<string, string> = {
  google_drive: 'Drive',
  share_point: 'SharePoint',
  confluence: 'Confluence',
};

const isFolder = (file: CloudFile) =>
  file.isFolder ||
  file.type === 'application/vnd.google-apps.folder' ||
  file.type === 'folder';

/**
 * The file browser under the drive tabs. With the tabs shown it is the active
 * tab's panel; without them (one drive) it renders as is.
 */
function DrivePanel({
  tabbed,
  value,
  children,
}: {
  tabbed: boolean;
  value: string;
  children: React.ReactNode;
}) {
  return tabbed ? (
    <TabsContent value={value} className="mt-4">
      {children}
    </TabsContent>
  ) : (
    <>{children}</>
  );
}

interface CloudFilePickerProps {
  onSelectionChange: (
    selectedFileIds: string[],
    selectedFolderIds?: string[],
  ) => void;
  /** Called with the first item's name when the selection goes from empty to one. */
  onFirstPickName?: (name: string) => void;
  /**
   * The connection (signed-in account) to browse, chosen by the caller (the
   * connect wizard). Left out, the picker browses the first connected
   * account for ``provider`` and offers its own sign-in.
   */
  connectionId?: string | null;
  /** Reports the account the picker is browsing, so the upload can name it. */
  onConnectionChange?: (connectionId: string | null) => void;
  /** Signs the connection in again when its sign-in expired. */
  onReconnect?: () => void;
  provider: string;
  token: string | null;
  initialSelectedFiles?: string[];
}

/**
 * Pick files and folders from a SharePoint, Confluence or Drive listing: the
 * search, then the folder's items as check rows that load more as the list
 * scrolls (the modal body is the one scroller), then how many are picked.
 * Folders open with the trailing chevron; their checkbox picks them whole.
 */
export const FilePicker: React.FC<CloudFilePickerProps> = ({
  onSelectionChange,
  onFirstPickName,
  connectionId: suppliedConnectionId,
  onConnectionChange,
  onReconnect,
  provider,
  token,
  initialSelectedFiles = [],
}) => {
  const { t } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();
  const rootName =
    provider === 'google_drive'
      ? t('filePicker.myDrive')
      : provider === 'share_point'
        ? t('filePicker.myFiles')
        : provider === 'confluence'
          ? t('filePicker.spaces')
          : t('filePicker.root');

  // The wizard hands in the account; only a caller that doesn't falls back
  // to the first connected one and the picker's own sign-in.
  const supplied = suppliedConnectionId !== undefined;
  const connections = useSelector(selectConnections);
  const fallbackConnectionId =
    connections.find(
      (connection) =>
        connection.connector_key === provider &&
        connection.status === 'connected',
    )?.id ?? null;
  const [signedInId, setSignedInId] = useState<string | null>(null);
  const activeConnectionId = supplied
    ? suppliedConnectionId
    : (signedInId ?? fallbackConnectionId);

  const [selectedFiles, setSelectedFiles] =
    useState<string[]>(initialSelectedFiles);
  const [selectedFolders, setSelectedFolders] = useState<string[]>([]);
  const [activeTab, setActiveTab] = useState<DriveTab>('my_files');
  const [folderPath, setFolderPath] = useState<Crumb[]>([
    { id: null, name: rootName },
  ]);
  const [query, setQuery] = useState('');
  const [searchedQuery, setSearchedQuery] = useState('');
  const [allowsSharedContent, setAllowsSharedContent] = useState(false);
  const [needsReconnect, setNeedsReconnect] = useState(false);
  const [authError, setAuthError] = useState('');
  const abortRef = useRef<AbortController | null>(null);

  const currentFolderId = folderPath[folderPath.length - 1].id;

  useEffect(() => {
    onConnectionChange?.(activeConnectionId);
  }, [activeConnectionId]);

  const load = useCallback(
    async (cursor: string | null): Promise<LoadMorePage<CloudFile, string>> => {
      if (!activeConnectionId) return { items: [], next: null };
      // A newer listing replaces this one: never let a stale answer land.
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      if (cursor === null) setNeedsReconnect(false);
      const response = await userService.getConnectorFiles(
        {
          provider,
          connection_id: activeConnectionId,
          folder_id: currentFolderId,
          limit: PAGE_SIZE,
          page_token: cursor ?? undefined,
          search_query: searchedQuery,
          shared: activeTab === 'shared' && !currentFolderId,
        },
        token,
        controller.signal,
      );
      const data = await response.json();
      if (!data.success) {
        if (data.reconnect) {
          setNeedsReconnect(true);
          dispatch(loadConnectors({ token }));
        }
        throw new Error(data.error || 'list failed');
      }
      return {
        items: data.files ?? [],
        next: data.next_page_token || null,
      };
    },
    [
      activeConnectionId,
      currentFolderId,
      searchedQuery,
      activeTab,
      provider,
      token,
      dispatch,
    ],
  );

  const feed = useLoadMore<CloudFile, string>({
    load,
    resetKey: [
      activeConnectionId ?? '',
      activeTab,
      currentFolderId ?? '',
      searchedQuery,
    ].join('|'),
  });

  useEffect(() => () => abortRef.current?.abort(), []);

  // Browse from the root whenever the account changes.
  useEffect(() => {
    setActiveTab('my_files');
    setFolderPath([{ id: null, name: rootName }]);
    setQuery('');
    setSearchedQuery('');
    setAllowsSharedContent(false);
    if (!activeConnectionId || provider !== 'share_point') return;
    // Work and school accounts can browse "Shared with me" too.
    connectorsService
      .pickerToken(activeConnectionId, token)
      .then((data) => setAllowsSharedContent(!!data?.allows_shared_content))
      .catch(() => undefined);
  }, [activeConnectionId, provider]);

  const search = useDebouncedCallback(
    (value: string) => setSearchedQuery(value),
    300,
  );

  const clearSearch = () => {
    setQuery('');
    setSearchedQuery('');
  };

  const openFolder = (folder: CloudFile) => {
    if (folder.id === currentFolderId) return;
    clearSearch();
    setFolderPath((path) => [...path, { id: folder.id, name: folder.name }]);
  };

  const goUp = (index: number) => {
    if (index >= folderPath.length - 1) return;
    clearSearch();
    setFolderPath((path) => path.slice(0, index + 1));
  };

  const showDriveTabs = provider === 'share_point' && allowsSharedContent;

  const changeTab = (tab: DriveTab) => {
    if (tab === activeTab) return;
    setActiveTab(tab);
    clearSearch();
    setFolderPath([
      { id: null, name: tab === 'shared' ? t('filePicker.shared') : rootName },
    ]);
  };

  const toggle = (file: CloudFile) => {
    if (selectedFiles.length === 0 && selectedFolders.length === 0) {
      onFirstPickName?.(file.name);
    }
    if (isFolder(file)) {
      const next = selectedFolders.includes(file.id)
        ? selectedFolders.filter((id) => id !== file.id)
        : [...selectedFolders, file.id];
      setSelectedFolders(next);
      onSelectionChange(selectedFiles, next);
    } else {
      const next = selectedFiles.includes(file.id)
        ? selectedFiles.filter((id) => id !== file.id)
        : [...selectedFiles, file.id];
      setSelectedFiles(next);
      onSelectionChange(next, selectedFolders);
    }
  };

  const meta = (file: CloudFile) => {
    const date = file.modifiedTime ? formatDateOnly(file.modifiedTime) : '';
    if (isFolder(file))
      return date
        ? t('filePicker.folderMeta', {
            date,
            interpolation: { escapeValue: false },
          })
        : t('filePicker.folder');
    const size = file.size ? formatBytes(file.size) : '';
    if (date && size)
      return t('filePicker.fileMeta', {
        date,
        size,
        interpolation: { escapeValue: false },
      });
    if (date)
      return t('filePicker.updated', {
        date,
        interpolation: { escapeValue: false },
      });
    return size || undefined;
  };

  const pickedCount = selectedFiles.length + selectedFolders.length;

  const renderList = () => {
    if (feed.items.length === 0) {
      if (feed.loading) return <LoadingState fill="block" />;
      if (feed.error)
        return (
          <EmptyState
            tone="destructive"
            size="sm"
            illustration="none"
            title={
              needsReconnect
                ? t('settings.connectors.detail.expired')
                : t('filePicker.loadFailed')
            }
            onRetry={needsReconnect ? undefined : feed.retry}
            action={
              needsReconnect && onReconnect ? (
                <Button
                  variant="outline"
                  size="sm"
                  shape="pill"
                  onClick={onReconnect}
                >
                  {t('settings.connectors.status.reconnect')}
                </Button>
              ) : undefined
            }
          />
        );
      return (
        <EmptyState
          size="xs"
          illustration="none"
          title={
            searchedQuery
              ? t('filePicker.noMatches')
              : t('filePicker.emptyFolder')
          }
        />
      );
    }
    return (
      <>
        <Card variant="outline" padding="none" className="overflow-hidden">
          <ListRows>
            {feed.items.map((file) => {
              const folder = isFolder(file);
              const id = `file-picker-${file.id}`;
              return (
                <ListRow
                  key={file.id}
                  interactive
                  asChild
                  leading={
                    <>
                      <Checkbox
                        id={id}
                        aria-label={file.name}
                        checked={(folder
                          ? selectedFolders
                          : selectedFiles
                        ).includes(file.id)}
                        onCheckedChange={() => toggle(file)}
                      />
                      <span className="bg-muted text-muted-foreground flex size-8 shrink-0 items-center justify-center rounded-md">
                        {folder ? (
                          <Folder className="size-4" aria-hidden />
                        ) : (
                          <File className="size-4" aria-hidden />
                        )}
                      </span>
                    </>
                  }
                  title={file.name}
                  description={meta(file)}
                  trailing={
                    folder ? (
                      <IconButton
                        variant="ghost-muted"
                        size="icon-sm"
                        icon={ChevronRight}
                        label={t('filePicker.openFolder', {
                          name: file.name,
                          interpolation: { escapeValue: false },
                        })}
                        // Opening a folder is not picking it: cancel the
                        // row label's click before it reaches the label.
                        onClickCapture={(event) => event.preventDefault()}
                        onClick={() => openFolder(file)}
                      />
                    ) : undefined
                  }
                >
                  <label htmlFor={id} />
                </ListRow>
              );
            })}
          </ListRows>
        </Card>
        <div ref={feed.sentinelRef} aria-hidden="true" className="h-px" />
        {feed.items.length >= PAGE_SIZE && (!feed.done || feed.error) ? (
          <LoadMoreStatus
            loading={feed.loading}
            error={feed.error}
            done={false}
            onRetry={feed.retry}
            loadingLabel={t('pagination.loadingMore')}
          />
        ) : null}
      </>
    );
  };

  const browser = (
    <div className="flex flex-col gap-3">
      {/* At the root the tab (or the step) says where this is; the trail
          appears once a folder is open, its first crumb the way back. */}
      {folderPath.length > 1 && (
        <Breadcrumb className="min-w-0">
          <BreadcrumbList>
            {folderPath.map((crumb, index) => (
              <Fragment key={crumb.id || 'root'}>
                {index > 0 && <BreadcrumbSeparator />}
                {index === folderPath.length - 1 ? (
                  <BreadcrumbItem>
                    <BreadcrumbPage>{crumb.name}</BreadcrumbPage>
                  </BreadcrumbItem>
                ) : (
                  <BreadcrumbItem>
                    <BreadcrumbLink asChild>
                      <button
                        type="button"
                        title={crumb.name}
                        onClick={() => goUp(index)}
                      >
                        {crumb.name}
                      </button>
                    </BreadcrumbLink>
                  </BreadcrumbItem>
                )}
              </Fragment>
            ))}
          </BreadcrumbList>
        </Breadcrumb>
      )}
      <SearchInput
        label={t('filePicker.searchPlaceholder')}
        labelSurface="card"
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
          search(event.target.value);
        }}
      />
      {renderList()}
      {pickedCount > 0 && (
        <p className="text-muted-foreground text-xs">
          {t('filePicker.itemsSelected', {
            count: pickedCount,
            formatted: formatCount(pickedCount),
          })}
        </p>
      )}
    </div>
  );

  return (
    <div className="flex flex-col gap-4">
      {!supplied && (
        <ConnectorAuth
          provider={provider}
          label={t('filePicker.connectTo', {
            provider: PROVIDER_NAMES[provider] ?? provider,
          })}
          icon={
            <ConnectorIcon
              icon={connectorIconKey(provider)}
              className="size-5"
            />
          }
          onSuccess={(data) => {
            setAuthError('');
            dispatch(loadConnectors({ token }));
            if (data.connection_id) setSignedInId(data.connection_id);
          }}
          onError={setAuthError}
          errorMessage={authError}
          isConnected={!!activeConnectionId}
          userEmail={
            connections.find((c) => c.id === activeConnectionId)
              ?.account_label ||
            t('modals.uploadDoc.connectors.auth.connectedUser')
          }
        />
      )}
      {activeConnectionId && (
        <Tabs
          value={activeTab}
          onValueChange={(value) => changeTab(value as DriveTab)}
        >
          {showDriveTabs && (
            <TabsList>
              <TabsTrigger value="my_files">
                {t('filePicker.myFiles')}
              </TabsTrigger>
              <TabsTrigger value="shared">
                {t('filePicker.sharedWithMe')}
              </TabsTrigger>
            </TabsList>
          )}
          <DrivePanel tabbed={showDriveTabs} value={activeTab}>
            {browser}
          </DrivePanel>
        </Tabs>
      )}
    </div>
  );
};
