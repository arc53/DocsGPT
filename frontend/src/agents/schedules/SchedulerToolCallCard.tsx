import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';

import { Button } from '../../components/ui/button';
import { selectToken } from '../../preferences/preferenceSlice';
import type { AppDispatch } from '../../store';
import { formatDateTime } from '../../utils/dateTimeUtils';
import { deleteSchedule, loadSchedulesForAgent } from './schedulesSlice';

export type SchedulerToolCallCardProps = {
  /** Outcome JSON the scheduler tool returned (action result). */
  result?: unknown;
  /** Action name dispatched by the LLM. */
  actionName: string;
  /** Status of this tool call (pending → completed). */
  status?: string;
  /** Agent id, for live-refresh of the cancel action. */
  agentId?: string;
};

const formatTimestamp = (value?: string | null): string => {
  return value ? formatDateTime(value) : '—';
};

const parseResult = (result: unknown): Record<string, unknown> | null => {
  if (!result) return null;
  if (typeof result === 'object') return result as Record<string, unknown>;
  if (typeof result === 'string') {
    try {
      return JSON.parse(result) as Record<string, unknown>;
    } catch {
      return null;
    }
  }
  return null;
};

/** Tool returns a plain "Error: …" string on failure (cancel-not-found etc). */
export const extractToolError = (result: unknown): string | null => {
  if (typeof result === 'string') {
    const trimmed = result.trim();
    if (trimmed.startsWith('Error:')) {
      return trimmed.slice('Error:'.length).trim();
    }
  }
  return null;
};

/** In-chat card for scheduler.schedule_task with a one-click cancel. */
export default function SchedulerToolCallCard({
  result,
  actionName,
  status,
  agentId,
}: SchedulerToolCallCardProps) {
  const dispatch = useDispatch<AppDispatch>();
  const token = useSelector(selectToken);
  const [cancelled, setCancelled] = useState<boolean>(false);
  const parsed = parseResult(result);
  const taskId =
    parsed && typeof parsed.task_id === 'string' ? parsed.task_id : null;
  const runAt =
    parsed && typeof parsed.resolved_run_at === 'string'
      ? parsed.resolved_run_at
      : null;
  const instruction =
    parsed && typeof parsed.instruction === 'string'
      ? parsed.instruction
      : null;
  const error =
    parsed && typeof parsed.error === 'string' ? parsed.error : null;

  // Agent-bound chats prime the Schedules tab cache; agentless chats have
  // no per-agent listing, so skip the fetch.
  useEffect(() => {
    if (agentId) dispatch(loadSchedulesForAgent({ agentId, token }));
  }, [dispatch, agentId, token]);

  const cancel = async () => {
    if (!taskId) return;
    setCancelled(true);
    try {
      await dispatch(deleteSchedule({ id: taskId, token })).unwrap();
    } catch (err) {
      setCancelled(false);
      console.error(err);
    }
  };

  if (actionName.startsWith('cancel_scheduled_task')) {
    // The tool returns a plain "Error: …" string when the cancel fails
    // (not found, already terminal, invalid id). Don't claim success.
    const cancelError = extractToolError(result);
    if (cancelError) {
      return (
        <div className="border-border bg-card rounded-2xl border p-4 text-sm">
          <p className="text-destructive font-semibold">
            Cancel failed: {cancelError}
          </p>
        </div>
      );
    }
    return (
      <div className="border-border bg-card rounded-2xl border p-4 text-sm">
        <p className="font-semibold">Scheduled task cancelled.</p>
      </div>
    );
  }

  if (actionName.startsWith('list_scheduled_tasks')) {
    const tasks = Array.isArray(parsed?.tasks)
      ? (parsed?.tasks as Array<Record<string, unknown>>)
      : [];
    return (
      <div className="border-border bg-card rounded-2xl border p-4 text-sm">
        <p className="font-semibold">
          {tasks.length} pending scheduled task{tasks.length === 1 ? '' : 's'}
        </p>
        <ul className="mt-2 flex flex-col gap-1">
          {tasks.map((task) => (
            <li key={String(task.task_id)}>
              {formatTimestamp(task.resolved_run_at as string)} —{' '}
              {String(task.instruction || task.name || task.task_id)}
            </li>
          ))}
        </ul>
      </div>
    );
  }

  // ``error`` may be JSON-shaped (``{"error": "…"}``) or a plain
  // ``"Error: …"`` string returned by the tool on validation failures.
  const schedulingError = error || extractToolError(result);
  if (schedulingError) {
    return (
      <div className="border-border bg-card rounded-2xl border p-4 text-sm">
        <p className="text-destructive font-semibold">
          Scheduling failed: {schedulingError}
        </p>
      </div>
    );
  }

  return (
    <div className="border-border bg-card rounded-2xl border p-4 text-sm">
      <div className="flex items-center justify-between">
        <p className="font-semibold">
          {status === 'pending' ? '⏰ Scheduling…' : '⏰ Scheduled task'}
        </p>
        {runAt && (
          <span className="text-muted-foreground text-xs">
            {formatTimestamp(runAt)}
          </span>
        )}
      </div>
      {instruction && (
        <p className="text-muted-foreground mt-2 text-sm italic">
          “{instruction}”
        </p>
      )}
      {taskId && !cancelled && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={cancel}
          className="text-destructive mt-2 text-xs"
        >
          Cancel
        </Button>
      )}
      {cancelled && (
        <p className="text-muted-foreground mt-2 text-xs">Cancelled.</p>
      )}
    </div>
  );
}
