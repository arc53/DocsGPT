import { useState } from 'react';

import { useDispatch, useSelector } from 'react-redux';
import { useTranslation } from 'react-i18next';
import {
  selectUploadTasks,
  dismissUploadTask,
  clearCompletedTasks,
} from '../upload/uploadSlice';
import ChevronDown from '../assets/chevron-down.svg';
import CheckCircleFilled from '../assets/check-circle-filled.svg';
import WarnIcon from '../assets/warn.svg';

const PROGRESS_RADIUS = 10;
const PROGRESS_CIRCUMFERENCE = 2 * Math.PI * PROGRESS_RADIUS;

export default function UploadToast() {
  const [collapsedTasks, setCollapsedTasks] = useState<Record<string, boolean>>(
    {},
  );

  const toggleTaskCollapse = (taskId: string) => {
    setCollapsedTasks((prev) => ({
      ...prev,
      [taskId]: !prev[taskId],
    }));
  };

  const { t } = useTranslation();
  const dispatch = useDispatch();
  const uploadTasks = useSelector(selectUploadTasks);

  const getStatusHeading = (status: string) => {
    switch (status) {
      case 'preparing':
        return t('modals.uploadDoc.progress.wait');
      case 'uploading':
        return t('modals.uploadDoc.progress.upload');
      case 'training':
        return t('modals.uploadDoc.progress.training');
      case 'completed':
        return t('modals.uploadDoc.progress.completed');
      case 'failed':
        return t('attachments.uploadFailed');
      default:
        return 'Preparing upload';
    }
  };

  return (
    <div className="fixed right-4 bottom-4 z-50 flex max-w-md flex-col gap-2">
      {uploadTasks
        .filter((task) => !task.dismissed)
        .map((task) => {
          const shouldShowProgress = [
            'preparing',
            'uploading',
            'training',
          ].includes(task.status);
          const rawProgress = Math.min(Math.max(task.progress ?? 0, 0), 100);
          const formattedProgress = Math.round(rawProgress);
          const progressOffset =
            PROGRESS_CIRCUMFERENCE * (1 - rawProgress / 100);
          const isCollapsed = collapsedTasks[task.id] ?? false;

          return (
            <div
              key={task.id}
              className={`w-[271px] overflow-hidden rounded-2xl border border-[#00000021] shadow-[0px_24px_48px_0px_#00000029] transition-all duration-300 ${
                task.status === 'completed'
                  ? 'bg-[#FBFBFB] dark:bg-[#26272E]'
                  : task.status === 'failed'
                    ? 'bg-[#FBFBFB] dark:bg-[#26272E]'
                    : 'bg-[#FBFBFB] dark:bg-[#26272E]'
              }`}
            >
              <div className="flex flex-col">
                <div
                  className={`flex items-center justify-between px-4 py-3 ${
                    task.status !== 'failed'
                      ? 'bg-[#FBF2FE] dark:bg-transparent'
                      : ''
                  }`}
                >
                  <h3 className="font-inter text-[14px] leading-[16.5px] font-medium text-black dark:text-[#DCDCDC]">
                    {getStatusHeading(task.status)}
                  </h3>
                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      onClick={() => toggleTaskCollapse(task.id)}
                      aria-label={
                        isCollapsed
                          ? 'Expand upload details'
                          : 'Collapse upload details'
                      }
                      className="flex h-8 items-center justify-center p-0 text-black opacity-70 transition-opacity hover:opacity-100 dark:text-white"
                    >
                      <img
                        src={ChevronDown}
                        alt=""
                        className={`h-4 w-4 transform transition-transform duration-200 dark:invert ${
                          isCollapsed ? '' : 'rotate-180'
                        }`}
                      />
                    </button>
                    <button
                      type="button"
                      onClick={() => dispatch(dismissUploadTask(task.id))}
                      className="flex h-8 items-center justify-center p-0 text-black opacity-70 transition-opacity hover:opacity-100 dark:text-white"
                      aria-label="Dismiss upload toast"
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
                  style={{ gridTemplateRows: isCollapsed ? '0fr' : '1fr' }}
                >
                  <div
                    className={`min-h-0 overflow-hidden transition-opacity duration-300 ${
                      isCollapsed ? 'opacity-0' : 'opacity-100'
                    }`}
                  >
                    <div className="flex items-center justify-between px-5 py-3">
                      <p
                        className="font-inter max-w-[200px] truncate text-[13px] leading-[16.5px] font-normal text-black dark:text-[#B7BAB8]"
                        title={task.fileName}
                      >
                        {task.fileName}
                      </p>

                      <div className="flex items-center gap-2">
                        {shouldShowProgress && (
                          <svg
                            width="24"
                            height="24"
                            viewBox="0 0 24 24"
                            className="h-6 w-6 flex-shrink-0 text-[#7D54D1]"
                            role="progressbar"
                            aria-valuemin={0}
                            aria-valuemax={100}
                            aria-valuenow={formattedProgress}
                            aria-label={`Upload progress ${formattedProgress}%`}
                          >
                            <circle
                              className="text-gray-300 dark:text-gray-700"
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
                            className="h-6 w-6 flex-shrink-0"
                            aria-hidden="true"
                          />
                        )}

                        {task.status === 'failed' && (
                          <img
                            src={WarnIcon}
                            alt=""
                            className="h-6 w-6 flex-shrink-0"
                            aria-hidden="true"
                          />
                        )}
                      </div>
                    </div>

                    {task.status === 'failed' && task.errorMessage && (
                      <span className="block px-5 pb-3 text-xs text-red-500">
                        {task.errorMessage}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </div>
          );
        })}

      {uploadTasks.some(
        (task) => task.status === 'completed' || task.status === 'failed',
      ) && (
        <button
          onClick={() => dispatch(clearCompletedTasks())}
          className="mt-1 mr-1 text-right text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
        >
          Clear
        </button>
      )}
    </div>
  );
}
