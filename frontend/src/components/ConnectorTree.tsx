import React, { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import CheckmarkIcon from '../assets/checkMark2.svg';
import SyncIcon from '../assets/sync.svg';
import ConfirmationModal from '../modals/ConfirmationModal';
import { ActiveState } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import TreeBrowser from './tree/TreeBrowser';
import type { TreeBrowserController } from './tree/types';
import { useReingestSseWaiter } from './tree/useReingestWait';

interface ConnectorTreeProps {
  docId: string;
  sourceName: string;
  onBackToDocuments: () => void;
}

const ConnectorTree: React.FC<ConnectorTreeProps> = ({
  docId,
  sourceName,
  onBackToDocuments,
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
      const response = await userService.syncConnector(docId, provider, token);
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
    <button
      onClick={() => setSyncConfirmationModal('ACTIVE')}
      disabled={isSyncing}
      className={`flex h-[38px] min-w-[108px] items-center justify-center rounded-full px-4 text-sm font-medium whitespace-nowrap transition-colors ${
        isSyncing
          ? 'dark:bg-muted dark:text-muted-foreground cursor-not-allowed bg-gray-300 text-gray-600'
          : 'bg-primary hover:bg-primary/90 text-white'
      }`}
      title={
        isSyncing
          ? `${t('settings.sources.syncing')} ${syncProgress}%`
          : syncDone
            ? 'Done'
            : t('settings.sources.sync')
      }
    >
      <img
        src={syncDone ? CheckmarkIcon : SyncIcon}
        alt={t('settings.sources.sync')}
        className={`mr-2 h-4 w-4 brightness-0 invert filter ${isSyncing ? 'animate-spin' : ''}`}
      />
      {isSyncing
        ? `${syncProgress}%`
        : syncDone
          ? 'Done'
          : t('settings.sources.sync')}
    </button>
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
