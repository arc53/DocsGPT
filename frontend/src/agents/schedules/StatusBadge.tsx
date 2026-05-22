import { cn } from '@/lib/utils';

import type { ScheduleRunStatus, ScheduleStatus } from '../types/schedule';

export type ScheduleStatusBadgeStatus = ScheduleStatus | ScheduleRunStatus;

export type ScheduleStatusBadgeProps = {
  status: ScheduleStatusBadgeStatus;
  className?: string;
};

const STATUS_CLASSES: Record<ScheduleStatusBadgeStatus, string> = {
  // Schedule statuses
  active:
    'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300',
  paused:
    'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  completed: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
  cancelled: 'bg-muted text-muted-foreground',
  // Run statuses
  success:
    'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300',
  failed: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
  skipped:
    'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  running: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
  pending: 'bg-muted text-muted-foreground',
  timeout: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
};

/** Maps a status string to a human label (sentence-cased, underscores spaced). */
export const formatStatusLabel = (status: string): string => {
  const spaced = status.replace(/_/g, ' ');
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
};

/** Returns the Tailwind classes for a given schedule/run status pill. */
export const getStatusClasses = (status: ScheduleStatusBadgeStatus): string =>
  STATUS_CLASSES[status] ?? 'bg-muted text-muted-foreground';

/** Colored pill for schedule or run statuses. */
export default function ScheduleStatusBadge({
  status,
  className,
}: ScheduleStatusBadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2 py-0.5 text-[11px] leading-[16px] font-medium',
        getStatusClasses(status),
        className,
      )}
      data-status={status}
    >
      {formatStatusLabel(status)}
    </span>
  );
}
