import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import type { BackgroundJobStatus } from '../api/services/backgroundService';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Progress } from '../components/ui/progress';
import { StepIcon } from '../conversation/StepGroup';
import ToolCallCard from '../conversation/ToolCallCard';
import type { ToolCallsType } from '../conversation/types';
import { showActionToast } from '../notifications/actionToastSlice';
import { selectPushChannelHealthy } from '../notifications/notificationsSlice';
import type { AppDispatch, RootState } from '../store';
import { getToolChipLabel } from '../utils/streamingStatusUtils';

import {
  cancelBackgroundJob,
  fetchBackgroundJob,
  fetchConversationJobs,
  FINAL_JOB_STATUSES,
  selectBackgroundJob,
  selectJobUnavailable,
  type BackgroundJob,
} from './backgroundSlice';

/** Polling cadence while the event stream is down and the job still runs. */
export const JOB_POLL_MS = 10_000;

const STATUS_BADGE: Record<
  BackgroundJobStatus,
  'info' | 'success' | 'destructive' | 'neutral' | 'warning'
> = {
  working: 'info',
  completed: 'success',
  failed: 'destructive',
  cancelled: 'neutral',
  lost: 'warning',
};

/**
 * The job's status as best known: the store (events and fetches) first, then
 * the outcome patched onto the saved tool call, then the call's own status.
 */
export function effectiveJobStatus(
  toolCall: ToolCallsType,
  job: BackgroundJob | undefined,
): BackgroundJobStatus {
  if (job) return job.status;
  const patched = toolCall.job_status;
  if (patched && (patched === 'working' || FINAL_JOB_STATUSES.has(patched))) {
    return patched as BackgroundJobStatus;
  }
  if (toolCall.status === 'completed') return 'completed';
  if (toolCall.status === 'error') return 'failed';
  return 'working';
}

/** `1h 4m`, `3m 12s`, `45s`. */
export function formatElapsed(
  seconds: number,
  t: (key: string, options?: Record<string, unknown>) => string,
): string {
  const total = Math.max(0, Math.floor(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return t('backgroundJobs.card.durationHours', { h, m });
  if (m > 0) return t('backgroundJobs.card.durationMinutes', { m, s });
  return t('backgroundJobs.card.durationSeconds', { s });
}

/** Seconds the job has run: from its start to its finish, or to now. */
export function elapsedSeconds(
  job: BackgroundJob | undefined,
  now: number,
): number | null {
  if (!job) return null;
  const started = job.started_at ? Date.parse(job.started_at) : NaN;
  if (Number.isFinite(started)) {
    const finished = job.finished_at ? Date.parse(job.finished_at) : NaN;
    const end = Number.isFinite(finished) ? finished : now;
    return Math.max(0, (end - started) / 1000);
  }
  if (typeof job.elapsed_s === 'number') {
    const running = job.status === 'working';
    return job.elapsed_s + (running ? (now - job.receivedAt) / 1000 : 0);
  }
  return null;
}

function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [active]);
  return now;
}

/**
 * A tool call that became a background job, in the chat: running with its
 * elapsed time, progress and latest output, and a Cancel button; then
 * finished, failed, cancelled or interrupted. Live from `job.updated`; the
 * job is fetched once on mount (a reload, a missed event) and polled only
 * while the event stream is down.
 */
export default function BackgroundJobCard({
  toolCall,
}: {
  toolCall: ToolCallsType;
}) {
  const { t } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();
  const jobId = toolCall.job_id as string;
  const job = useSelector(selectBackgroundJob(jobId));
  const unavailable = useSelector(selectJobUnavailable(jobId));
  const openConversationId = useSelector(
    (state: RootState) => state.conversation?.conversationId ?? null,
  );
  const streamHealthy = useSelector(selectPushChannelHealthy);
  const [cancelling, setCancelling] = useState(false);
  const status = effectiveJobStatus(toolCall, job);
  const running = status === 'working';
  const now = useNow(running);
  const knownFinal = !job && FINAL_JOB_STATUSES.has(status);

  // The card's own snapshot (the start time, a progress the stream missed),
  // once per job; a call saved with its outcome needs none.
  const fetchedFor = useRef<string | null>(null);
  useEffect(() => {
    if (knownFinal || fetchedFor.current === jobId) return;
    fetchedFor.current = jobId;
    void dispatch(fetchBackgroundJob(jobId));
  }, [knownFinal, jobId, dispatch]);

  // The job just ended: fetch its final timing once.
  const finalFromEvent = Boolean(job && !running && !job.finished_at);
  useEffect(() => {
    if (finalFromEvent) void dispatch(fetchBackgroundJob(jobId));
  }, [finalFromEvent, jobId, dispatch]);

  // Without the event stream, poll: the conversation's job list (one request
  // however many cards are on screen), or this job when its chat is unknown.
  const conversationId = job?.conversation_id ?? openConversationId;
  useEffect(() => {
    if (!running || streamHealthy || unavailable) return;
    const timer = window.setInterval(
      () =>
        void dispatch(
          conversationId
            ? fetchConversationJobs(conversationId)
            : fetchBackgroundJob(jobId),
        ),
      JOB_POLL_MS,
    );
    return () => window.clearInterval(timer);
  }, [running, streamHealthy, unavailable, conversationId, jobId, dispatch]);

  const cancel = async () => {
    setCancelling(true);
    try {
      await dispatch(cancelBackgroundJob(jobId)).unwrap();
    } catch {
      setCancelling(false);
      dispatch(
        showActionToast({
          variant: 'destructive',
          message: t('backgroundJobs.card.cancelFailed'),
        }),
      );
    }
  };

  const label = getToolChipLabel(
    { ...toolCall, status: running ? 'pending' : 'completed' },
    t,
  );
  const elapsed = elapsedSeconds(job, now);
  const percent = job?.progress?.percent;
  const lastLine = job?.progress?.last?.trim();
  const cancelRequested = Boolean(job?.cancel_requested) || cancelling;

  return (
    <div className="my-2 mr-5 ml-6" data-testid="background-job-card">
      <ToolCallCard
        icon={<StepIcon call={toolCall} pulse={running} />}
        title={label}
        meta={
          elapsed !== null ? (
            <span className="text-muted-foreground text-xs tabular-nums">
              {formatElapsed(elapsed, t)}
            </span>
          ) : null
        }
        state={
          <Badge variant={STATUS_BADGE[status]}>
            {t(`backgroundJobs.card.status.${status}`)}
          </Badge>
        }
        actions={
          running && !unavailable ? (
            <Button
              type="button"
              variant="outline"
              size="xs"
              shape="pill"
              onClick={() => void cancel()}
              disabled={cancelRequested}
            >
              {cancelRequested
                ? t('backgroundJobs.card.cancelling')
                : t('backgroundJobs.card.cancel')}
            </Button>
          ) : null
        }
      >
        {running && typeof percent === 'number' && (
          <Progress
            size="sm"
            variant="info"
            value={percent}
            aria-label={t('backgroundJobs.card.progress', {
              percent: Math.round(percent),
            })}
          />
        )}
        {running && lastLine && (
          <p
            className="text-muted-foreground mt-2 truncate font-mono text-xs"
            title={lastLine}
          >
            {lastLine}
          </p>
        )}
        {running && !lastLine && typeof percent !== 'number' && (
          <p className="text-muted-foreground text-xs">
            {job?.auto_resume === false
              ? t('backgroundJobs.card.pollOnly')
              : t('backgroundJobs.card.willResume')}
          </p>
        )}
        {status === 'failed' && job?.error && (
          <p
            className="text-destructive mt-1 line-clamp-3 font-mono text-xs wrap-break-word"
            title={job.error}
          >
            {job.error}
          </p>
        )}
        {status === 'lost' && (
          <p className="text-muted-foreground text-xs">
            {t('backgroundJobs.card.lostHint')}
          </p>
        )}
      </ToolCallCard>
    </div>
  );
}
