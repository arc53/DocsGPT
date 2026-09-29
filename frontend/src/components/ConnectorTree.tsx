import React, { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { Check, Cloud, RefreshCw } from 'lucide-react';

import userService from '../api/services/userService';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Spinner } from '@/components/ui/spinner';
import ConfirmationModal from '../modals/ConfirmationModal';
import { ActiveState } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import type { Crumb } from './tree/PathHeader';
import TreeBrowser from './tree/TreeBrowser';
import type { TreeBrowserController } from './tree/types';
import { useReingestSseWaiter } from './tree/useReingestWait';

interface ConnectorTreeProps {
  docId: string;
  sourceName: string;
  onBackToDocuments: () => void;
  /** Extra header control, rendered left of the Sync button. */
  headerAction?: React.ReactNode;
  /**
   * Inside another source view (the graph source's Files tab): no Sources
   * crumb, badge or byline, and no headerAction; Sync stays.
   */
  embedded?: boolean;
  /** Embedded only: the host header's action slot (see TreeBrowser). */
  actionsTarget?: HTMLElement | null;
  /** A file to open once the structure loads (path, file name or display name). */
  initialPath?: string;
  /** Embedded only: the tree's crumbs, for the host's header (see TreeBrowser). */
  onCrumbsChange?: (crumbs: Crumb[]) => void;
  /**
   * Whether the caller may change the source (`can(source, 'edit')`).
   * False hides Sync and the chunk writes; browsing stays.
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
  embedded = false,
  actionsTarget,
  initialPath,
  onCrumbsChange,
  canEdit = true,
}) => {
  const { t } = useTranslation();
  const token = useSelector(selectToken);

  const [isSyncing, setIsSyncing] = useState(false);
  const [syncProgress, setSyncProgress] = useState(0);
  const [syncDone, setSyncDone] = useState(false);
  const [sourceProvider, setSourceProvider] = useState('');
  const [syncConfirmationModal, setSyncConfirmationModal] =
    useState<ActiveState>('INACTIVE');

  const controllerRef = useRef<TreeBrowserController | null>(null);
  const { waitForTerminal, mountedRef } = useReingestSseWaiter();

  const handleSync = async () => {
    if (isSyncing) return;

    const provider = sourceProvider;

    setIsSyncing(true);
    setSyncProgress(0);

    try {
      const response = await userService.syncConnector(docId, token);
      const data = await response.json();

      if (data.success) {
        console.log('Sync started successfully:', data.task_id);
        setSyncProgress(10);

        // Sync mode reuses the source uuid for ``scope.id``, so we wait
        // on the same SSE channel FileTree uses for ingest terminals.
        // ``opStartedAt`` guards against a stale terminal from a prior
        // sync of this same source short-circuiting the current op.
        const opStartedAt = Date.now();
        const terminal = await waitForTerminal(docId, opStartedAt);

        if (terminal === 'timeout') {
          console.error('Sync timed out waiting for SSE terminal');
        } else if (terminal === 'unmounted') {
          return;
        }

        if (terminal === 'completed') {
          // The "no files downloaded" early-return path publishes
          // ``completed`` with ``no_changes: true`` — treated as success
          // here; refreshing the directory is cheap and idempotent.
          setSyncProgress(100);
          console.log('Sync completed successfully');

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
          console.error('Sync task failed (per SSE)');
        }
      } else {
        console.error('Sync failed:', data.error);
      }
    } catch (err) {
      console.error('Error syncing connector:', err);
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
              : t('settings.sources.sync')}
        </Button>
      ) : null}
    </>
  );

  const extraContent = (
    <ConfirmationModal
      message={t('settings.sources.syncConfirmation', { sourceName })}
      modalState={syncConfirmationModal}
      setModalState={setSyncConfirmationModal}
      handleSubmit={handleSync}
      submitLabel={t('settings.sources.sync')}
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
      badge={
        sourceProvider ? (
          <Badge variant="neutral">
            <Cloud />
            {providerLabel(sourceProvider)}
          </Badge>
        ) : undefined
      }
      columnOrder="tokens-first"
      sortEntries
      controllerRef={controllerRef}
      topRightAction={topRightAction}
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
