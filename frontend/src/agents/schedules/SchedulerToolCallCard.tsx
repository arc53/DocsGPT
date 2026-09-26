import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import { CalendarClock, CalendarX2, CircleAlert } from 'lucide-react';

import { Button } from '../../components/ui/button';
import { Card } from '../../components/ui/card';
import { Spinner } from '../../components/ui/spinner';
import { selectToken } from '../../preferences/preferenceSlice';
import type { AppDispatch } from '../../store';
import { formatDateTime } from '../../utils/dateTimeUtils';
import { deleteSchedule, loadSchedulesForAgent } from './schedulesSlice';
import ScheduleStatusBadge from './StatusBadge';

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
  const { t } = useTranslation();
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
        <Card>
          <div className="flex items-start gap-3">
            <CircleAlert className="text-destructive mt-0.5 size-4 shrink-0" />
            <div className="flex min-w-0 flex-1 flex-col">
              <p className="text-destructive font-semibold">
                {t('agents.schedules.toolCard.cancelFailed')}
              </p>
              <p className="text-muted-foreground">{cancelError}</p>
            </div>
          </div>
        </Card>
      );
    }
    return (
      <Card>
        <div className="flex items-start gap-3">
          <CalendarX2 className="text-muted-foreground mt-0.5 size-4 shrink-0" />
          <div className="flex min-w-0 flex-1 flex-col">
            <p className="font-semibold">
              {t('agents.schedules.toolCard.taskCancelled')}
            </p>
          </div>
        </div>
      </Card>
    );
  }

  if (actionName.startsWith('list_scheduled_tasks')) {
    const tasks = Array.isArray(parsed?.tasks)
      ? (parsed?.tasks as Array<Record<string, unknown>>)
      : [];
    return (
      <Card>
        <div className="flex items-start gap-3">
          <CalendarClock className="text-muted-foreground mt-0.5 size-4 shrink-0" />
          <div className="flex min-w-0 flex-1 flex-col">
            <p className="font-semibold">
              {t('agents.schedules.toolCard.pendingCount', {
                count: tasks.length,
              })}
            </p>
          </div>
        </div>
        {tasks.length > 0 && (
          <ul className="flex flex-col gap-1 pl-7">
            {tasks.map((task) => (
              <li key={String(task.task_id)}>
                {formatTimestamp(task.resolved_run_at as string)} —{' '}
                {String(task.instruction || task.name || task.task_id)}
              </li>
            ))}
          </ul>
        )}
      </Card>
    );
  }

  // ``error`` may be JSON-shaped (``{"error": "…"}``) or a plain
  // ``"Error: …"`` string returned by the tool on validation failures.
  const schedulingError = error || extractToolError(result);
  if (schedulingError) {
    return (
      <Card>
        <div className="flex items-start gap-3">
          <CircleAlert className="text-destructive mt-0.5 size-4 shrink-0" />
          <div className="flex min-w-0 flex-1 flex-col">
            <p className="text-destructive font-semibold">
              {t('agents.schedules.toolCard.schedulingFailed')}
            </p>
            <p className="text-muted-foreground">{schedulingError}</p>
          </div>
        </div>
      </Card>
    );
  }

  const iconClass = 'text-muted-foreground mt-0.5 size-4 shrink-0';
  return (
    <Card>
      <div className="flex items-start gap-3">
        {status === 'pending' ? (
          <Spinner size="xs" className="text-muted-foreground mt-0.5" />
        ) : cancelled ? (
          <CalendarX2 className={iconClass} />
        ) : (
          <CalendarClock className={iconClass} />
        )}
        <div className="flex min-w-0 flex-1 flex-col">
          <p className="font-semibold">
            {status === 'pending'
              ? t('agents.schedules.toolCard.scheduling')
              : t('agents.schedules.toolCard.scheduled')}
          </p>
          {runAt && (
            <span className="text-muted-foreground text-xs">
              {formatTimestamp(runAt)}
            </span>
          )}
        </div>
        {taskId && !cancelled && (
          <Button
            type="button"
            variant="destructive-outline"
            size="xs"
            shape="pill"
            onClick={cancel}
          >
            {t('agents.schedules.cancel')}
          </Button>
        )}
        {cancelled && <ScheduleStatusBadge status="cancelled" />}
      </div>
      {instruction && (
        <p className="text-muted-foreground pl-7">{instruction}</p>
      )}
    </Card>
  );
}
