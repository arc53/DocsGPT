import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import type {
  BackgroundJobNotice,
  BackgroundJobStatus,
} from '../api/services/backgroundService';
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

/** The card's line for a notice the server attached to a job. */
export function noticeText(
  notice: BackgroundJobNotice,
  t: (key: string, options?: Record<string, unknown>) => string,
): string | null {
  switch (notice.code) {
    case 'cancel_unsupported':
      return t('backgroundJobs.card.noticeCancelUnsupported');
    case 'device_interrupted':
      return notice.pid
        ? t('backgroundJobs.card.noticeDeviceInterrupted', { pid: notice.pid })
        : t('backgroundJobs.card.noticeDeviceInterruptedNoPid');
    case 'device_shutdown':
      return t('backgroundJobs.card.noticeDeviceShutdown');
    case 'output_truncated':
      return t('backgroundJobs.card.noticeOutputTruncated');
    default:
      return null;
  }
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

/**
 * Seconds the job has run: from its start to its finish, or to now. A
 * finished call reloaded from the conversation has no job in the store; its
 * entry carries the job's start and finish instead.
 */
export function elapsedSeconds(
  job: BackgroundJob | undefined,
  now: number,
  toolCall?: ToolCallsType,
): number | null {
  if (!job) {
    const started = Date.parse(toolCall?.job_started_at ?? '');
    const finished = Date.parse(toolCall?.job_finished_at ?? '');
    return Number.isFinite(started) && Number.isFinite(finished)
      ? Math.max(0, (finished - started) / 1000)
      : null;
  }
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
  // A call saved with its outcome needs no fetch; one saved before the
  // outcome carried its notices (a device's pid) still fetches them once.
  const knownFinal =
    !job &&
    FINAL_JOB_STATUSES.has(status) &&
    Array.isArray(toolCall.job_notices);

  // The card's own snapshot (the start time, a progress the stream missed),
  // once per job.
  const fetchedFor = useRef<string | null>(null);
  useEffect(() => {
    if (knownFinal || fetchedFor.current === jobId) return;
    fetchedFor.current = jobId;
    void dispatch(fetchBackgroundJob(jobId));
  }, [knownFinal, jobId, dispatch]);

  // The job just ended (an event, or a list poll): fetch its final timing
  // and error once; only the single-job route carries the error.
  const finalDetailMissing = Boolean(
    job &&
    !running &&
    (!job.finished_at || (job.status === 'failed' && !job.error)),
  );
  const finalFetchedFor = useRef<string | null>(null);
  useEffect(() => {
    if (!finalDetailMissing || finalFetchedFor.current === jobId) return;
    finalFetchedFor.current = jobId;
    void dispatch(fetchBackgroundJob(jobId));
  }, [finalDetailMissing, jobId, dispatch]);

  // Without the event stream, poll: the conversation's job list (one request
  // however many cards are on screen), or this job when its chat is unknown.
  const conversationId = job?.conversation_id ?? openConversationId;
  useEffect(() => {
    if (!running || streamHealthy || unavailable) return;
    const poll = () => {
      if (conversationId) void dispatch(fetchConversationJobs(conversationId));
      else void dispatch(fetchBackgroundJob(jobId));
    };
    const timer = window.setInterval(poll, JOB_POLL_MS);
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
  const elapsed = elapsedSeconds(job, now, toolCall);
  const percent = job?.progress?.percent;
  const lastLine = job?.progress?.last?.trim();
  const waitingForDevice = running && job?.progress?.waiting_for === 'device';
  const notices = (
    job?.notices ??
    (toolCall.job_notices as BackgroundJobNotice[] | undefined) ??
    []
  )
    .map((notice) => ({ code: notice.code, text: noticeText(notice, t) }))
    .filter(
      (notice): notice is { code: BackgroundJobNotice['code']; text: string } =>
        Boolean(notice.text),
    );
  // A device job interrupted by its client says why itself; the generic hint would repeat it.
  const deviceExplained = notices.some(
    (notice) => notice.code === 'device_interrupted',
  );
  const cancelRequested = Boolean(job?.cancel_requested) || cancelling;

  return (
    // Stretched to the column, like the approval card: in the bubble's
    // wrapping flex column a shrink-to-fit card sizes to its title and
    // spills past a phone's width instead of truncating it.
    <div className="w-full min-w-0" data-testid="background-job-card">
      <div className="my-2 mr-5 ml-6 min-w-0">
        <ToolCallCard
          icon={<StepIcon call={toolCall} pulse={running} />}
          title={label}
          meta={
            elapsed !== null ? (
              <span className="text-muted-foreground text-xs whitespace-nowrap tabular-nums">
                {formatElapsed(elapsed, t)}
              </span>
            ) : null
          }
          state={
            waitingForDevice ? (
              <Badge variant="warning" data-testid="job-badge-waiting-device">
                {t('backgroundJobs.card.waitingBadge')}
              </Badge>
            ) : (
              <Badge variant={STATUS_BADGE[status]}>
                {t(`backgroundJobs.card.status.${status}`)}
              </Badge>
            )
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
            <div className="flex items-center gap-2">
              <Progress
                size="sm"
                variant="info"
                value={percent}
                className="flex-1"
                aria-label={t('backgroundJobs.card.progress', {
                  percent: Math.round(percent),
                })}
              />
              <span
                className="text-muted-foreground shrink-0 text-xs tabular-nums"
                data-testid="job-percent"
              >
                {t('backgroundJobs.card.progress', {
                  percent: Math.round(percent),
                })}
              </span>
            </div>
          )}
          {running && lastLine && (
            <p
              className="text-muted-foreground mt-2 truncate font-mono text-xs"
              title={lastLine}
            >
              {lastLine}
            </p>
          )}
          {waitingForDevice && (
            <p
              className="text-warning mt-2 text-sm"
              role="status"
              data-testid="job-waiting-device"
            >
              {t('backgroundJobs.card.waitingForDevice')}
            </p>
          )}
          {running &&
            !waitingForDevice &&
            !lastLine &&
            typeof percent !== 'number' && (
              <p className="text-muted-foreground text-xs">
                {job?.auto_resume === false
                  ? t('backgroundJobs.card.pollOnly')
                  : t('backgroundJobs.card.willResume')}
              </p>
            )}
          {notices.map((notice) => (
            <p
              key={notice.code}
              className="text-muted-foreground mt-1 text-xs"
              data-testid={`job-notice-${notice.code}`}
            >
              {notice.text}
            </p>
          ))}
          {status === 'failed' && job?.error && (
            <p
              className="text-destructive mt-1 line-clamp-3 font-mono text-xs wrap-break-word"
              title={job.error}
            >
              {job.error}
            </p>
          )}
          {status === 'lost' && !deviceExplained && (
            <p className="text-muted-foreground text-xs">
              {t('backgroundJobs.card.lostHint')}
            </p>
          )}
        </ToolCallCard>
      </div>
    </div>
  );
}
