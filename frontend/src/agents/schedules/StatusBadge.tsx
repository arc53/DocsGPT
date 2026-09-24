import { Badge } from '@/components/ui/badge';

import type { ScheduleRunStatus, ScheduleStatus } from '../types/schedule';

export type ScheduleStatusBadgeStatus = ScheduleStatus | ScheduleRunStatus;

export type ScheduleStatusBadgeProps = {
  status: ScheduleStatusBadgeStatus;
  className?: string;
};

type StatusVariant = 'success' | 'warning' | 'info' | 'destructive' | 'neutral';

const STATUS_VARIANTS: Record<ScheduleStatusBadgeStatus, StatusVariant> = {
  // Schedule statuses
  active: 'success',
  paused: 'warning',
  completed: 'success',
  cancelled: 'neutral',
  // Run statuses
  success: 'success',
  failed: 'destructive',
  skipped: 'warning',
  running: 'info',
  pending: 'neutral',
  timeout: 'destructive',
};

/** Maps a status string to a human label (sentence-cased, underscores spaced). */
export const formatStatusLabel = (status: string): string => {
  const spaced = status.replace(/_/g, ' ');
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
};

/** Returns the Badge variant for a given schedule/run status. */
export const getStatusVariant = (
  status: ScheduleStatusBadgeStatus,
): StatusVariant => STATUS_VARIANTS[status] ?? 'neutral';

/** Colored pill for schedule or run statuses. */
export default function ScheduleStatusBadge({
  status,
  className,
}: ScheduleStatusBadgeProps) {
  return (
    <Badge
      variant={getStatusVariant(status)}
      className={className}
      data-status={status}
    >
      {formatStatusLabel(status)}
    </Badge>
  );
}
