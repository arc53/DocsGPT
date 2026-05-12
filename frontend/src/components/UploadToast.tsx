import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import CheckCircleFilled from '../assets/check-circle-filled.svg';
import ChevronDown from '../assets/chevron-down.svg';
import WarnIcon from '../assets/warn.svg';
import {
  dismissUploadTask,
  selectUploadTasks,
  type UploadTask,
} from '../upload/uploadSlice';

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
      className="fixed right-4 bottom-4 z-50 flex max-w-md flex-col gap-2"
      onMouseDown={(e) => e.stopPropagation()}
      role="status"
      aria-live="polite"
      aria-atomic="false"
    >
      <div
        className={`border-border bg-card w-[271px] overflow-hidden rounded-2xl border shadow-[0px_24px_48px_0px_#00000029] transition-all duration-300`}
      >
        <div
          className={`flex items-center justify-between px-4 py-3 ${
            primaryTask.status !== 'failed'
              ? 'bg-accent/50 dark:bg-muted'
              : 'bg-destructive/10 dark:bg-destructive/10'
          }`}
        >
          <h3 className="font-inter dark:text-foreground text-[14px] leading-[16.5px] font-medium text-black">
            {headerLabel}
          </h3>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setCollapsed((prev) => !prev)}
              aria-label={
                collapsed
                  ? t('modals.uploadDoc.progress.expandDetails')
                  : t('modals.uploadDoc.progress.collapseDetails')
              }
              className="flex h-8 items-center justify-center p-0 text-black opacity-70 transition-opacity hover:opacity-100 dark:text-white"
            >
              <img
                src={ChevronDown}
                alt=""
                className={`h-4 w-4 transform transition-transform duration-200 dark:invert ${
                  collapsed ? 'rotate-180' : ''
                }`}
              />
            </button>
            <button
              type="button"
              onClick={dismissAll}
              className="flex h-8 items-center justify-center p-0 text-black opacity-70 transition-opacity hover:opacity-100 dark:text-white"
              aria-label={t('modals.uploadDoc.progress.dismiss')}
            >
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
                className="h-4 w-4"
              >
                <path
                  d="M18 6L6 18"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
                <path
                  d="M6 6L18 18"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </button>
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
        <p
          className="font-inter dark:text-muted-foreground max-w-[200px] truncate text-[13px] leading-[16.5px] font-normal text-black"
          title={task.fileName}
        >
          {task.fileName}
        </p>

        <div className="flex items-center gap-2">
          {showProgress && (
            <svg
              width="24"
              height="24"
              viewBox="0 0 24 24"
              className="h-6 w-6 shrink-0 text-[#7D54D1]"
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
                className="text-[#7D54D1]"
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

      {task.status === 'failed' && (task.tokenLimitReached || task.errorMessage) && (
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
