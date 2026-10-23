import { ExternalLink, Globe, RefreshCw, Trash2 } from 'lucide-react';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import userService from '../api/services/userService';
import ConfirmationModal from '../modals/ConfirmationModal';
import { showActionToast } from '../notifications/actionToastSlice';
import { selectToken } from '../preferences/preferenceSlice';
import { isQueueFailed, pageKey, websiteRefusal } from '../upload/website';
import { formatCount, formatRelative } from '../utils/dateTimeUtils';
import AddWebsitePagesModal from './AddWebsitePagesModal';
import type { LinkedChunk } from './chunkUtils';
import type { Crumb } from './tree/PathHeader';
import TreeBrowser from './tree/TreeBrowser';
import { folderAddress, webHref } from './tree/pages';
import type {
  DirectoryStructure,
  FileNode,
  RowMenuContext,
  TreeBrowserController,
} from './tree/types';
import {
  type WebsiteChanges,
  type WebsiteSync,
  useWebsiteChanges,
} from './tree/useWebsiteChanges';
import { Alert, AlertDescription } from './ui/alert';
import { Button } from './ui/button';
import type { MenuOption } from './ui/dropdown-menu';

interface WebsiteTreeProps {
  docId: string;
  sourceName: string;
  onBackToDocuments: () => void;
  /** Extra header control (Test retrieval); not drawn when embedded. */
  headerAction?: React.ReactNode;
  /** The source's ⋯, last in the title row; not drawn when embedded. */
  headerMenu?: React.ReactNode;
  /**
   * Inside another source view (the graph source's Files tab): no Sources
   * crumb, badge or byline, and no headerAction; Add pages stays.
   */
  embedded?: boolean;
  /** Embedded only: the host header's action slot (see TreeBrowser). */
  actionsTarget?: HTMLElement | null;
  /** Embedded only: the tree's crumbs, for the host's header (see TreeBrowser). */
  onCrumbsChange?: (crumbs: Crumb[]) => void;
  /** The source has a knowledge graph: Add pages says new pages are extracted into it. */
  graph?: boolean;
  /** The hosts the source fetches from (the sources list's `website.hosts`). */
  hosts: string[];
  /**
   * Called once a page change (add, refresh, remove) has finished, so a host
   * showing more of the source (the graph) can read it again.
   */
  onPagesChanged?: () => void;
  /** `sources.sync_frequency`; never (or empty) reads "Not synced". */
  syncFrequency?: string;
  /** When the source was last ingested or synced. */
  syncedAt?: string;
  /**
   * A sync of this source the host started (the source's ⋯ → Sync now), with
   * when its request went out and the task it queued. The tree waits for it
   * as for its own changes: busy meanwhile, then read again. A new object
   * starts a new wait; the same one is waited for once. Ignored with
   * `changes`, whose owner waits for it.
   */
  sync?: WebsiteSync | null;
  /**
   * The wait for `sync` ended: the sync finished, failed, was skipped or is
   * still running past the wait. Not called when the tree unmounts first.
   */
  onSyncSettled?: (sync: WebsiteSync) => void;
  /**
   * Whether a page change or a sync is in flight, each time that turns, so
   * the host can hold its own Sync now meanwhile. Ignored with `changes`.
   */
  onBusyChange?: (busy: boolean) => void;
  /**
   * The source's changes, held by a host that outlives the tree (the graph
   * source's Files tab is mounted only while open; see `useWebsiteChanges`).
   * Without it the tree holds its own, with `sync`, `onSyncSettled`,
   * `onPagesChanged` and `onBusyChange`.
   */
  changes?: WebsiteChanges;
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

/** The page at a tree path (`Deploying/Docker.md`), or null. */
function pageAt(structure: DirectoryStructure, path: string): FileNode | null {
  let node: unknown = structure;
  for (const part of path.split('/')) {
    if (!node || typeof node !== 'object') return null;
    node = (node as DirectoryStructure)[part];
  }
  return node && typeof node === 'object' && 'token_count' in node
    ? (node as FileNode)
    : null;
}

/**
 * The keys a page answers to: its address, and the one it was added under
 * when fetching it was redirected (`requested_url`), so a page added as
 * `/old` that landed on `/new` still matches its entry.
 */
function pageKeysOf(node: FileNode | null | undefined): string[] {
  return [node?.url, node?.requested_url]
    .filter((url): url is string => typeof url === 'string' && !!url)
    .map(pageKey);
}

/** A remove the server refused; its message is what the dialog shows. */
class RemoveRefused extends Error {}

/** What a remove asks to confirm: its copy depends on where the page came from. */
type PendingRemoval = {
  name: string;
  path: string;
  isFile: boolean;
  /** A page's keys (see {@link pageKeysOf}); none for a folder. */
  keys: string[];
  /**
   * The page's host, or the folder's address; null for a page (or a folder
   * of pages) without an address, from before pages kept theirs.
   */
  where: string | null;
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
  embedded = false,
  actionsTarget,
  onCrumbsChange,
  graph = false,
  hosts,
  onPagesChanged,
  syncFrequency,
  syncedAt,
  sync,
  onSyncSettled,
  onBusyChange,
  changes: hostChanges,
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
  // Read by a change's wait, which outlives the render that started it.
  const structureRef = useRef(structure);
  structureRef.current = structure;
  // Keys of the pages the source lists by address (from its config); null
  // until the config has loaded, and when it couldn't be read, so no page is
  // called crawled (or an entry) on a guess.
  const [pageEntries, setPageEntries] = useState<Set<string> | null>(null);
  // The origin of the config's first entry (scheme, host and port).
  const [firstEntryOrigin, setFirstEntryOrigin] = useState<string | null>(null);
  const [configKey, setConfigKey] = useState(0);
  const [addOpen, setAddOpen] = useState(false);
  const [removal, setRemoval] = useState<PendingRemoval | null>(null);
  // A host's changes outlive the tree; without one the tree holds its own.
  const ownChanges = useWebsiteChanges({
    docId,
    sync: hostChanges ? null : sync,
    onSyncSettled: hostChanges ? undefined : onSyncSettled,
    onPagesChanged: hostChanges ? undefined : onPagesChanged,
    onBusyChange: hostChanges ? undefined : onBusyChange,
  });
  const changes = hostChanges ?? ownChanges;
  const status = changes.status;

  const tokenRef = useRef(token);
  tokenRef.current = token;
  // Another source's entries and first address never stand in for this
  // one's (a source the caller only reads never loads its own).
  useEffect(() => {
    setPageEntries(null);
    setFirstEntryOrigin(null);
  }, [docId]);
  useEffect(() => {
    if (!canEdit) return;
    let cancelled = false;
    userService
      .getWebsite(docId, tokenRef.current)
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (cancelled) return;
        if (!data?.config) {
          setPageEntries(null);
          return;
        }
        const entries = data.config.entries as { url: string; mode: string }[];
        setFirstEntryOrigin(originOf(entries[0]?.url));
        setPageEntries(
          new Set(
            entries.filter((e) => e.mode === 'page').map((e) => pageKey(e.url)),
          ),
        );
      })
      .catch(() => {
        if (!cancelled) setPageEntries(null);
      });
    return () => {
      cancelled = true;
    };
  }, [docId, canEdit, configKey]);

  // A finished change reads what it touched again, while the tree shows.
  const { attach } = changes;
  useEffect(
    () =>
      attach({
        reload: async (affects) => {
          await controllerRef.current?.refreshDirectory();
          if (affects === undefined) controllerRef.current?.reloadFile();
          else if (affects !== false)
            controllerRef.current?.reloadFile(affects);
          setConfigKey((key) => key + 1);
        },
      }),
    [attach],
  );

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
   * A change the server saved but couldn't queue: it runs at the next sync.
   * Says so, and reads the source's list again (it may have changed).
   */
  const warnQueueFailed = (message: string) => {
    dispatch(showActionToast({ variant: 'warning', message }));
    setConfigKey((key) => key + 1);
  };

  const refreshPage = async (path: string, name: string, url?: string) => {
    const startedAt = Date.now();
    let taskId: string | null = null;
    // Taken at once: the menu turns its changes off until this one is done.
    const hold = changes.begin(tr('refreshing'));
    let refusal: string | null = null;
    try {
      const response = await userService.refreshWebsitePage(
        // The address too: the server refreshes the page the tree shows.
        { source_id: docId, file_path: path, ...(url ? { url } : {}) },
        token,
      );
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        // A refresh saves nothing first: one the server couldn't queue just
        // failed, unlike an add or a remove (no "the next sync picks it up").
        refusal = isQueueFailed(data)
          ? null
          : websiteRefusal(t, response.status, data);
        throw new Error('refresh failed');
      }
      taskId = typeof data?.task_id === 'string' ? data.task_id : null;
    } catch {
      changes.end(hold);
      toastFailure('refreshFailed', name, refusal);
      return;
    }
    await changes.awaitChange(tr('refreshing'), startedAt, 'refreshFailed', {
      name,
      taskId,
      affects: path,
      hold,
    });
  };

  /**
   * Asks the server to remove the pages. A refusal stays in the dialog; once
   * the removal is queued the dialog closes and the header shows it until the
   * worker has deleted the pages.
   */
  const confirmRemove = async () => {
    if (!removal) return;
    const startedAt = Date.now();
    const body = removal.isFile
      ? { source_id: docId, file_paths: [removal.path] }
      : { source_id: docId, directory_path: removal.path };
    const response = await userService.removeWebsitePages(body, token);
    const data = await response.json().catch(() => null);
    const refusal = websiteRefusal(t, response.status, data);
    if (refusal && isQueueFailed(data)) {
      // Saved: the next sync removes the pages, so the dialog's job is done.
      setRemoval(null);
      warnQueueFailed(refusal);
      return;
    }
    if (!response.ok || !data?.success)
      throw new RemoveRefused(refusal ?? tr('removeFailed'));
    const { name } = removal;
    setRemoval(null);
    void changes.awaitChange(tr('removing'), startedAt, 'removeFailed', {
      name,
      taskId: typeof data.task_id === 'string' ? data.task_id : null,
      affects: false,
    });
  };

  const askRemove = (name: string, isFile: boolean, node?: FileNode) => {
    const path = [...currentPathRef.current, name].join('/');
    if (!isFile) {
      setRemoval({
        name,
        path,
        isFile,
        keys: [],
        where: folderAddress(structure, path),
      });
      return;
    }
    const url = typeof node?.url === 'string' ? node.url : '';
    setRemoval({
      name:
        (typeof node?.display_name === 'string' && node.display_name) || name,
      path,
      isFile,
      keys: pageKeysOf(node),
      where: hostOf(url) || null,
    });
  };

  /**
   * Where a page to remove came from, decided as the dialog draws, so the
   * copy follows the source's list once it loads: `unknown` until then (and
   * when it can't be read, or the page has no address to tell by).
   */
  const removalKind = (
    pending: PendingRemoval,
  ): 'entry' | 'crawled' | 'folder' | 'unknownFolder' | 'unknown' => {
    if (!pending.isFile) return pending.where ? 'folder' : 'unknownFolder';
    if (!pageEntries || !pending.where) return 'unknown';
    return pending.keys.some((key) => pageEntries.has(key))
      ? 'entry'
      : 'crawled';
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
            url,
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
      {embedded ? null : headerAction}
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
    const kind = removalKind(removal);
    if (kind === 'entry')
      return { description: tr('removeEntry'), submit: tr('remove') };
    // Not known yet where it came from: only what holds either way.
    if (kind === 'unknown')
      return { description: tr('removeGeneric'), submit: tr('remove') };
    if (kind === 'unknownFolder')
      return { description: tr('removeFolderGeneric'), submit: tr('remove') };
    if (kind === 'folder')
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
        embedded={embedded}
        actionsTarget={actionsTarget}
        onCrumbsChange={onCrumbsChange}
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
          graph={graph}
          onClose={() => setAddOpen(false)}
          onQueued={(startedAt, taskId, change) => {
            // Appended pages replace only the pages they name (by the
            // address they were added under, too); a rebuild may change any
            // page.
            const added = new Set(change.urls.map(pageKey));
            void changes.awaitChange(
              tr('addingPages'),
              startedAt,
              'addFailed',
              {
                taskId,
                affects:
                  change.mode === 'append'
                    ? (path) =>
                        pageKeysOf(pageAt(structureRef.current, path)).some(
                          (key) => added.has(key),
                        )
                    : undefined,
              },
            );
          }}
          onQueueFailed={warnQueueFailed}
        />
      )}
    </>
  );
};

export default WebsiteTree;
