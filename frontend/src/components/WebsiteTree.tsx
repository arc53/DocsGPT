import { ExternalLink, Globe, RefreshCw, Trash2 } from 'lucide-react';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import userService from '../api/services/userService';
import ConfirmationModal from '../modals/ConfirmationModal';
import { showActionToast } from '../notifications/actionToastSlice';
import { selectToken } from '../preferences/preferenceSlice';
import { pageKey, websiteRefusal } from '../upload/website';
import { formatCount, formatRelative } from '../utils/dateTimeUtils';
import AddWebsitePagesModal from './AddWebsitePagesModal';
import type { LinkedChunk } from './chunkUtils';
import TreeBrowser from './tree/TreeBrowser';
import { folderAddress, webHref } from './tree/pages';
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

/** A URL's origin (`http://docs.x.io:8080`), or null when it isn't a web one. */
function originOf(url: unknown): string | null {
  const href = webHref(url);
  if (!href) return null;
  try {
    return new URL(href).origin;
  } catch {
    return null;
  }
}

/** A URL's host with its port, or '' when it doesn't parse. */
function hostOf(url: string): string {
  try {
    return url ? new URL(url).host : '';
  } catch {
    return '';
  }
}

/**
 * The origin of the first page on `host` (a hostname without `www.` or a
 * port, as the sources list gives it), so the link keeps the site's own
 * scheme and port.
 */
function pageOrigin(
  structure: DirectoryStructure,
  host: string,
): string | null {
  for (const node of Object.values(structure ?? {})) {
    if (!node || typeof node !== 'object') continue;
    if (!('token_count' in node)) {
      const origin = pageOrigin(node as DirectoryStructure, host);
      if (origin) return origin;
      continue;
    }
    const origin = originOf(node.url);
    if (origin && new URL(origin).hostname.replace(/^www\./, '') === host)
      return origin;
  }
  return null;
}

/** A remove the server refused; its message is what the dialog shows. */
class RemoveRefused extends Error {}

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
  // The origin of the config's first entry (scheme, host and port).
  const [firstEntryOrigin, setFirstEntryOrigin] = useState<string | null>(null);
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
        setFirstEntryOrigin(originOf(entries[0]?.url));
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
    (key: string, name?: string, message?: string | null) =>
      dispatch(
        showActionToast({
          variant: 'destructive',
          message:
            message ?? tr(key, { name, interpolation: { escapeValue: false } }),
        }),
      ),
    // tr reads t, which is stable per language.
    [dispatch, t],
  );

  /**
   * Waits for a background change to finish, then reloads the tree and the
   * open page's chunks (all of them, or only when `changedPath` is open).
   */
  const awaitChange = async (
    label: string,
    startedAt: number,
    failure: string,
    {
      name,
      taskId,
      changedPath,
    }: { name?: string; taskId?: string | null; changedPath?: string } = {},
  ) => {
    setStatus(label);
    const terminal = await waitForTerminal(docId, startedAt, { taskId });
    if (!mountedRef.current) return;
    setStatus(null);
    if (terminal === 'completed') {
      await controllerRef.current?.refreshDirectory();
      if (changedPath !== undefined)
        controllerRef.current?.reloadFile(changedPath);
      else controllerRef.current?.reloadFile();
      setConfigKey((key) => key + 1);
    } else if (terminal === 'failed') {
      toastFailure(failure, name);
    }
  };

  const refreshPage = async (path: string, name: string) => {
    const startedAt = Date.now();
    let taskId: string | null = null;
    // Taken at once: the menu turns its changes off until this one is done.
    setStatus(tr('refreshing'));
    let refusal: string | null = null;
    try {
      const response = await userService.refreshWebsitePage(
        { source_id: docId, file_path: path },
        token,
      );
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        refusal = websiteRefusal(t, response.status, data);
        throw new Error('refresh failed');
      }
      taskId = typeof data?.task_id === 'string' ? data.task_id : null;
    } catch {
      if (mountedRef.current) setStatus(null);
      toastFailure('refreshFailed', name, refusal);
      return;
    }
    await awaitChange(tr('refreshing'), startedAt, 'refreshFailed', {
      name,
      taskId,
      changedPath: path,
    });
  };

  const confirmRemove = async () => {
    if (!removal) return;
    const body = removal.isFile
      ? { source_id: docId, file_paths: [removal.path] }
      : { source_id: docId, directory_path: removal.path };
    const response = await userService.removeWebsitePages(body, token);
    const data = await response.json().catch(() => null);
    if (!response.ok || !data?.success)
      throw new RemoveRefused(
        websiteRefusal(t, response.status, data) ?? tr('removeFailed'),
      );
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
      where: hostOf(url),
    });
  };

  const openLink = (url: string | null, label: string) =>
    url ? (
      <Button variant="link" size="inline" asChild>
        <a href={url} target="_blank" rel="noopener noreferrer">
          {label}
          <ExternalLink />
        </a>
      </Button>
    ) : (
      label
    );

  const synced = !!syncFrequency && syncFrequency !== 'never';
  const frequencyLabel = synced
    ? t(`settings.sources.syncFrequency.${syncFrequency}`)
    : '';
  const syncLine = synced
    ? tr('synced', {
        frequency: frequencyLabel,
        when: formatRelative(syncedAt) ?? '',
        interpolation: { escapeValue: false },
      })
    : tr('notSynced');

  // Always the source's line, even with a page open (the page has its bar).
  const renderByline = ({
    files,
    tokens,
  }: {
    files: number;
    tokens: number;
  }) => {
    const parts: React.ReactNode[] = [];
    if (hosts.length === 1) {
      parts.push(
        <span className="inline-flex items-center gap-1.5">
          <Globe className="size-4" aria-hidden="true" />
          {openLink(
            firstEntryOrigin ??
              pageOrigin(structure, hosts[0]) ??
              `https://${hosts[0]}`,
            hosts[0],
          )}
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
    const href = webHref(url);
    const options: MenuOption[] = [defaultViewOption];
    if (href) {
      options.push({
        icon: ExternalLink,
        label: tr('openPage'),
        onClick: () => window.open(href, '_blank', 'noopener,noreferrer'),
      });
    }
    if (!canEdit) return options;
    // One change at a time: a refresh, add or remove waits for the last.
    const busy = !!status;
    if (url) {
      options.push({
        icon: RefreshCw,
        label: tr('refreshPage'),
        disabled: busy,
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
      disabled: busy,
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
        description: tr('removeFolder', {
          address: removal.where,
          interpolation: { escapeValue: false },
        }),
        submit: tr('removeAndSkip'),
      };
    return {
      description: tr('removeCrawled', {
        host: removal.where,
        interpolation: { escapeValue: false },
      }),
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
                {tr('handEditsNote', {
                  frequency: frequencyLabel,
                  interpolation: { escapeValue: false },
                })}
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
              reason instanceof RemoveRefused
                ? reason.message
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
          onQueued={(startedAt, taskId) =>
            void awaitChange(tr('addingPages'), startedAt, 'addFailed', {
              taskId,
            })
          }
        />
      )}
    </>
  );
};

export default WebsiteTree;
