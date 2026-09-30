import { ChevronRight } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import { EmptyState } from '../../components/ui/empty-state';
import { LoadMoreStatus } from '../../components/ui/load-more-status';
import { LoadingState } from '../../components/ui/loading-state';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../../components/ui/table';
import { useScrollSentinel } from '../../hooks/useLoadMore';
import { selectToken } from '../../preferences/preferenceSlice';
import {
  formatDurationMs,
  formatTokens,
} from '../../settings/traces/traceUtils';
import type { AppDispatch, RootState } from '../../store';
import { formatTimestamp } from '../../utils/dateTimeUtils';
import type { ScheduleRun } from '../types/schedule';
import ScheduleStatusBadge from './StatusBadge';
import {
  loadRunsForSchedule,
  RUNS_PAGE_SIZE,
  selectRunsEnd,
  selectRunsForSchedule,
} from './schedulesSlice';

export type RunLogProps = {
  scheduleId: string;
  onSelect?: (run: ScheduleRun) => void;
};

/** How long a run took, or a dash while it hasn't started or finished. */
const runDuration = (run: ScheduleRun): string => {
  if (!run.started_at || !run.finished_at) return '—';
  return formatDurationMs(
    Date.parse(run.finished_at) - Date.parse(run.started_at),
  );
};

/**
 * A schedule's run log (SSE updates merge via schedulesSlice). Each row opens
 * the run's details when `onSelect` is given. Older runs load as the end of
 * the log scrolls into view, inside a capped inner scroller so the schedule
 * card keeps its size.
 */
export default function RunLog({ scheduleId, onSelect }: RunLogProps) {
  const { t } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();
  const token = useSelector(selectToken);
  const runs = useSelector((state: RootState) =>
    selectRunsForSchedule(state, scheduleId),
  );
  const end = useSelector((state: RootState) =>
    selectRunsEnd(state, scheduleId),
  );
  const [status, setStatus] = useState<'loading' | 'idle' | 'error'>('loading');

  const load = useCallback(
    (offset: number) => {
      setStatus('loading');
      dispatch(loadRunsForSchedule({ id: scheduleId, token, offset }))
        .unwrap()
        .then(() => setStatus('idle'))
        .catch(() => setStatus('error'));
    },
    [dispatch, scheduleId, token],
  );

  useEffect(() => {
    if (scheduleId) load(0);
  }, [load, scheduleId]);

  const sentinelRef = useScrollSentinel(
    () => load(runs.length),
    status === 'idle' && !end && runs.length > 0,
    runs.length,
  );

  if (runs.length === 0 && status === 'loading') {
    return <LoadingState fill="block" size="sm" />;
  }

  if (runs.length === 0 && status === 'error') {
    return (
      <EmptyState
        size="xs"
        illustration="none"
        tone="destructive"
        title={t('agents.schedules.runLog.loadFailed')}
        onRetry={() => load(0)}
      />
    );
  }

  if (runs.length === 0) {
    return (
      <EmptyState
        size="xs"
        illustration="none"
        title={t('agents.schedules.runLog.empty')}
      />
    );
  }

  return (
    <>
      <div className="scrollbar-overlay max-h-[45svh] overflow-y-auto">
        <Table minWidth="min-w-0">
          <TableHead>
            <TableRow>
              <TableHeader>{t('agents.schedules.runLog.when')}</TableHeader>
              <TableHeader>
                {t('agents.schedules.runDetails.status')}
              </TableHeader>
              <TableHeader>{t('agents.schedules.runLog.duration')}</TableHeader>
              <TableHeader>
                {t('agents.schedules.runDetails.tokens')}
              </TableHeader>
              <TableHeader>
                {t('agents.schedules.runDetails.trigger')}
              </TableHeader>
              {onSelect && (
                <TableHeader width="40px" align="center">
                  <span className="sr-only">
                    {t('agents.schedules.runLog.details')}
                  </span>
                </TableHeader>
              )}
            </TableRow>
          </TableHead>
          <TableBody>
            {runs.map((run) => (
              <TableRow
                key={run.id}
                onClick={onSelect ? () => onSelect(run) : undefined}
              >
                <TableCell>{formatTimestamp(run.scheduled_for)}</TableCell>
                <TableCell>
                  <div className="flex items-center gap-1.5">
                    <ScheduleStatusBadge status={run.status} />
                    {run.error_type && (
                      <span className="text-muted-foreground text-xs">
                        ({run.error_type})
                      </span>
                    )}
                  </div>
                </TableCell>
                <TableCell className="tabular-nums">
                  {runDuration(run)}
                </TableCell>
                <TableCell className="tabular-nums">
                  {formatTokens(run.prompt_tokens + run.generated_tokens)}
                </TableCell>
                <TableCell>
                  {t(`agents.schedules.trigger.${run.trigger_source}`, {
                    defaultValue: run.trigger_source,
                  })}
                </TableCell>
                {onSelect && (
                  <TableCell align="center">
                    <ChevronRight
                      aria-hidden
                      className="text-muted-foreground size-4"
                    />
                  </TableCell>
                )}
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <div ref={sentinelRef} aria-hidden="true" className="h-px" />
      </div>
      {/* Only a log long enough to scroll gets the strip; it also keeps the
        scrollbar clear of the card's rounded bottom corner. */}
      {runs.length >= RUNS_PAGE_SIZE ? (
        <LoadMoreStatus
          loading={status === 'loading'}
          error={status === 'error'}
          done={end}
          onRetry={() => load(runs.length)}
          divider
        />
      ) : null}
    </>
  );
}
