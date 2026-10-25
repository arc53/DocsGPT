import React, { useCallback, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { Check, Cloud, RefreshCw } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Spinner } from '@/components/ui/spinner';
import ConnectorIcon from '../connectors/ConnectorIcon';
import { requestSync, syncRefusal } from '../connectors/syncRefusal';
import ConfirmationModal from '../modals/ConfirmationModal';
import { ActiveState } from '../models/misc';
import { showActionToast } from '../notifications/actionToastSlice';
import { selectToken } from '../preferences/preferenceSlice';
import {
  EMPTY_VALUE,
  formatCount,
  formatRelative,
} from '../utils/dateTimeUtils';
import type { Crumb } from './tree/PathHeader';
import TreeBrowser from './tree/TreeBrowser';
import type { TreeBrowserController } from './tree/types';
import { useReingestSseWaiter } from './tree/useReingestWait';
import type { LinkedChunk } from './chunkUtils';

interface ConnectorTreeProps {
  docId: string;
  sourceName: string;
  onBackToDocuments: () => void;
  /** Extra header control, rendered left of the Sync now button. */
  headerAction?: React.ReactNode;
  /** The source's ⋯, last in the title row; not drawn when embedded. */
  headerMenu?: React.ReactNode;
  /**
   * The source's stored type. A `connector*` source syncs through the
   * connector endpoint; one typed by its loader (S3, GitHub) through the
   * remote-source one.
   */
  sourceType?: string;
  /** The connection the source syncs from, when known: the header badge. */
  connection?: { name: string; icon: string };
  /** `sources.sync_frequency`; a schedule other than never joins the byline. */
  syncFrequency?: string;
  /** When the source was last ingested or synced. */
  syncedAt?: string;
  /**
   * Inside another source view (the graph source's Files tab): no Sources
   * crumb, badge or byline, and no headerAction; Sync stays.
   */
  embedded?: boolean;
  /** Embedded only: the host header's action slot (see TreeBrowser). */
  actionsTarget?: HTMLElement | null;
  /** A file to open once the structure loads (path, file name or display name). */
  initialPath?: string;
  /** The cited chunk to open in `initialPath`'s chunk list (see `LinkedChunk`). */
  linkedChunk?: LinkedChunk;
  /** Embedded only: the tree's crumbs, for the host's header (see TreeBrowser). */
  onCrumbsChange?: (crumbs: Crumb[]) => void;
  /**
   * Whether the caller may change the source (`can(source, 'edit')`).
   * False hides Sync now and the chunk writes; browsing stays.
   */
  canEdit?: boolean;
  /**
   * Whether the source can sync at all (`canSyncSource`): false hides Sync
   * now, as for a connector source whose account connection was removed.
   */
  canSync?: boolean;
}

// Provider names are brand names, so they are not translated.
const PROVIDER_LABELS: Record<string, string> = {
  google_drive: 'Google Drive',
  share_point: 'SharePoint',
  confluence: 'Confluence',
};

/**
 * The display name of a connector provider: a known brand name, else the raw
 * id with underscores as spaces, title-cased ("box_sync" → "Box Sync").
 */
export function providerLabel(provider: string): string {
  const known = PROVIDER_LABELS[provider.toLowerCase()];
  if (known) return known;
  return provider
    .split('_')
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

/**
 * Why the worker skipped a queued sync, by its failed event's `reason`: the
 * source became a wiki, or was deleted (`busy` is a warning, worded apart).
 */
const SKIPPED_SYNC_KEYS: Record<string, string> = {
  wiki: 'settings.connectors.detail.syncRefusedWiki',
  gone: 'settings.sources.website.sourceGone',
};

const ConnectorTree: React.FC<ConnectorTreeProps> = ({
  docId,
  sourceName,
  onBackToDocuments,
  headerAction,
  headerMenu,
  sourceType = 'connector:file',
  connection,
  syncFrequency,
  syncedAt,
  embedded = false,
  actionsTarget,
  initialPath,
  linkedChunk,
  onCrumbsChange,
  canEdit = true,
  canSync = true,
}) => {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const token = useSelector(selectToken);

  const [isSyncing, setIsSyncing] = useState(false);
  const [syncProgress, setSyncProgress] = useState(0);
  const [syncDone, setSyncDone] = useState(false);
  const [sourceProvider, setSourceProvider] = useState('');
  const [syncConfirmationModal, setSyncConfirmationModal] =
    useState<ActiveState>('INACTIVE');

  const controllerRef = useRef<TreeBrowserController | null>(null);
  const { waitForChange, mountedRef } = useReingestSseWaiter();

  /**
   * A failed sync as a destructive toast: the forbidden message on a 403,
   * else why the server refused (see `syncRefusal`), else the generic line.
   */
  const toastSyncFailed = (status?: number, data?: unknown) =>
    dispatch(
      showActionToast({
        variant: 'destructive',
        message: syncRefusal(t, data, {
          status,
          fallback: t('settings.sources.errors.sync'),
          forbidden: true,
        }),
      }),
    );

  const handleSync = async () => {
    if (isSyncing) return;

    setIsSyncing(true);
    setSyncProgress(0);

    try {
      const { accepted, status, data, taskId } = await requestSync(
        docId,
        sourceType,
        token,
      );

      if (accepted) {
        dispatch(
          showActionToast({
            variant: 'success',
            message: t('settings.sources.syncStarted', {
              name: sourceName,
              interpolation: { escapeValue: false },
            }),
          }),
        );
        setSyncProgress(10);

        // Sync mode reuses the source uuid for ``scope.id``, so we wait
        // on the same SSE channel FileTree uses for ingest terminals.
        // ``opStartedAt`` guards against a stale terminal from a prior
        // sync of this same source short-circuiting the current op; a
        // sync's events also carry its task id, which decides when present.
        const opStartedAt = Date.now();
        const { terminal, reason } = await waitForChange(docId, opStartedAt, {
          taskId,
        });

        if (terminal === 'timeout') {
          // Still running past the wait: the toast said it started, and the
          // tree refreshes when the source is opened again.
          console.error('Sync timed out waiting for SSE terminal');
        } else if (terminal === 'unmounted') {
          return;
        }

        if (terminal === 'completed') {
          // The "no files downloaded" early-return path publishes
          // ``completed`` with ``no_changes: true`` — treated as success
          // here; refreshing the directory is cheap and idempotent.
          setSyncProgress(100);

          try {
            const refreshed = await controllerRef.current?.refreshDirectory();
            if (refreshed) {
              controllerRef.current?.resetPath();
            }
            if (mountedRef.current) {
              setSyncDone(true);
              setTimeout(() => {
                if (mountedRef.current) setSyncDone(false);
              }, 5000);
            }
          } catch (err) {
            console.error('Error refreshing directory structure:', err);
          }
        } else if (terminal === 'failed' && reason === 'busy') {
          // The worker skipped it: another change held the source too long.
          dispatch(
            showActionToast({
              variant: 'warning',
              message: t('settings.sources.website.changeBusy'),
            }),
          );
        } else if (terminal === 'failed') {
          const skipped = reason ? SKIPPED_SYNC_KEYS[reason] : undefined;
          if (skipped)
            dispatch(
              showActionToast({ variant: 'destructive', message: t(skipped) }),
            );
          else toastSyncFailed();
        }
      } else {
        toastSyncFailed(status, data);
      }
    } catch (err) {
      console.error('Error syncing source:', err);
      toastSyncFailed();
    } finally {
      setIsSyncing(false);
      setSyncProgress(0);
    }
  };

  const topRightAction = (
    <>
      {embedded ? null : headerAction}
      {canEdit && canSync ? (
        <Button
          type="button"
          size="field"
          shape="pill"
          onClick={() => setSyncConfirmationModal('ACTIVE')}
          disabled={isSyncing}
        >
          {syncDone ? (
            <Check />
          ) : isSyncing ? (
            // The busy state shows its percentage, so it keeps the label and
            // draws the app's ring spinner at icon size (DESIGN.md, Button).
            <Spinner size="xs" label={t('settings.sources.syncing')} />
          ) : (
            <RefreshCw />
          )}
          {isSyncing
            ? `${syncProgress}%`
            : syncDone
              ? t('settings.sources.syncDone')
              : t('settings.sources.syncNow')}
        </Button>
      ) : null}
    </>
  );

  // The files and tokens, then the schedule when it runs:
  // "12 files · 13,080 tokens · Weekly · synced 2 days ago"; an unknown
  // sync time is the dash, as on the source's card.
  const schedule =
    syncFrequency && syncFrequency !== 'never' ? syncFrequency : null;
  const renderByline = useCallback(
    ({ files, tokens }: { files: number; tokens: number }) =>
      [
        t('settings.sources.filesByline', {
          count: files,
          files: formatCount(files),
          tokens: formatCount(tokens),
        }),
        schedule
          ? t('settings.sources.website.synced', {
              frequency: t(`settings.sources.syncFrequency.${schedule}`),
              when: formatRelative(syncedAt) ?? EMPTY_VALUE,
            })
          : null,
      ]
        .filter(Boolean)
        .join(' · '),
    [t, schedule, syncedAt],
  );

  const extraContent = (
    <ConfirmationModal
      message={t('settings.sources.syncConfirmation', {
        interpolation: { escapeValue: false },
        sourceName,
      })}
      description={t('settings.sources.syncConsequence')}
      modalState={syncConfirmationModal}
      setModalState={setSyncConfirmationModal}
      // The sync runs for minutes with its own progress, so the dialog
      // closes at once rather than waiting on it.
      handleSubmit={() => {
        void handleSync();
      }}
      submitLabel={t('settings.sources.syncNow')}
      cancelLabel={t('cancel')}
    />
  );

  return (
    <TreeBrowser
      docId={docId}
      sourceName={sourceName}
      onBackToDocuments={onBackToDocuments}
      embedded={embedded}
      onCrumbsChange={onCrumbsChange}
      canEdit={canEdit}
      actionsTarget={actionsTarget}
      initialPath={initialPath}
      linkedChunk={linkedChunk}
      badge={
        connection ? (
          <Badge variant="neutral">
            <ConnectorIcon icon={connection.icon} />
            {connection.name}
          </Badge>
        ) : sourceProvider ? (
          <Badge variant="neutral">
            <Cloud />
            {providerLabel(sourceProvider)}
          </Badge>
        ) : undefined
      }
      renderByline={renderByline}
      columnOrder="tokens-first"
      sortEntries
      controllerRef={controllerRef}
      topRightAction={topRightAction}
      headerMenu={headerMenu}
      extraContent={extraContent}
      onDirectoryDataLoaded={(data) => {
        if (data && data.provider) {
          setSourceProvider(data.provider);
        }
      }}
    />
  );
};

export default ConnectorTree;
