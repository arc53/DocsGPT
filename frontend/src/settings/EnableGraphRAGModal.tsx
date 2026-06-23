import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import Spinner from '../components/Spinner';
import { Button } from '../components/ui/button';
import { Modal } from '../components/ui/modal';
import { ActiveState, Doc } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';

import {
  GraphRAGSummary,
  pollTaskOnce,
  startGraphRAG,
} from './graphragEnableUtils';

const POLL_INTERVAL_MS = 2000;

type Phase = 'confirm' | 'building' | 'summary' | 'error';

interface EnableGraphRAGModalProps {
  modalState: ActiveState;
  setModalState: (state: ActiveState) => void;
  document: Doc | null;
  onEnabled: () => void;
}

export default function EnableGraphRAGModal({
  modalState,
  setModalState,
  document,
  onEnabled,
}: EnableGraphRAGModalProps) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);

  const [phase, setPhase] = useState<Phase>('confirm');
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<GraphRAGSummary | null>(null);
  const pollTimer = useRef<number | null>(null);
  const isActiveRef = useRef(true);

  const clearPoll = () => {
    if (pollTimer.current !== null) {
      window.clearTimeout(pollTimer.current);
      pollTimer.current = null;
    }
  };

  const stopPolling = () => {
    isActiveRef.current = false;
    clearPoll();
  };

  useEffect(() => {
    if (modalState === 'ACTIVE') {
      isActiveRef.current = true;
      setPhase('confirm');
      setError(null);
      setSummary(null);
    }
    return stopPolling;
  }, [modalState, document]);

  const closeModal = () => {
    stopPolling();
    setModalState('INACTIVE');
  };

  const fail = (message?: string) => {
    setError(message ?? t('settings.sources.graphrag.enable.errors.generic'));
    setPhase('error');
  };

  const poll = (taskId: string) => {
    pollTaskOnce(userService, taskId, token)
      .then((result) => {
        if (!isActiveRef.current) return;
        if (result.status === 'pending') {
          pollTimer.current = window.setTimeout(
            () => poll(taskId),
            POLL_INTERVAL_MS,
          );
          return;
        }
        if (result.status === 'done') {
          setSummary(result.summary);
          setPhase('summary');
          onEnabled();
          return;
        }
        fail(result.message);
      })
      .catch(() => {
        if (!isActiveRef.current) return;
        fail();
      });
  };

  const handleEnable = async () => {
    if (!document?.id) return;
    setPhase('building');
    setError(null);
    const start = await startGraphRAG(userService, document.id, token);
    if (start.status === 'enabled') {
      setSummary({
        nodes: 0,
        edges: 0,
        chunksProcessed: 0,
        skippedOverCap: 0,
        failedChunks: 0,
      });
      setPhase('summary');
      onEnabled();
      return;
    }
    if (start.status === 'task') {
      onEnabled();
      poll(start.taskId);
      return;
    }
    if (start.status === 'forbidden') {
      fail(t('settings.sources.graphrag.enable.errors.forbidden'));
      return;
    }
    if (start.status === 'conflict') {
      fail(
        start.message ?? t('settings.sources.graphrag.enable.errors.conflict'),
      );
      return;
    }
    fail(start.message);
  };

  return (
    <Modal
      open={modalState === 'ACTIVE'}
      onOpenChange={(o) => !o && closeModal()}
      hideTitle
      title={t('settings.sources.graphrag.enable.title')}
      size="md"
      mobileVariant="sheet"
      className="max-w-[480px]"
      isPerformingTask={phase === 'building'}
    >
      <div className="flex flex-col gap-5 px-1 py-1">
        <h2 className="text-foreground text-xl font-semibold">
          {t('settings.sources.graphrag.enable.title')}
        </h2>

        {phase === 'confirm' && (
          <>
            <p className="text-muted-foreground text-sm">
              {document?.name
                ? t('settings.sources.graphrag.enable.intro', {
                    name: document.name,
                  })
                : t('settings.sources.graphrag.enable.introGeneric')}
            </p>
            <ul className="text-muted-foreground list-disc space-y-1.5 pl-5 text-sm">
              <li>{t('settings.sources.graphrag.enable.costExtraction')}</li>
              <li>{t('settings.sources.graphrag.enable.costCost')}</li>
              <li>{t('settings.sources.graphrag.enable.costPgvector')}</li>
            </ul>
            <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
              <Button
                type="button"
                variant="ghost"
                onClick={closeModal}
                className="w-full rounded-3xl px-6 sm:w-auto"
              >
                {t('cancel')}
              </Button>
              <Button
                type="button"
                onClick={handleEnable}
                className="w-full rounded-3xl px-6 sm:w-auto"
              >
                {t('settings.sources.graphrag.enable.confirm')}
              </Button>
            </div>
          </>
        )}

        {phase === 'building' && (
          <div className="flex flex-col items-center gap-3 py-6">
            <Spinner size="medium" />
            <p className="text-muted-foreground text-sm">
              {t('settings.sources.graphrag.enable.inProgress')}
            </p>
          </div>
        )}

        {phase === 'summary' && summary && (
          <>
            <div className="rounded-xl bg-green-50 p-4 text-sm text-green-800 dark:bg-green-900/30 dark:text-green-200">
              {[
                t('settings.sources.graphrag.enable.summaryNodes', {
                  count: summary.nodes,
                }),
                t('settings.sources.graphrag.enable.summaryEdges', {
                  count: summary.edges,
                }),
                t('settings.sources.graphrag.enable.summaryChunks', {
                  count: summary.chunksProcessed,
                }),
              ].join(' · ')}
            </div>
            <div className="flex justify-end">
              <Button
                type="button"
                onClick={closeModal}
                className="w-full rounded-3xl px-6 sm:w-auto"
              >
                {t('settings.sources.graphrag.enable.done')}
              </Button>
            </div>
          </>
        )}

        {phase === 'error' && (
          <>
            <div className="rounded-xl bg-red-50 p-4 text-sm text-red-700 dark:bg-red-900/40 dark:text-red-300">
              {error}
            </div>
            <div className="flex justify-end">
              <Button
                type="button"
                variant="ghost"
                onClick={closeModal}
                className="w-full rounded-3xl px-6 sm:w-auto"
              >
                {t('cancel')}
              </Button>
            </div>
          </>
        )}
      </div>
    </Modal>
  );
}
