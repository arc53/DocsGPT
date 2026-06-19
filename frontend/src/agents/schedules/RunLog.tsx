import { useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';

import { Button } from '../../components/ui/button';
import { selectToken } from '../../preferences/preferenceSlice';
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

/** Paginated run log for a schedule (SSE updates merge via schedulesSlice). */
export default function RunLog({ scheduleId, onSelect }: RunLogProps) {
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
        No runs recorded for this schedule yet.
      </p>
    );
  }

  return (
    <table className="w-full text-left text-sm">
      <thead className="text-muted-foreground text-xs uppercase">
        <tr>
          <th className="py-2">When</th>
          <th className="py-2">Status</th>
          <th className="py-2">Tokens</th>
          <th className="py-2">Trigger</th>
          <th className="py-2"></th>
        </tr>
      </thead>
      <tbody>
        {runs.map((run) => (
          <tr key={run.id} className="border-border border-t">
            <td className="py-2">{formatTimestamp(run.scheduled_for)}</td>
            <td className="py-2">
              <div className="flex items-center gap-1.5">
                <ScheduleStatusBadge status={run.status} />
                {run.error_type && (
                  <span className="text-muted-foreground text-xs">
                    ({run.error_type})
                  </span>
                )}
              </div>
            </td>
            <td className="py-2">{run.prompt_tokens + run.generated_tokens}</td>
            <td className="py-2">{run.trigger_source}</td>
            <td className="py-2">
              {onSelect && (
                <Button
                  type="button"
                  variant="link"
                  size="sm"
                  onClick={() => onSelect(run)}
                  className="h-auto p-0 text-xs underline"
                >
                  Details
                </Button>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
