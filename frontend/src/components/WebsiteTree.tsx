import { ExternalLink, Globe, RefreshCw, Trash2 } from 'lucide-react';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import userService from '../api/services/userService';
import ConfirmationModal from '../modals/ConfirmationModal';
import { showActionToast } from '../notifications/actionToastSlice';
import { selectToken } from '../preferences/preferenceSlice';
import { pageKey } from '../upload/website';
import { formatCount, formatRelative } from '../utils/dateTimeUtils';
import AddWebsitePagesModal from './AddWebsitePagesModal';
import type { LinkedChunk } from './chunkUtils';
import TreeBrowser from './tree/TreeBrowser';
import { folderAddress, pageAddress } from './tree/pages';
import type {
  DirectoryStructure,
  FileNode,
  RowMenuContext,
  TreeBrowserController,
} from './tree/types';
import { useReingestSseWaiter } from './tree/useReingestWait';
import { Alert, AlertDescription } from './ui/alert';
import { Button } from './ui/button';
import type { MenuOption } from './ui/dropdown-menu';

interface WebsiteTreeProps {
  docId: string;
  sourceName: string;
  onBackToDocuments: () => void;
  /** Extra header control (Test retrieval). */
  headerAction?: React.ReactNode;
  /** The source's ⋯, last in the title row. */
  headerMenu?: React.ReactNode;
  /** The hosts the source fetches from (the sources list's `website.hosts`). */
  hosts: string[];
  /** `sources.sync_frequency`; never (or empty) reads "Not synced". */
  syncFrequency?: string;
  /** When the source was last ingested or synced. */
  syncedAt?: string;
  canEdit?: boolean;
  initialPath?: string;
  linkedChunk?: LinkedChunk;
}

/** What a remove asks to confirm: its copy depends on where the page came from. */
type PendingRemoval = {
  name: string;
  path: string;
  isFile: boolean;
  /** `entry`: added by its address; `crawled`: found by a site; `folder`. */
  kind: 'entry' | 'crawled' | 'folder';
  /** The page's host (crawled) or the folder's address (folder). */
  where: string;
};

/**
 * A Website source in Knowledge: its pages by title, each with its address,
 * and a header line that says where the source comes from and how it stays
 * current. An open page's header links to the live page.
 *
 * Editors add pages (fetched now, kept in every sync), refresh one page, and
 * remove pages or folders. A page added by its address leaves the source's
 * list; a page a site's crawl found (or a folder) is skipped by later syncs.
 */
const WebsiteTree: React.FC<WebsiteTreeProps> = ({
  docId,
  sourceName,
  onBackToDocuments,
  headerAction,
  headerMenu,
  hosts,
  syncFrequency,
  syncedAt,
  canEdit = true,
  initialPath,
  linkedChunk,
}) => {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const token = useSelector(selectToken);
  const tr = (key: string, options?: Record<string, unknown>) =>
    t(`settings.sources.website.${key}`, options);

  const controllerRef = useRef<TreeBrowserController | null>(null);
  const currentPathRef = useRef<string[]>([]);
  const [structure, setStructure] = useState<DirectoryStructure>({});
  // Keys of the pages the source lists by address (from its config).
  const [pageEntries, setPageEntries] = useState<Set<string>>(new Set());
  const [configKey, setConfigKey] = useState(0);
  const [addOpen, setAddOpen] = useState(false);
  const [removal, setRemoval] = useState<PendingRemoval | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const { waitForTerminal, mountedRef } = useReingestSseWaiter();

  const tokenRef = useRef(token);
  tokenRef.current = token;
  useEffect(() => {
    if (!canEdit) return;
    let cancelled = false;
    userService
      .getWebsite(docId, tokenRef.current)
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (cancelled || !data?.config) return;
        const entries = data.config.entries as { url: string; mode: string }[];
        setPageEntries(
          new Set(
            entries.filter((e) => e.mode === 'page').map((e) => pageKey(e.url)),
          ),
        );
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [docId, canEdit, configKey]);

  const toastFailure = useCallback(
    (key: string, name?: string) =>
      dispatch(
        showActionToast({
          variant: 'destructive',
          message: tr(key, { name, interpolation: { escapeValue: false } }),
        }),
      ),
    // tr reads t, which is stable per language.
    [dispatch, t],
  );

  /** Waits for a background change to finish, then reloads the tree. */
  const awaitChange = async (
    label: string,
    startedAt: number,
    failure: string,
    name?: string,
  ) => {
    setStatus(label);
    const terminal = await waitForTerminal(docId, startedAt);
    if (!mountedRef.current) return;
    setStatus(null);
    if (terminal === 'completed') {
      await controllerRef.current?.refreshDirectory();
      setConfigKey((key) => key + 1);
    } else if (terminal === 'failed') {
      toastFailure(failure, name);
    }
  };

  const refreshPage = async (path: string, name: string) => {
    const startedAt = Date.now();
    try {
      const response = await userService.refreshWebsitePage(
        { source_id: docId, file_path: path },
        token,
      );
      if (!response.ok) throw new Error('refresh failed');
    } catch {
      toastFailure('refreshFailed', name);
      return;
    }
    await awaitChange(tr('refreshing'), startedAt, 'refreshFailed', name);
  };

  const confirmRemove = async () => {
    if (!removal) return;
    const body = removal.isFile
      ? { source_id: docId, file_paths: [removal.path] }
      : { source_id: docId, directory_path: removal.path };
    const response = await userService.removeWebsitePages(body, token);
    const data = await response.json().catch(() => null);
    if (!response.ok || !data?.success)
      throw new Error(data?.code === 'last_entry' ? 'last_entry' : 'failed');
    setRemoval(null);
    await controllerRef.current?.refreshDirectory();
    setConfigKey((key) => key + 1);
  };

  const askRemove = (name: string, isFile: boolean, node?: FileNode) => {
    const path = [...currentPathRef.current, name].join('/');
    if (!isFile) {
      setRemoval({
        name,
        path,
        isFile,
        kind: 'folder',
        where: folderAddress(structure, path) ?? path,
      });
      return;
    }
    const url = typeof node?.url === 'string' ? node.url : '';
    setRemoval({
      name:
        (typeof node?.display_name === 'string' && node.display_name) || name,
      path,
      isFile,
      kind: url && pageEntries.has(pageKey(url)) ? 'entry' : 'crawled',
      where: url ? new URL(url).host : '',
    });
  };

  const openLink = (url: string, label: string) => (
    <Button variant="link" size="inline" asChild>
      <a href={url} target="_blank" rel="noopener noreferrer">
        {label}
        <ExternalLink />
      </a>
    </Button>
  );

  const synced = !!syncFrequency && syncFrequency !== 'never';
  const frequencyLabel = synced
    ? t(`settings.sources.syncFrequency.${syncFrequency}`)
    : '';
  const syncLine = synced
    ? tr('synced', {
        frequency: frequencyLabel,
        when: formatRelative(syncedAt) ?? '',
      })
    : tr('notSynced');

  const renderByline = ({
    openFile,
    files,
    tokens,
  }: {
    openFile: FileNode | null;
    files: number;
    tokens: number;
  }) => {
    const parts: React.ReactNode[] = [];
    if (openFile && typeof openFile.url === 'string') {
      parts.push(openLink(openFile.url, pageAddress(openFile.url)));
      const when =
        typeof openFile.fetched_at === 'string'
          ? formatRelative(openFile.fetched_at)
          : null;
      if (when) parts.push(tr('fetchedAt', { when }));
    } else {
      if (hosts.length === 1) {
        parts.push(
          <span className="inline-flex items-center gap-1.5">
            <Globe className="size-4" aria-hidden="true" />
            {openLink(`https://${hosts[0]}`, hosts[0])}
          </span>,
        );
      } else if (hosts.length > 1) {
        parts.push(tr('sites', { count: hosts.length }));
      }
      parts.push(
        tr('pagesByline', {
          count: files,
          pages: formatCount(files),
          tokens: formatCount(tokens),
        }),
      );
      parts.push(syncLine);
    }
    return (
      <span className="inline-flex flex-wrap items-center gap-x-3 gap-y-1">
        {parts.map((part, index) => (
          <span key={index}>{part}</span>
        ))}
      </span>
    );
  };

  const getRowMenuOptions = ({
    defaultViewOption,
    name,
    isFile,
    displayName,
    node,
  }: RowMenuContext): MenuOption[] => {
    const url = typeof node?.url === 'string' ? node.url : null;
    const options: MenuOption[] = [defaultViewOption];
    if (url) {
      options.push({
        icon: ExternalLink,
        label: tr('openPage'),
        onClick: () => window.open(url, '_blank', 'noopener,noreferrer'),
      });
    }
    if (!canEdit) return options;
    if (url) {
      options.push({
        icon: RefreshCw,
        label: tr('refreshPage'),
        onClick: () =>
          void refreshPage(
            [...currentPathRef.current, name].join('/'),
            displayName ?? name,
          ),
      });
    }
    options.push({
      icon: Trash2,
      label: tr('removeFromSource'),
      onClick: () => askRemove(name, isFile, node),
      variant: 'destructive',
      separatorBefore: true,
    });
    return options;
  };

  const topRightAction = (
    <>
      {headerAction}
      {canEdit && !status ? (
        <Button
          type="button"
          size="field"
          shape="pill"
          onClick={() => setAddOpen(true)}
        >
          {tr('addPages')}
        </Button>
      ) : null}
    </>
  );

  const removalCopy = (() => {
    if (!removal) return { description: '', submit: '' };
    if (removal.kind === 'entry')
      return { description: tr('removeEntry'), submit: tr('remove') };
    if (removal.kind === 'folder')
      return {
        description: tr('removeFolder', { address: removal.where }),
        submit: tr('removeAndSkip'),
      };
    return {
      description: tr('removeCrawled', { host: removal.where }),
      submit: tr('removeAndSkip'),
    };
  })();

  return (
    <>
      <TreeBrowser
        docId={docId}
        sourceName={sourceName}
        onBackToDocuments={onBackToDocuments}
        columnOrder="size-first"
        variant="pages"
        renderByline={renderByline}
        topRightAction={topRightAction}
        headerMenu={headerMenu}
        statusLabel={status}
        getRowMenuOptions={getRowMenuOptions}
        controllerRef={controllerRef}
        onCurrentPathChange={(path) => {
          currentPathRef.current = path;
        }}
        onDirectoryDataLoaded={(data) => {
          const value = data?.directory_structure;
          setStructure(value && typeof value === 'object' ? value : {});
        }}
        chunksNotice={
          canEdit && synced ? (
            <Alert variant="info" role="note">
              <AlertDescription>
                {tr('handEditsNote', { frequency: frequencyLabel })}
              </AlertDescription>
            </Alert>
          ) : undefined
        }
        canEdit={canEdit}
        initialPath={initialPath}
        linkedChunk={linkedChunk}
        extraContent={
          <ConfirmationModal
            message={tr('removeTitle', {
              name: removal?.name ?? '',
              interpolation: { escapeValue: false },
            })}
            description={removalCopy.description}
            modalState={removal ? 'ACTIVE' : 'INACTIVE'}
            setModalState={(state) => state === 'INACTIVE' && setRemoval(null)}
            handleSubmit={confirmRemove}
            handleCancel={() => setRemoval(null)}
            submitLabel={removalCopy.submit}
            variant="destructive"
            error={(reason) =>
              reason instanceof Error && reason.message === 'last_entry'
                ? tr('removeLast')
                : tr('removeFailed')
            }
          />
        }
      />
      {addOpen && (
        <AddWebsitePagesModal
          sourceId={docId}
          sourceName={sourceName}
          onClose={() => setAddOpen(false)}
          onQueued={(startedAt) =>
            void awaitChange(tr('addingPages'), startedAt, 'addFailed')
          }
        />
      )}
    </>
  );
};

export default WebsiteTree;
