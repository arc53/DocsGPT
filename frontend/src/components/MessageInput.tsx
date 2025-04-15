import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import endpoints from '../api/endpoints';
import userService from '../api/services/userService';
import ClipIcon from '../assets/clip.svg';
import PaperPlane from '../assets/paper_plane.svg';
import SourceIcon from '../assets/source.svg';
import SpinnerDark from '../assets/spinner-dark.svg';
import Spinner from '../assets/spinner.svg';
import ToolIcon from '../assets/tool.svg';
import { setAttachments } from '../conversation/conversationSlice';
import { useDarkTheme } from '../hooks';
import { ActiveState } from '../models/misc';
import {
  selectSelectedDocs,
  selectToken,
} from '../preferences/preferenceSlice';
import Upload from '../upload/Upload';
import SourcesPopup from './SourcesPopup';
import ToolsPopup from './ToolsPopup';

type MessageInputProps = {
  value: string;
  onChange: (e: React.ChangeEvent<HTMLTextAreaElement>) => void;
  onSubmit: () => void;
  loading: boolean;
  showSourceButton?: boolean;
  showToolButton?: boolean;
};

type UploadState = {
  taskId: string;
  fileName: string;
  progress: number;
  attachment_id?: string;
  token_count?: number;
  status: 'uploading' | 'processing' | 'completed' | 'failed';
};

export default function MessageInput({
  value,
  onChange,
  onSubmit,
  loading,
  showSourceButton = true,
  showToolButton = true,
}: MessageInputProps) {
  const { t } = useTranslation();
  const [isDarkTheme] = useDarkTheme();
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const sourceButtonRef = useRef<HTMLButtonElement>(null);
  const toolButtonRef = useRef<HTMLButtonElement>(null);
  const [isSourcesPopupOpen, setIsSourcesPopupOpen] = useState(false);
  const [isToolsPopupOpen, setIsToolsPopupOpen] = useState(false);
  const [uploadModalState, setUploadModalState] =
    useState<ActiveState>('INACTIVE');
  const [uploads, setUploads] = useState<UploadState[]>([]);

  const selectedDocs = useSelector(selectSelectedDocs);
  const token = useSelector(selectToken);

  const dispatch = useDispatch();

  const handleFileAttachment = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files || e.target.files.length === 0) return;

    const file = e.target.files[0];
    const formData = new FormData();
    formData.append('file', file);

    const apiHost = import.meta.env.VITE_API_HOST;
    const xhr = new XMLHttpRequest();

    const uploadState: UploadState = {
      taskId: '',
      fileName: file.name,
      progress: 0,
      status: 'uploading',
    };

    setUploads((prev) => [...prev, uploadState]);
    const uploadIndex = uploads.length;

    xhr.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable) {
        const progress = Math.round((event.loaded / event.total) * 100);
        setUploads((prev) =>
          prev.map((upload, index) =>
            index === uploadIndex ? { ...upload, progress } : upload,
          ),
        );
      }
    });

    xhr.onload = () => {
      if (xhr.status === 200) {
        const response = JSON.parse(xhr.responseText);
        console.log('File uploaded successfully:', response);

        if (response.task_id) {
          setUploads((prev) =>
            prev.map((upload, index) =>
              index === uploadIndex
                ? { ...upload, taskId: response.task_id, status: 'processing' }
                : upload,
            ),
          );
        }
      } else {
        setUploads((prev) =>
          prev.map((upload, index) =>
            index === uploadIndex ? { ...upload, status: 'failed' } : upload,
          ),
        );
        console.error('Error uploading file:', xhr.responseText);
      }
    };

    xhr.onerror = () => {
      setUploads((prev) =>
        prev.map((upload, index) =>
          index === uploadIndex ? { ...upload, status: 'failed' } : upload,
        ),
      );
      console.error('Network error during file upload');
    };

    xhr.open('POST', `${apiHost}${endpoints.USER.STORE_ATTACHMENT}`);
    xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    xhr.send(formData);
    e.target.value = '';
  };

  useEffect(() => {
    let timeoutIds: number[] = [];

    const checkTaskStatus = () => {
      const processingUploads = uploads.filter(
        (upload) => upload.status === 'processing' && upload.taskId,
      );

      processingUploads.forEach((upload) => {
        userService
          .getTaskStatus(upload.taskId, null)
          .then((data) => data.json())
          .then((data) => {
            console.log('Task status:', data);

            setUploads((prev) =>
              prev.map((u) => {
                if (u.taskId !== upload.taskId) return u;

                if (data.status === 'SUCCESS') {
                  return {
                    ...u,
                    status: 'completed',
                    progress: 100,
                    attachment_id: data.result?.attachment_id,
                    token_count: data.result?.token_count,
                  };
                } else if (data.status === 'FAILURE') {
                  return { ...u, status: 'failed' };
                } else if (data.status === 'PROGRESS' && data.result?.current) {
                  return { ...u, progress: data.result.current };
                }
                return u;
              }),
            );

            if (data.status !== 'SUCCESS' && data.status !== 'FAILURE') {
              const timeoutId = window.setTimeout(
                () => checkTaskStatus(),
                2000,
              );
              timeoutIds.push(timeoutId);
            }
          })
          .catch((error) => {
            console.error('Error checking task status:', error);
            setUploads((prev) =>
              prev.map((u) =>
                u.taskId === upload.taskId ? { ...u, status: 'failed' } : u,
              ),
            );
          });
      });
    };

    if (uploads.some((upload) => upload.status === 'processing')) {
      const timeoutId = window.setTimeout(checkTaskStatus, 2000);
      timeoutIds.push(timeoutId);
    }

    return () => {
      timeoutIds.forEach((id) => clearTimeout(id));
    };
  }, [uploads]);

  const handleInput = () => {
    if (inputRef.current) {
      if (window.innerWidth < 350) inputRef.current.style.height = 'auto';
      else inputRef.current.style.height = '64px';
      inputRef.current.style.height = `${Math.min(
        inputRef.current.scrollHeight,
        96,
      )}px`;
    }
  };

  useEffect(() => {
    inputRef.current?.focus();
    handleInput();
  }, []);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
      if (inputRef.current) {
        inputRef.current.value = '';
        handleInput();
      }
    }
  };

  const handlePostDocumentSelect = (doc: any) => {
    console.log('Selected document:', doc);
  };

  const handleSubmit = () => {
    const completedAttachments = uploads
      .filter((upload) => upload.status === 'completed' && upload.attachment_id)
      .map((upload) => ({
        fileName: upload.fileName,
        id: upload.attachment_id as string,
      }));

    dispatch(setAttachments(completedAttachments));

    onSubmit();
  };
  return (
    <div className="mx-2 flex w-full flex-col">
      <div className="relative flex w-full flex-col rounded-[23px] border border-dark-gray bg-lotion dark:border-grey dark:bg-transparent">
        <div className="flex flex-wrap gap-1.5 px-4 pb-0 pt-3 sm:gap-2 sm:px-6">
          {uploads.map((upload, index) => (
            <div
              key={index}
              className="flex items-center rounded-[32px] border border-[#AAAAAA] bg-white px-2 py-1 text-[12px] text-[#5D5D5D] dark:border-purple-taupe dark:bg-[#1F2028] dark:text-bright-gray sm:px-3 sm:py-1.5 sm:text-[14px]"
            >
              <span className="max-w-[120px] truncate font-medium sm:max-w-[150px]">
                {upload.fileName}
              </span>

              {upload.status === 'completed' && (
                <span className="ml-2 text-green-500">✓</span>
              )}

              {upload.status === 'failed' && (
                <span className="ml-2 text-red-500">✗</span>
              )}

              {(upload.status === 'uploading' ||
                upload.status === 'processing') && (
                <div className="relative ml-2 h-4 w-4">
                  <svg className="h-4 w-4" viewBox="0 0 24 24">
                    <circle
                      className="text-gray-200 dark:text-gray-700"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="4"
                      fill="none"
                    />
                    <circle
                      className="text-blue-600 dark:text-blue-400"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="4"
                      fill="none"
                      strokeDasharray="62.83"
                      strokeDashoffset={62.83 - (upload.progress / 100) * 62.83}
                      transform="rotate(-90 12 12)"
                    />
                  </svg>
                </div>
              )}
            </div>
          ))}
        </div>

        <div className="w-full">
          <label htmlFor="message-input" className="sr-only">
            {t('inputPlaceholder')}
          </label>
          <textarea
            id="message-input"
            ref={inputRef}
            value={value}
            onChange={onChange}
            tabIndex={1}
            placeholder={t('inputPlaceholder')}
            className="inputbox-style no-scrollbar w-full overflow-y-auto overflow-x-hidden whitespace-pre-wrap rounded-t-[23px] bg-lotion px-4 py-3 text-base leading-tight opacity-100 focus:outline-none dark:bg-transparent dark:text-bright-gray dark:placeholder-bright-gray dark:placeholder-opacity-50 sm:px-6 sm:py-5"
            onInput={handleInput}
            onKeyDown={handleKeyDown}
            aria-label={t('inputPlaceholder')}
          />
        </div>

        <div className="flex items-center px-3 py-1.5 sm:px-4 sm:py-2">
          <div className="flex flex-grow flex-wrap gap-1 sm:gap-2">
            {showSourceButton && (
              <button
                ref={sourceButtonRef}
                className="xs:px-3 xs:py-1.5 xs:max-w-[150px] flex max-w-[130px] items-center rounded-[32px] border border-[#AAAAAA] px-2 py-1 transition-colors hover:bg-gray-100 dark:border-purple-taupe dark:hover:bg-[#2C2E3C]"
                onClick={() => setIsSourcesPopupOpen(!isSourcesPopupOpen)}
              >
                <img
                  src={SourceIcon}
                  alt="Sources"
                  className="mr-1 h-3.5 w-3.5 flex-shrink-0 sm:mr-1.5 sm:h-4 sm:w-4"
                />
                <span className="xs:text-[12px] overflow-hidden truncate text-[10px] font-medium text-[#5D5D5D] dark:text-bright-gray sm:text-[14px]">
                  {selectedDocs
                    ? selectedDocs.name
                    : t('conversation.sources.title')}
                </span>
              </button>
            )}

            {showToolButton && (
              <button
                ref={toolButtonRef}
                className="xs:px-3 xs:py-1.5 xs:max-w-[150px] flex max-w-[130px] items-center rounded-[32px] border border-[#AAAAAA] px-2 py-1 transition-colors hover:bg-gray-100 dark:border-purple-taupe dark:hover:bg-[#2C2E3C]"
                onClick={() => setIsToolsPopupOpen(!isToolsPopupOpen)}
              >
                <img
                  src={ToolIcon}
                  alt="Tools"
                  className="mr-1 h-3.5 w-3.5 flex-shrink-0 sm:mr-1.5 sm:h-4 sm:w-4"
                />
                <span className="xs:text-[12px] overflow-hidden truncate text-[10px] font-medium text-[#5D5D5D] dark:text-bright-gray sm:text-[14px]">
                  {t('settings.tools.label')}
                </span>
              </button>
            )}
            <label className="xs:px-3 xs:py-1.5 flex cursor-pointer items-center rounded-[32px] border border-[#AAAAAA] px-2 py-1 transition-colors hover:bg-gray-100 dark:border-purple-taupe dark:hover:bg-[#2C2E3C]">
              <img
                src={ClipIcon}
                alt="Attach"
                className="mr-1 h-3.5 w-3.5 sm:mr-1.5 sm:h-4 sm:w-4"
              />
              <span className="xs:text-[12px] text-[10px] font-medium text-[#5D5D5D] dark:text-bright-gray sm:text-[14px]">
                Attach
              </span>
              <input
                type="file"
                className="hidden"
                onChange={handleFileAttachment}
              />
            </label>

            {/* Additional badges can be added here in the future */}
          </div>

          <button
            onClick={loading ? undefined : handleSubmit}
            aria-label={loading ? t('loading') : t('send')}
            className={`flex items-center justify-center rounded-full p-2 sm:p-2.5 ${loading ? 'bg-gray-300 dark:bg-gray-600' : 'bg-black dark:bg-white'} ml-auto flex-shrink-0`}
            disabled={loading}
          >
            {loading ? (
              <img
                src={isDarkTheme ? SpinnerDark : Spinner}
                className="h-3.5 w-3.5 animate-spin sm:h-4 sm:w-4"
                alt={t('loading')}
              />
            ) : (
              <img
                className={`h-3.5 w-3.5 sm:h-4 sm:w-4 ${isDarkTheme ? 'invert filter' : ''}`}
                src={PaperPlane}
                alt={t('send')}
              />
            )}
          </button>
        </div>
      </div>

      <SourcesPopup
        isOpen={isSourcesPopupOpen}
        onClose={() => setIsSourcesPopupOpen(false)}
        anchorRef={sourceButtonRef}
        handlePostDocumentSelect={handlePostDocumentSelect}
        setUploadModalState={setUploadModalState}
      />

      <ToolsPopup
        isOpen={isToolsPopupOpen}
        onClose={() => setIsToolsPopupOpen(false)}
        anchorRef={toolButtonRef}
      />

      {uploadModalState === 'ACTIVE' && (
        <Upload
          receivedFile={[]}
          setModalState={setUploadModalState}
          isOnboarding={false}
          renderTab={null}
          close={() => setUploadModalState('INACTIVE')}
        />
      )}
    </div>
  );
}
