import React, { useCallback, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { Check, Cloud, RefreshCw } from 'lucide-react';

import userService from '../api/services/userService';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Spinner } from '@/components/ui/spinner';
import ConnectorIcon from '../connectors/ConnectorIcon';
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
  const { waitForTerminal, mountedRef } = useReingestSseWaiter();

  /** A failed sync as a destructive toast: the forbidden message on a 403. */
  const toastSyncFailed = (status?: number) =>
    dispatch(
      showActionToast({
        variant: 'destructive',
        message:
          status === 403
            ? t('settings.sources.errors.forbidden')
            : t('settings.sources.errors.sync'),
      }),
    );

  const handleSync = async () => {
    if (isSyncing) return;

    setIsSyncing(true);
    setSyncProgress(0);

    try {
      const response = sourceType.startsWith('connector')
        ? await userService.syncConnector(docId, token)
        : await userService.syncSource({ source_id: docId }, token);
      const data = await response.json().catch(() => ({}));

      if (response.ok !== false && data?.success) {
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
        const terminal = await waitForTerminal(docId, opStartedAt, {
          taskId: typeof data?.task_id === 'string' ? data.task_id : null,
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
        } else if (terminal === 'failed') {
          toastSyncFailed();
        }
      } else {
        toastSyncFailed(response.status);
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
      {canEdit ? (
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
