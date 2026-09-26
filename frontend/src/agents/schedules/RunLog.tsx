import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import { Button } from '../../components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../../components/ui/table';
import { selectToken } from '../../preferences/preferenceSlice';
import type { AppDispatch, RootState } from '../../store';
import { formatDateTime } from '../../utils/dateTimeUtils';
import type { ScheduleRun } from '../types/schedule';
import ScheduleStatusBadge from './StatusBadge';
import { loadRunsForSchedule, selectRunsForSchedule } from './schedulesSlice';

// The column heads are a label row, so they take the eyebrow recipe.
const HEADER_CELL =
  'text-muted-foreground text-xs font-semibold tracking-wider uppercase';

export type RunLogProps = {
  scheduleId: string;
  onSelect?: (run: ScheduleRun) => void;
};

const formatTimestamp = (value?: string | null): string => {
  return value ? formatDateTime(value) : '—';
};

/** Paginated run log for a schedule (SSE updates merge via schedulesSlice). */
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
      <p className="text-muted-foreground py-3 text-sm">
        {t('agents.schedules.runLog.empty')}
      </p>
    );
  }

  return (
    <Table minWidth="min-w-0">
      <TableHead>
        <TableRow>
          <TableHeader className={HEADER_CELL}>
            {t('agents.schedules.runLog.when')}
          </TableHeader>
          <TableHeader className={HEADER_CELL}>
            {t('agents.schedules.runDetails.status')}
          </TableHeader>
          <TableHeader className={HEADER_CELL}>
            {t('agents.schedules.runDetails.tokens')}
          </TableHeader>
          <TableHeader className={HEADER_CELL}>
            {t('agents.schedules.runDetails.trigger')}
          </TableHeader>
          <TableHeader className={HEADER_CELL}></TableHeader>
        </TableRow>
      </TableHead>
      <TableBody>
        {runs.map((run) => (
          <TableRow key={run.id}>
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
            <TableCell>{run.prompt_tokens + run.generated_tokens}</TableCell>
            <TableCell>
              {t(`agents.schedules.trigger.${run.trigger_source}`, {
                defaultValue: run.trigger_source,
              })}
            </TableCell>
            <TableCell>
              {onSelect && (
                <Button
                  type="button"
                  variant="link"
                  size="xs"
                  onClick={() => onSelect(run)}
                  className="-mx-2 -my-1"
                >
                  {t('agents.schedules.runLog.details')}
                </Button>
              )}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
