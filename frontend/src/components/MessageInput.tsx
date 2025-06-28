import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import endpoints from '../api/endpoints';
import userService from '../api/services/userService';
import AlertIcon from '../assets/alert.svg';
import ClipIcon from '../assets/clip.svg';
import ExitIcon from '../assets/exit.svg';
import PaperPlane from '../assets/paper_plane.svg';
import SourceIcon from '../assets/source.svg';
import DocumentationDark from '../assets/documentation-dark.svg';
import SpinnerDark from '../assets/spinner-dark.svg';
import Spinner from '../assets/spinner.svg';
import ToolIcon from '../assets/tool.svg';
import {
  addAttachment,
  removeAttachment,
  selectAttachments,
  updateAttachment,
} from '../upload/uploadSlice';
import { useDarkTheme } from '../hooks';
import { ActiveState } from '../models/misc';
import {
  selectSelectedDocs,
  selectToken,
} from '../preferences/preferenceSlice';
import Upload from '../upload/Upload';
import { getOS, isTouchDevice } from '../utils/browserUtils';
import SourcesPopup from './SourcesPopup';
import ToolsPopup from './ToolsPopup';

type MessageInputProps = {
  onSubmit: (text: string) => void;
  loading: boolean;
  showSourceButton?: boolean;
  showToolButton?: boolean;
  autoFocus?: boolean;
};

export default function MessageInput({
  onSubmit,
  loading,
  showSourceButton = true,
  showToolButton = true,
  autoFocus = true,
}: MessageInputProps) {
  const { t } = useTranslation();
  const [isDarkTheme] = useDarkTheme();
  const [value, setValue] = useState('');
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const sourceButtonRef = useRef<HTMLButtonElement>(null);
  const toolButtonRef = useRef<HTMLButtonElement>(null);
  const [isSourcesPopupOpen, setIsSourcesPopupOpen] = useState(false);
  const [isToolsPopupOpen, setIsToolsPopupOpen] = useState(false);
  const [uploadModalState, setUploadModalState] =
    useState<ActiveState>('INACTIVE');

  const selectedDocs = useSelector(selectSelectedDocs);
  const token = useSelector(selectToken);
  const attachments = useSelector(selectAttachments);

  const dispatch = useDispatch();

  const browserOS = getOS();
  const isTouch = isTouchDevice();

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (
        ((browserOS === 'win' || browserOS === 'linux') &&
          event.ctrlKey &&
          event.key === 'k') ||
        (browserOS === 'mac' && event.metaKey && event.key === 'k')
      ) {
        event.preventDefault();
        setIsSourcesPopupOpen(!isSourcesPopupOpen);
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [browserOS]);

  const handleFileAttachment = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files || e.target.files.length === 0) return;

    const file = e.target.files[0];
    const formData = new FormData();
    formData.append('file', file);

    const apiHost = import.meta.env.VITE_API_HOST;
    const xhr = new XMLHttpRequest();

    const newAttachment = {
      fileName: file.name,
      progress: 0,
      status: 'uploading' as const,
      taskId: '',
    };

    dispatch(addAttachment(newAttachment));

    xhr.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable) {
        const progress = Math.round((event.loaded / event.total) * 100);
        dispatch(
          updateAttachment({
            taskId: newAttachment.taskId,
            updates: { progress },
          }),
        );
      }
    });

    xhr.onload = () => {
      if (xhr.status === 200) {
        const response = JSON.parse(xhr.responseText);
        if (response.task_id) {
          dispatch(
            updateAttachment({
              taskId: newAttachment.taskId,
              updates: {
                taskId: response.task_id,
                status: 'processing',
                progress: 10,
              },
            }),
          );
        }
      } else {
        dispatch(
          updateAttachment({
            taskId: newAttachment.taskId,
            updates: { status: 'failed' },
          }),
        );
      }
    };

    xhr.onerror = () => {
      dispatch(
        updateAttachment({
          taskId: newAttachment.taskId,
          updates: { status: 'failed' },
        }),
      );
    };

    xhr.open('POST', `${apiHost}${endpoints.USER.STORE_ATTACHMENT}`);
    xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    xhr.send(formData);
    e.target.value = '';
  };

  useEffect(() => {
    const checkTaskStatus = () => {
      const processingAttachments = attachments.filter(
        (att) => att.status === 'processing' && att.taskId,
      );

      processingAttachments.forEach((attachment) => {
        userService
          .getTaskStatus(attachment.taskId!, null)
          .then((data) => data.json())
          .then((data) => {
            if (data.status === 'SUCCESS') {
              dispatch(
                updateAttachment({
                  taskId: attachment.taskId!,
                  updates: {
                    status: 'completed',
                    progress: 100,
                    id: data.result?.attachment_id,
                    token_count: data.result?.token_count,
                  },
                }),
              );
            } else if (data.status === 'FAILURE') {
              dispatch(
                updateAttachment({
                  taskId: attachment.taskId!,
                  updates: { status: 'failed' },
                }),
              );
            } else if (data.status === 'PROGRESS' && data.result?.current) {
              dispatch(
                updateAttachment({
                  taskId: attachment.taskId!,
                  updates: { progress: data.result.current },
                }),
              );
            }
          })
          .catch(() => {
            dispatch(
              updateAttachment({
                taskId: attachment.taskId!,
                updates: { status: 'failed' },
              }),
            );
          });
      });
    };

    const interval = setInterval(() => {
      if (attachments.some((att) => att.status === 'processing')) {
        checkTaskStatus();
      }
    }, 2000);

    return () => clearInterval(interval);
  }, [attachments, dispatch]);

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
    if (autoFocus) inputRef.current?.focus();
    handleInput();
  }, []);

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setValue(e.target.value);
    handleInput();
  };

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
    if (value.trim() && !loading) {
      onSubmit(value);
      setValue('');
    }
  };
  return (
    <div className="mx-2 flex w-full flex-col">
      <div className="border-dark-gray bg-lotion dark:border-grey relative flex w-full flex-col rounded-[23px] border dark:bg-transparent">
        <div className="flex flex-wrap gap-1.5 px-4 pt-3 pb-0 sm:gap-2 sm:px-6">
          {attachments.map((attachment, index) => (
            <div
              key={index}
              className={`group dark:text-bright-gray relative flex items-center rounded-xl bg-[#EFF3F4] px-2 py-1 text-[12px] text-[#5D5D5D] sm:px-3 sm:py-1.5 sm:text-[14px] dark:bg-[#393B3D] ${
                attachment.status !== 'completed' ? 'opacity-70' : 'opacity-100'
              }`}
              title={attachment.fileName}
            >
              <div className="bg-purple-30 mr-2 items-center justify-center rounded-lg p-[5.5px]">
                {attachment.status === 'completed' && (
                  <img
                    src={DocumentationDark}
                    alt="Attachment"
                    className="h-[15px] w-[15px] object-fill"
                  />
                )}

                {attachment.status === 'failed' && (
                  <img
                    src={AlertIcon}
                    alt="Failed"
                    className="h-[15px] w-[15px] object-fill"
                  />
                )}

                {(attachment.status === 'uploading' ||
                  attachment.status === 'processing') && (
                  <div className="flex h-[15px] w-[15px] items-center justify-center">
                    <svg className="h-[15px] w-[15px]" viewBox="0 0 24 24">
                      <circle
                        className="opacity-0"
                        cx="12"
                        cy="12"
                        r="10"
                        stroke="transparent"
                        strokeWidth="4"
                        fill="none"
                      />
                      <circle
                        className="text-[#ECECF1]"
                        cx="12"
                        cy="12"
                        r="10"
                        stroke="currentColor"
                        strokeWidth="4"
                        fill="none"
                        strokeDasharray="62.83"
                        strokeDashoffset={
                          62.83 * (1 - attachment.progress / 100)
                        }
                        transform="rotate(-90 12 12)"
                      />
                    </svg>
                  </div>
                )}
              </div>

              <span className="max-w-[120px] truncate font-medium sm:max-w-[150px]">
                {attachment.fileName}
              </span>

              <button
                className="ml-1.5 flex items-center justify-center rounded-full p-1"
                onClick={() => {
                  if (attachment.id) {
                    dispatch(removeAttachment(attachment.id));
                  } else if (attachment.taskId) {
                    dispatch(removeAttachment(attachment.taskId));
                  }
                }}
                aria-label={t('conversation.attachments.remove')}
              >
                <img
                  src={ExitIcon}
                  alt={t('conversation.attachments.remove')}
                  className="h-2.5 w-2.5 filter dark:invert"
                />
              </button>
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
            onChange={handleChange}
            tabIndex={1}
            placeholder={t('inputPlaceholder')}
            className="inputbox-style no-scrollbar bg-lotion dark:text-bright-gray dark:placeholder:text-bright-gray/50 w-full overflow-x-hidden overflow-y-auto rounded-t-[23px] px-4 py-3 text-base leading-tight whitespace-pre-wrap opacity-100 placeholder:text-gray-500 focus:outline-hidden sm:px-6 sm:py-5 dark:bg-transparent"
            onInput={handleInput}
            onKeyDown={handleKeyDown}
            aria-label={t('inputPlaceholder')}
          />
        </div>

        <div className="flex items-center px-3 py-1.5 sm:px-4 sm:py-2">
          <div className="flex grow flex-wrap gap-1 sm:gap-2">
            {showSourceButton && (
              <button
                ref={sourceButtonRef}
                className="xs:px-3 xs:py-1.5 dark:border-purple-taupe flex max-w-[130px] items-center rounded-[32px] border border-[#AAAAAA] px-2 py-1 transition-colors hover:bg-gray-100 sm:max-w-[150px] dark:hover:bg-[#2C2E3C]"
                onClick={() => setIsSourcesPopupOpen(!isSourcesPopupOpen)}
                title={
                  selectedDocs
                    ? selectedDocs.name
                    : t('conversation.sources.title')
                }
              >
                <img
                  src={SourceIcon}
                  alt="Sources"
                  className="mr-1 h-3.5 w-3.5 shrink-0 sm:mr-1.5 sm:h-4"
                />
                <span className="xs:text-[12px] dark:text-bright-gray truncate overflow-hidden text-[10px] font-medium text-[#5D5D5D] sm:text-[14px]">
                  {selectedDocs
                    ? selectedDocs.name
                    : t('conversation.sources.title')}
                </span>
                {!isTouch && (
                  <span className="ml-1 hidden text-[10px] text-gray-500 sm:inline-block dark:text-gray-400">
                    {browserOS === 'mac' ? '(⌘K)' : '(ctrl+K)'}
                  </span>
                )}
              </button>
            )}

            {showToolButton && (
              <button
                ref={toolButtonRef}
                className="xs:px-3 xs:py-1.5 xs:max-w-[150px] dark:border-purple-taupe flex max-w-[130px] items-center rounded-[32px] border border-[#AAAAAA] px-2 py-1 transition-colors hover:bg-gray-100 dark:hover:bg-[#2C2E3C]"
                onClick={() => setIsToolsPopupOpen(!isToolsPopupOpen)}
              >
                <img
                  src={ToolIcon}
                  alt="Tools"
                  className="mr-1 h-3.5 w-3.5 shrink-0 sm:mr-1.5 sm:h-4 sm:w-4"
                />
                <span className="xs:text-[12px] dark:text-bright-gray truncate overflow-hidden text-[10px] font-medium text-[#5D5D5D] sm:text-[14px]">
                  {t('settings.tools.label')}
                </span>
              </button>
            )}
            <label className="xs:px-3 xs:py-1.5 dark:border-purple-taupe flex cursor-pointer items-center rounded-[32px] border border-[#AAAAAA] px-2 py-1 transition-colors hover:bg-gray-100 dark:hover:bg-[#2C2E3C]">
              <img
                src={ClipIcon}
                alt="Attach"
                className="mr-1 h-3.5 w-3.5 sm:mr-1.5 sm:h-4 sm:w-4"
              />
              <span className="xs:text-[12px] dark:text-bright-gray text-[10px] font-medium text-[#5D5D5D] sm:text-[14px]">
                {t('conversation.attachments.attach')}
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
            className={`flex items-center justify-center rounded-full p-2 sm:p-2.5 ${loading ? 'bg-gray-300 dark:bg-gray-600' : 'bg-black dark:bg-white'} ml-auto shrink-0`}
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
