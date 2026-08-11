import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import userService from '../api/services/userService';
import Spinner from '../components/Spinner';
import { Button } from '../components/ui/button';
import { Modal } from '../components/ui/modal';
import { ActiveState, Doc } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import type { AppDispatch, RootState } from '../store';

import { clearGraphBuild, selectGraphBuilds } from './graphBuildSlice';
import {
  GraphRAGSummary,
  estimateGraphTokens,
  pollTaskOnce,
  startGraphRAG,
} from './graphragEnableUtils';

const POLL_INTERVAL_MS = 2000;
// Fallback poll backstop. SSE (graphBuildSlice) is the primary driver; the poll
// only covers SSE-off deployments. Bounded so a dead/stuck backend can't spin
// forever (consecutive transient errors), with a hard attempt cap on top.
const MAX_POLL_ATTEMPTS = 150;
const MAX_CONSECUTIVE_ERRORS = 5;

const ZERO_SUMMARY: GraphRAGSummary = {
  nodes: 0,
  edges: 0,
  chunksProcessed: 0,
  skippedOverCap: 0,
  failedChunks: 0,
};

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
  const dispatch = useDispatch<AppDispatch>();

  const sourceId = document?.id;
  const build = useSelector((state: RootState) =>
    sourceId ? selectGraphBuilds(state)[sourceId] : undefined,
  );

  const estimate = estimateGraphTokens(
    Number(document?.tokens) || 0,
    document?.config?.chunking?.max_tokens,
  );

  const [phase, setPhase] = useState<Phase>('confirm');
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<GraphRAGSummary | null>(null);
  const pollTimer = useRef<number | null>(null);
  const isActiveRef = useRef(true);
  // Guards against the SSE path and the poll fallback both resolving.
  const resolvedRef = useRef(false);

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
      resolvedRef.current = false;
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

  const succeed = (result: GraphRAGSummary) => {
    if (resolvedRef.current) return;
    resolvedRef.current = true;
    clearPoll();
    setSummary(result);
    setPhase('summary');
  };

  const fail = (message?: string) => {
    if (resolvedRef.current) return;
    resolvedRef.current = true;
    clearPoll();
    setError(message ?? t('settings.sources.graphrag.enable.errors.generic'));
    setPhase('error');
  };

  // Primary resolution path: the build's terminal SSE event lands in the slice.
  useEffect(() => {
    if (phase !== 'building' || !build) return;
    if (build.status === 'completed') succeed(build.summary ?? ZERO_SUMMARY);
    else if (build.status === 'failed') fail(build.error);
  }, [build, phase]);

  // Fallback poll: bounded so it can't loop forever on a dead/stuck backend.
  const poll = (taskId: string, attempt: number, consecutiveErrors: number) => {
    if (attempt > MAX_POLL_ATTEMPTS) return; // SSE may still resolve
    pollTaskOnce(userService, taskId, token)
      .then((result) => {
        if (!isActiveRef.current || resolvedRef.current) return;
        if (result.status === 'done') {
          succeed(result.summary);
          return;
        }
        if (result.status === 'failed') {
          fail(result.message);
          return;
        }
        if (result.status === 'error') {
          if (consecutiveErrors + 1 >= MAX_CONSECUTIVE_ERRORS) {
            fail();
            return;
          }
          pollTimer.current = window.setTimeout(
            () => poll(taskId, attempt + 1, consecutiveErrors + 1),
            POLL_INTERVAL_MS,
          );
          return;
        }
        // pending — reset the error streak and keep polling.
        pollTimer.current = window.setTimeout(
          () => poll(taskId, attempt + 1, 0),
          POLL_INTERVAL_MS,
        );
      })
      .catch(() => {
        if (!isActiveRef.current || resolvedRef.current) return;
        fail();
      });
  };

  const handleEnable = async () => {
    if (!sourceId) return;
    resolvedRef.current = false;
    // Reset any prior build record so this build's progress events flow.
    dispatch(clearGraphBuild(sourceId));
    setPhase('building');
    setError(null);
    setSummary(null);
    const start = await startGraphRAG(userService, sourceId, token);
    if (!isActiveRef.current) return;
    if (start.status === 'enabled') {
      onEnabled();
      succeed(ZERO_SUMMARY);
      return;
    }
    if (start.status === 'task') {
      onEnabled();
      poll(start.taskId, 0, 0);
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

  const progressPct =
    build && build.status === 'building' && build.total > 0
      ? Math.min(100, Math.round((build.current / build.total) * 100))
      : null;

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
            </ul>
            <div className="bg-muted text-muted-foreground rounded-xl p-3 text-sm">
              {t('settings.sources.graphrag.enable.estimate', {
                lo: estimate.lo.toLocaleString(),
                hi: estimate.hi.toLocaleString(),
              })}
            </div>
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
              {progressPct !== null
                ? t('settings.sources.graphrag.enable.inProgressPct', {
                    pct: progressPct,
                  })
                : t('settings.sources.graphrag.enable.inProgress')}
            </p>
            {progressPct !== null && (
              <div className="bg-muted h-1.5 w-48 overflow-hidden rounded-full">
                <div
                  className="bg-foreground/70 h-full rounded-full transition-all"
                  style={{ width: `${progressPct}%` }}
                />
              </div>
            )}
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
