import { ChevronRight } from 'lucide-react';
import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import { EmptyState } from '../../components/ui/empty-state';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../../components/ui/table';
import { selectToken } from '../../preferences/preferenceSlice';
import {
  formatDurationMs,
  formatTokens,
} from '../../settings/traces/traceUtils';
import type { AppDispatch, RootState } from '../../store';
import { formatDateTime } from '../../utils/dateTimeUtils';
import type { ScheduleRun } from '../types/schedule';
import ScheduleStatusBadge from './StatusBadge';
import { loadRunsForSchedule, selectRunsForSchedule } from './schedulesSlice';

export type RunLogProps = {
  scheduleId: string;
  onSelect?: (run: ScheduleRun) => void;
};

const formatTimestamp = (value?: string | null): string => {
  return value ? formatDateTime(value) : '—';
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
 * the run's details when `onSelect` is given.
 */
export default function RunLog({ scheduleId, onSelect }: RunLogProps) {
  const { t } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();
  const token = useSelector(selectToken);
  const runs = useSelector((state: RootState) =>
    selectRunsForSchedule(state, scheduleId),
  );

  useEffect(() => {
    if (!scheduleId) return;
    dispatch(loadRunsForSchedule({ id: scheduleId, token }));
  }, [dispatch, scheduleId, token]);

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
    <Table minWidth="min-w-0">
      <TableHead>
        <TableRow>
          <TableHeader>{t('agents.schedules.runLog.when')}</TableHeader>
          <TableHeader>{t('agents.schedules.runDetails.status')}</TableHeader>
          <TableHeader>{t('agents.schedules.runLog.duration')}</TableHeader>
          <TableHeader>{t('agents.schedules.runDetails.tokens')}</TableHeader>
          <TableHeader>{t('agents.schedules.runDetails.trigger')}</TableHeader>
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
            <TableCell className="tabular-nums">{runDuration(run)}</TableCell>
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
  );
}
