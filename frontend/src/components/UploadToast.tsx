import { X } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import { selectWorkflowPreviewOpen } from '../agents/workflow/workflowPreviewSlice';
import CheckCircleFilled from '../assets/check-circle-filled.svg';
import ChevronDown from '../assets/chevron-down.svg';
import WarnIcon from '../assets/warn.svg';
import {
  dismissUploadTask,
  selectUploadTasks,
  type UploadTask,
} from '../upload/uploadSlice';
import { Button } from './ui/button';

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
 * Dismissal: the header X dismisses every visible task at once
 * (mirrors the GDrive panel close — keeps the surface tidy without
 * per-row controls). The chevron collapses the row list.
 */
export default function UploadToast() {
  const [collapsed, setCollapsed] = useState(false);

  const { t } = useTranslation();
  const dispatch = useDispatch();
  const uploadTasks = useSelector(selectUploadTasks);
  // The workflow Preview drawer occupies the right edge; shift the toast to
  // the bottom-left while it's open so it stays visible without covering the
  // drawer's attach/send controls.
  const previewOpen = useSelector(selectWorkflowPreviewOpen);

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
    <div
      className={`fixed bottom-4 z-50 flex max-w-md flex-col gap-2 ${
        previewOpen ? 'left-4' : 'right-4'
      }`}
      onMouseDown={(e) => e.stopPropagation()}
      role="status"
      aria-live="polite"
      aria-atomic="false"
    >
      <div
        className={`border-border bg-card shadow-toast w-[271px] overflow-hidden rounded-2xl border transition-all duration-300`}
      >
        <div
          className={`flex items-center justify-between px-4 py-3 ${
            primaryTask.status !== 'failed'
              ? 'bg-accent/50 dark:bg-muted'
              : 'bg-destructive/10 dark:bg-destructive/10'
          }`}
        >
          <h3 className="dark:text-foreground text-sm leading-[16.5px] font-medium text-black">
            {headerLabel}
          </h3>
          <div className="flex items-center gap-1">
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              onClick={() => setCollapsed((prev) => !prev)}
              aria-label={
                collapsed
                  ? t('modals.uploadDoc.progress.expandDetails')
                  : t('modals.uploadDoc.progress.collapseDetails')
              }
              className="text-black opacity-70 hover:bg-transparent hover:opacity-100 dark:text-white dark:hover:bg-transparent"
            >
              <img
                src={ChevronDown}
                alt=""
                className={`h-4 w-4 transform transition-transform duration-200 dark:invert ${
                  collapsed ? 'rotate-180' : ''
                }`}
              />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              onClick={dismissAll}
              className="text-black opacity-70 hover:bg-transparent hover:opacity-100 dark:text-white dark:hover:bg-transparent"
              aria-label={t('modals.uploadDoc.progress.dismiss')}
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>

        <div
          className="grid overflow-hidden transition-[grid-template-rows] duration-300 ease-out"
          style={{ gridTemplateRows: collapsed ? '0fr' : '1fr' }}
        >
          <div
            className={`min-h-0 overflow-hidden transition-opacity duration-300 ${
              collapsed ? 'opacity-0' : 'opacity-100'
            }`}
          >
            <ul className="max-h-72 overflow-y-auto">
              {visibleTasks.map((task) => (
                <UploadRow key={task.id} task={task} t={t} />
              ))}
            </ul>
          </div>
        </div>
      </div>
    </div>
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
    <li className="border-border/50 border-b last:border-b-0">
      <div className="flex items-center justify-between px-5 py-3">
        <div className="flex min-w-0 flex-col">
          <p
            className="dark:text-muted-foreground max-w-[200px] truncate text-sm leading-[16.5px] font-normal text-black"
            title={task.fileName}
          >
            {task.fileName}
          </p>
          {task.status === 'training' && task.stage && (
            <span className="text-muted-foreground mt-0.5 text-xs leading-[14px]">
              {t(`modals.uploadDoc.progress.${task.stage}`)}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {showProgress && (
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
            <img
              src={CheckCircleFilled}
              alt=""
              className="h-6 w-6 shrink-0"
              aria-hidden="true"
            />
          )}

          {task.status === 'failed' && (
            <img
              src={WarnIcon}
              alt=""
              className="h-6 w-6 shrink-0"
              aria-hidden="true"
            />
          )}
        </div>
      </div>

      {task.status === 'failed' &&
        (task.tokenLimitReached || task.errorMessage) && (
          <span className="block px-5 pb-3 text-xs text-red-500">
            {task.tokenLimitReached
              ? t('modals.uploadDoc.progress.tokenLimit')
              : task.errorMessage}
          </span>
        )}
    </li>
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
