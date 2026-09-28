import {
  ChevronDown,
  Clock,
  History,
  Pause,
  Pencil,
  Play,
  Repeat,
  Trash2,
  TriangleAlert,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Badge } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { Card } from '../../components/ui/card';
import { ActionMenu, type MenuOption } from '../../components/ui/dropdown-menu';
import { IconButton } from '../../components/ui/icon-button';
import { cn } from '@/lib/utils';
import { formatDateTime, formatRelative } from '../../utils/dateTimeUtils';
import type { Schedule, ScheduleRun } from '../types/schedule';
import RunLog from './RunLog';
import ScheduleStatusBadge from './StatusBadge';
import { formatCron } from './cronBuilder';

// Timezones and dates carry slashes: React escapes on render, so i18next
// must not escape them first.
const NO_ESCAPE = { interpolation: { escapeValue: false } } as const;

const STATUS_DOT: Record<Schedule['status'], string> = {
  active: 'bg-success',
  paused: 'bg-warning',
  completed: 'bg-muted-foreground',
  cancelled: 'bg-muted-foreground',
};

export type ScheduleRowProps = {
  schedule: Schedule;
  /** Whether the run log is open under the row (recurring schedules). */
  expanded: boolean;
  onToggleRuns: (scheduleId: string) => void;
  onEdit: (schedule: Schedule) => void;
  onSetPaused: (schedule: Schedule, paused: boolean) => void;
  onRunNow: (schedule: Schedule) => void;
  onDelete: (schedule: Schedule) => void;
  onSelectRun: (run: ScheduleRun) => void;
};

/**
 * One schedule on an agent's Schedules page: a subtle panel with a status dot,
 * the name and status, the instruction, one meta line, the common action as
 * a button (Run now, or Resume while paused) and the rest in a menu. A
 * recurring schedule opens its run log flush under the row.
 *
 * Args:
 *   schedule: The schedule to show.
 *   expanded: Whether its run log is open.
 *   onToggleRuns: Opens or closes the run log.
 *   onEdit: Opens the schedule form.
 *   onSetPaused: Pauses (true) or resumes (false) a recurring schedule.
 *   onRunNow: Runs the schedule once now.
 *   onDelete: Asks to delete the schedule (or cancel a one-time task).
 *   onSelectRun: Opens a run's details.
 */
export default function ScheduleRow({
  schedule,
  expanded,
  onToggleRuns,
  onEdit,
  onSetPaused,
  onRunNow,
  onDelete,
  onSelectRun,
}: ScheduleRowProps) {
  const { t } = useTranslation();
  const recurring = schedule.trigger_type === 'recurring';
  const active = schedule.status === 'active';
  const paused = schedule.status === 'paused';
  const title = schedule.name || schedule.instruction.slice(0, 80);

  const edit: MenuOption = {
    label: t('agents.schedules.edit'),
    icon: Pencil,
    onClick: () => onEdit(schedule),
  };
  const remove: MenuOption = {
    label: t('agents.schedules.delete'),
    icon: Trash2,
    variant: 'destructive',
    onClick: () => onDelete(schedule),
  };
  const menu: MenuOption[] = recurring
    ? active
      ? [
          edit,
          {
            label: t('agents.schedules.pause'),
            icon: Pause,
            onClick: () => onSetPaused(schedule, true),
          },
          remove,
        ]
      : paused
        ? [
            edit,
            {
              label: t('agents.schedules.runNow'),
              icon: Play,
              onClick: () => onRunNow(schedule),
            },
            remove,
          ]
        : [remove]
    : active
      ? [
          edit,
          {
            label: t('agents.schedules.cancelTask'),
            icon: Trash2,
            variant: 'destructive',
            onClick: () => onDelete(schedule),
          },
        ]
      : [remove];

  const meta: { icon: typeof Clock; text: string }[] = [];
  if (recurring) {
    meta.push({
      icon: Repeat,
      text: `${formatCron(schedule.cron, t)}, ${schedule.timezone}`,
    });
    if (active && schedule.next_run_at) {
      meta.push({
        icon: Clock,
        text: t('agents.schedules.meta.nextRun', {
          ...NO_ESCAPE,
          // A past next run (the scheduler is behind) reads as a date, not
          // "… ago".
          time:
            Date.parse(schedule.next_run_at) > Date.now()
              ? formatRelative(schedule.next_run_at, { future: true })
              : formatDateTime(schedule.next_run_at),
        }),
      });
    }
  } else if (schedule.run_at) {
    meta.push({
      icon: Clock,
      text: t('agents.schedules.meta.runsAt', {
        ...NO_ESCAPE,
        time: `${formatDateTime(schedule.run_at)}, ${schedule.timezone}`,
      }),
    });
  }
  if (schedule.last_run_at) {
    meta.push({
      icon: History,
      text: t('agents.schedules.meta.lastRun', {
        ...NO_ESCAPE,
        time: formatRelative(schedule.last_run_at),
      }),
    });
  }

  return (
    <Card variant="subtle" padding="none" data-schedule-id={schedule.id}>
      <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-start">
        <div className="flex min-w-0 flex-1 items-start gap-3">
          <span
            aria-hidden
            className={cn(
              'mt-1.5 size-2 shrink-0 rounded-full',
              STATUS_DOT[schedule.status],
            )}
          />
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium wrap-break-word">{title}</span>
              <ScheduleStatusBadge status={schedule.status} />
              {schedule.consecutive_failure_count > 0 && (
                <Badge variant="destructive">
                  <TriangleAlert aria-hidden />
                  {t('agents.schedules.failureStreak', {
                    count: schedule.consecutive_failure_count,
                  })}
                </Badge>
              )}
            </div>
            {schedule.name && (
              <p className="text-muted-foreground line-clamp-1 text-sm">
                {schedule.instruction}
              </p>
            )}
            {meta.length > 0 && (
              <p className="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                {meta.map(({ icon: Icon, text }) => (
                  <span key={text} className="inline-flex items-center gap-1">
                    <Icon aria-hidden className="size-3.5 shrink-0" />
                    {text}
                  </span>
                ))}
              </p>
            )}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1 pl-5 sm:pl-0">
          {recurring && (active || paused) && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              shape="pill"
              onClick={() =>
                active ? onRunNow(schedule) : onSetPaused(schedule, false)
              }
            >
              <Play />
              {active
                ? t('agents.schedules.runNow')
                : t('agents.schedules.resume')}
            </Button>
          )}
          <ActionMenu
            triggerLabel={t('agents.schedules.actions')}
            options={menu}
          />
          {recurring && (
            <IconButton
              label={
                expanded
                  ? t('agents.schedules.hideRuns')
                  : t('agents.schedules.showRuns')
              }
              variant="ghost-muted"
              size="icon-xs"
              aria-expanded={expanded}
              onClick={() => onToggleRuns(schedule.id)}
            >
              <ChevronDown
                aria-hidden
                className={cn(
                  'transition-transform duration-200',
                  expanded && 'rotate-180',
                )}
              />
            </IconButton>
          )}
        </div>
      </div>
      {recurring && expanded && (
        <div className="border-border border-t">
          <RunLog scheduleId={schedule.id} onSelect={onSelectRun} />
        </div>
      )}
    </Card>
  );
}
