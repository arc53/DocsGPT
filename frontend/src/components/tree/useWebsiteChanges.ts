import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch } from 'react-redux';

import { showActionToast } from '../../notifications/actionToastSlice';
import { pageAddress } from './pages';
import { type ReingestTerminal, useReingestSseWaiter } from './useReingestWait';

/** A sync the host started: when its request went out and the task it queued. */
export type WebsiteSync = { startedAt: number; taskId: string | null };

/** What the page list does once a change it shows has landed. */
export interface WebsiteTreeHandle {
  /**
   * Reads the tree and the source's list of addresses again, and the open
   * page's chunks when it is one of `paths` (the pages the change wrote or
   * removed; a removed open page closes by itself) or `paths` is null (a
   * sync or rebuild, which may change any page).
   */
  reload: (paths: string[] | null) => Promise<void>;
}

export interface AwaitChangeOptions {
  /** The page's name, for the failure's wording. */
  name?: string;
  /** The task the change queued; matched when its event carries one. */
  taskId?: string | null;
  /**
   * A hold from {@link WebsiteChanges.begin} taken before the request went
   * out; the wait releases it instead of taking its own.
   */
  hold?: number;
}

/** A Website source's page changes in flight, and how to wait for one. */
export interface WebsiteChanges {
  /** The label of the latest change still running, or null when none is. */
  status: string | null;
  /** Marks a change as running under `label` until {@link end}; returns its hold. */
  begin: (label: string) => number;
  /** Ends a hold from {@link begin}. */
  end: (hold: number) => void;
  /**
   * Waits for a queued change to finish, shown as running under `label`
   * meanwhile, then has the page list read what it touched again (when it is
   * mounted), tells the host the pages changed, and toasts how a change
   * that didn't simply finish ended (`failure` is its website key).
   * Resolves with how the wait ended, `unmounted` when the owner went first.
   */
  awaitChange: (
    label: string,
    startedAt: number,
    failure: string,
    options?: AwaitChangeOptions,
  ) => Promise<ReingestTerminal>;
  /** The page list, while mounted; returns the detach. */
  attach: (tree: WebsiteTreeHandle) => () => void;
}

export interface UseWebsiteChangesOptions {
  docId: string;
  /**
   * A sync of the source the host started (the source's ⋯ → Sync now). It
   * is waited for as a change of its own; a new object starts a new wait,
   * the same one is waited for once.
   */
  sync?: WebsiteSync | null;
  /**
   * The wait for `sync` ended: the sync finished, failed, was skipped or is
   * still running past the wait. Not called when the owner unmounts first.
   */
  onSyncSettled?: (sync: WebsiteSync) => void;
  /** A change (add, refresh, remove, a sync) has finished. */
  onPagesChanged?: () => void;
  /** Whether any change is in flight, each time that turns. */
  onBusyChange?: (busy: boolean) => void;
}

/**
 * The page changes of a Website source (Add pages, Refresh page, Remove, a
 * sync started from the source's ⋯) and their waits, held by the view that
 * outlives the page list: a graph source's Files tab mounts the list only
 * while it is open, but its changes keep running when another tab shows,
 * and the view still says so and still hears when they end.
 *
 * Changes may overlap (a refresh, then a sync): each holds the busy state
 * until it ends, and the latest one's label shows.
 *
 * @returns The {@link WebsiteChanges}.
 */
export function useWebsiteChanges({
  docId,
  sync,
  onSyncSettled,
  onPagesChanged,
  onBusyChange,
}: UseWebsiteChangesOptions): WebsiteChanges {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const { waitForChange, mountedRef } = useReingestSseWaiter();
  const tr = useCallback(
    (key: string, options?: Record<string, unknown>) =>
      t(`settings.sources.website.${key}`, options),
    [t],
  );

  const [holds, setHolds] = useState<{ id: number; label: string }[]>([]);
  const nextHold = useRef(0);
  const begin = useCallback((label: string) => {
    nextHold.current += 1;
    const id = nextHold.current;
    setHolds((current) => [...current, { id, label }]);
    return id;
  }, []);
  const end = useCallback(
    (id: number) =>
      setHolds((current) => current.filter((hold) => hold.id !== id)),
    [],
  );

  const treeRef = useRef<WebsiteTreeHandle | null>(null);
  const attach = useCallback((tree: WebsiteTreeHandle) => {
    treeRef.current = tree;
    return () => {
      if (treeRef.current === tree) treeRef.current = null;
    };
  }, []);

  const onPagesChangedRef = useRef(onPagesChanged);
  onPagesChangedRef.current = onPagesChanged;
  const onSyncSettledRef = useRef(onSyncSettled);
  onSyncSettledRef.current = onSyncSettled;
  const onBusyChangeRef = useRef(onBusyChange);
  onBusyChangeRef.current = onBusyChange;
  const docIdRef = useRef(docId);
  docIdRef.current = docId;

  const awaitChange = useCallback(
    async (
      label: string,
      startedAt: number,
      failure: string,
      { name, taskId, hold }: AwaitChangeOptions = {},
    ): Promise<ReingestTerminal> => {
      const id = hold ?? begin(label);
      const { terminal, reason, failedPages, paths } = await waitForChange(
        docIdRef.current,
        startedAt,
        { taskId },
      );
      // An unmount (StrictMode's too) ends the wait and its hold.
      end(id);
      if (!mountedRef.current || terminal === 'unmounted') return 'unmounted';
      const reload = (changed: string[] | null) =>
        treeRef.current?.reload(changed);
      const toast = (
        variant: 'info' | 'warning' | 'destructive',
        message: string,
      ) => dispatch(showActionToast({ variant, message }));
      if (terminal === 'completed') {
        await reload(paths);
        onPagesChangedRef.current?.();
        // Added pages the worker couldn't fetch stay listed, and the next
        // sync tries them again.
        if (failedPages.length === 1)
          toast(
            'warning',
            tr('pageNotFetched', {
              url: pageAddress(failedPages[0]),
              interpolation: { escapeValue: false },
            }),
          );
        else if (failedPages.length > 1)
          toast(
            'warning',
            tr('pagesNotFetched', { count: failedPages.length }),
          );
      } else if (terminal === 'timeout') {
        // Still queued or running: the buttons come back, and the tree
        // shows whatever has landed so far.
        await reload([]);
        toast('info', tr('stillRunning'));
      } else if (reason === 'out_of_scope') {
        // A refreshed page that now leads outside the source: the worker
        // removed it, as a sync would.
        await reload([]);
        onPagesChangedRef.current?.();
        toast(
          'warning',
          tr('refreshOutOfScope', {
            name,
            interpolation: { escapeValue: false },
          }),
        );
      } else if (reason === 'busy') {
        toast('warning', tr('changeBusy'));
      } else {
        toast(
          'destructive',
          tr(
            reason === 'wiki'
              ? 'wikiSource'
              : reason === 'gone'
                ? 'sourceGone'
                : failure,
            { name, interpolation: { escapeValue: false } },
          ),
        );
      }
      return terminal;
    },
    [begin, end, waitForChange, mountedRef, dispatch, tr],
  );

  // A sync the host started is waited for like the list's own changes.
  const awaitChangeRef = useRef(awaitChange);
  awaitChangeRef.current = awaitChange;
  const waitedSync = useRef<WebsiteSync | null>(null);
  useEffect(() => {
    if (!sync || waitedSync.current === sync) return;
    waitedSync.current = sync;
    void awaitChangeRef
      .current(tr('syncing'), sync.startedAt, 'syncFailed', {
        taskId: sync.taskId,
      })
      .then((terminal) => {
        if (terminal !== 'unmounted') onSyncSettledRef.current?.(sync);
      });
    // StrictMode's second run starts the wait again; the first one ends
    // with the unmount it saw.
    return () => {
      waitedSync.current = null;
    };
    // tr reads t, which is stable per language.
  }, [sync]);

  const busy = holds.length > 0;
  useEffect(() => {
    onBusyChangeRef.current?.(busy);
  }, [busy]);
  useEffect(() => () => onBusyChangeRef.current?.(false), []);

  return {
    status: holds[holds.length - 1]?.label ?? null,
    begin,
    end,
    awaitChange,
    attach,
  };
}
