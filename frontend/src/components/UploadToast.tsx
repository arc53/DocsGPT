import { ChevronDown, X } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import { cn } from '@/lib/utils';

import {
  dismissUploadTask,
  selectUploadTasks,
  type UploadTask,
} from '../upload/uploadSlice';
import { Button } from './ui/button';
import {
  Toast,
  ToastActions,
  ToastContent,
  ToastHeader,
  ToastItem,
  ToastMessage,
  ToastStatus,
  ToastTitle,
} from './ui/toast';

const PROGRESS_RADIUS = 10;
const PROGRESS_CIRCUMFERENCE = 2 * Math.PI * PROGRESS_RADIUS;

const IN_PROGRESS_STATUSES = new Set<UploadTask['status']>([
  'preparing',
  'uploading',
  'training',
]);

/**
 * Single merged upload card — Google-Drive style. Multiple in-flight
 * uploads share one toast with a list of rows; the header reflects
 * the *primary* task's status (the newest still-running task, or the
 * newest task overall if all are terminal). Per-task progress lives
 * on each row.
 *
 * Renders only its ``Toast`` card: App.tsx mounts the shared
 * ``ToastViewport`` and places this card at the bottom of the stack
 * (and moves the whole stack left while the workflow Preview drawer is
 * open).
 *
 * Dismissal: the header X dismisses every visible task at once
 * (mirrors the GDrive panel close — keeps the surface tidy without
 * per-row controls). The chevron collapses the row list.
 */
export default function UploadToast() {
  const [collapsed, setCollapsed] = useState(false);

  const { t } = useTranslation();
  const dispatch = useDispatch();
  const uploadTasks = useSelector(selectUploadTasks);

  const visibleTasks = uploadTasks.filter((task) => !task.dismissed);
  if (visibleTasks.length === 0) return null;

  // Pick the task that drives the header status: prefer a still-
  // running task (most-recent first since the slice unshifts), and
  // fall back to whatever's most-recent if everything is terminal.
  const primaryTask =
    visibleTasks.find((task) => IN_PROGRESS_STATUSES.has(task.status)) ??
    visibleTasks[0];

  const headerLabel = getStatusHeading(primaryTask.status, t);

  const dismissAll = () => {
    for (const task of visibleTasks) {
      dispatch(dismissUploadTask(task.id));
    }
  };

  return (
    <Toast>
      <ToastHeader
        variant={primaryTask.status === 'failed' ? 'destructive' : 'default'}
      >
        <ToastTitle>{headerLabel}</ToastTitle>
        <ToastActions>
          <Button
            type="button"
            variant="ghost-muted"
            size="icon-sm"
            onClick={() => setCollapsed((prev) => !prev)}
            aria-label={
              collapsed
                ? t('modals.uploadDoc.progress.expandDetails')
                : t('modals.uploadDoc.progress.collapseDetails')
            }
          >
            <ChevronDown
              className={cn(
                'h-4 w-4 transition-transform duration-200',
                collapsed && 'rotate-180',
              )}
            />
          </Button>
          <Button
            type="button"
            variant="ghost-muted"
            size="icon-sm"
            onClick={dismissAll}
            aria-label={t('modals.uploadDoc.progress.dismiss')}
          >
            <X className="h-4 w-4" />
          </Button>
        </ToastActions>
      </ToastHeader>

      <div
        className={cn(
          'grid overflow-hidden transition-[grid-template-rows] duration-300 ease-out',
          collapsed ? 'grid-rows-[0fr]' : 'grid-rows-[1fr]',
        )}
      >
        <div
          className={cn(
            'min-h-0 overflow-hidden transition-opacity duration-300',
            collapsed ? 'opacity-0' : 'opacity-100',
          )}
        >
          <ToastContent scrollable>
            {visibleTasks.map((task) => (
              <UploadRow key={task.id} task={task} t={t} />
            ))}
          </ToastContent>
        </div>
      </div>
    </Toast>
  );
}

function UploadRow({
  task,
  t,
}: {
  task: UploadTask;
  t: ReturnType<typeof useTranslation>['t'];
}) {
  const showProgress = IN_PROGRESS_STATUSES.has(task.status);
  const rawProgress = Math.min(Math.max(task.progress ?? 0, 0), 100);
  const formattedProgress = Math.round(rawProgress);
  const progressOffset = PROGRESS_CIRCUMFERENCE * (1 - rawProgress / 100);

  return (
    <>
      <ToastItem
        label={<span title={task.fileName}>{task.fileName}</span>}
        meta={
          task.status === 'training' && task.stage
            ? t(`modals.uploadDoc.progress.${task.stage}`)
            : undefined
        }
      >
        {showProgress && (
          // Determinate ring: ToastStatus "pending" is an indeterminate
          // spinner, and each row reports its own percentage.
          <svg
            width="24"
            height="24"
            viewBox="0 0 24 24"
            className="text-primary h-6 w-6 shrink-0"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={formattedProgress}
            aria-label={t('modals.uploadDoc.progress.uploadProgress', {
              progress: formattedProgress,
            })}
          >
            <circle
              className="text-muted dark:text-muted-foreground/30"
              stroke="currentColor"
              strokeWidth="2"
              cx="12"
              cy="12"
              r={PROGRESS_RADIUS}
              fill="none"
            />
            <circle
              className="text-primary"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeDasharray={PROGRESS_CIRCUMFERENCE}
              strokeDashoffset={progressOffset}
              cx="12"
              cy="12"
              r={PROGRESS_RADIUS}
              fill="none"
              transform="rotate(-90 12 12)"
            />
          </svg>
        )}

        {task.status === 'completed' && (
          <ToastStatus
            status="success"
            label={t('modals.uploadDoc.progress.completed')}
          />
        )}

        {task.status === 'failed' && (
          <ToastStatus
            status="destructive"
            label={t('modals.uploadDoc.progress.failed')}
          />
        )}
      </ToastItem>

      {task.status === 'failed' &&
        (task.tokenLimitReached || task.errorMessage) && (
          <ToastMessage variant="destructive">
            {task.tokenLimitReached
              ? t('modals.uploadDoc.progress.tokenLimit')
              : task.errorMessage}
          </ToastMessage>
        )}
    </>
  );
}

function getStatusHeading(
  status: UploadTask['status'],
  t: ReturnType<typeof useTranslation>['t'],
): string {
  switch (status) {
    case 'preparing':
      return t('modals.uploadDoc.progress.wait');
    case 'uploading':
    case 'training':
      return t('modals.uploadDoc.progress.upload');
    case 'completed':
      return t('modals.uploadDoc.progress.completed');
    case 'failed':
      return t('modals.uploadDoc.progress.failed');
    default:
      return t('modals.uploadDoc.progress.preparing');
  }
}
