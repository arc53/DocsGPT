import { useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';

import { selectToken } from '../../preferences/preferenceSlice';
import type { AppDispatch, RootState } from '../../store';
import type { ScheduleRun } from '../types/schedule';
import { loadRunsForSchedule, selectRunsForSchedule } from './schedulesSlice';

export type RunLogProps = {
  scheduleId: string;
  onSelect?: (run: ScheduleRun) => void;
};

const STATUS_STYLES: Record<string, string> = {
  success: 'text-green-600',
  failed: 'text-destructive',
  timeout: 'text-amber-600',
  skipped: 'text-muted-foreground',
  running: 'text-blue-600',
  pending: 'text-muted-foreground',
};

const formatTimestamp = (value?: string | null): string => {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString();
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
            <td className={`py-2 ${STATUS_STYLES[run.status] ?? ''}`}>
              {run.status}
              {run.error_type ? ` (${run.error_type})` : ''}
            </td>
            <td className="py-2">{run.prompt_tokens + run.generated_tokens}</td>
            <td className="py-2">{run.trigger_source}</td>
            <td className="py-2">
              {onSelect && (
                <button
                  type="button"
                  onClick={() => onSelect(run)}
                  className="text-primary text-xs underline"
                >
                  Details
                </button>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
