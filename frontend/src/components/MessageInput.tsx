import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useDropzone } from 'react-dropzone';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import endpoints from '../api/endpoints';
import userService from '../api/services/userService';
import AlertIcon from '../assets/alert.svg';
import ClipIcon from '../assets/clip.svg';
import DragFileUpload from '../assets/DragFileUpload.svg';
import ExitIcon from '../assets/exit.svg';
import SendArrowIcon from './SendArrowIcon';
import SourceIcon from '../assets/source.svg';
import DocumentationDark from '../assets/documentation-dark.svg';
import ToolIcon from '../assets/tool.svg';
import {
  addAttachment,
  removeAttachment,
  selectAttachments,
  updateAttachment,
  reorderAttachments,
} from '../upload/uploadSlice';

import { ActiveState } from '../models/misc';
import {
  selectSelectedDocs,
  selectToken,
} from '../preferences/preferenceSlice';
import Upload from '../upload/Upload';
import { getOS, isTouchDevice } from '../utils/browserUtils';
import SourcesPopup from './SourcesPopup';
import ToolsPopup from './ToolsPopup';
import { handleAbort } from '../conversation/conversationSlice';

const generateId = (): string =>
  `${Date.now()}-${Math.random().toString(36).substring(2)}`;

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
  const [value, setValue] = useState('');
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const sourceButtonRef = useRef<HTMLButtonElement>(null);
  const toolButtonRef = useRef<HTMLButtonElement>(null);
  const [isSourcesPopupOpen, setIsSourcesPopupOpen] = useState(false);
  const [isToolsPopupOpen, setIsToolsPopupOpen] = useState(false);
  const [uploadModalState, setUploadModalState] =
    useState<ActiveState>('INACTIVE');
  const [handleDragActive, setHandleDragActive] = useState<boolean>(false);

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
        setIsSourcesPopupOpen((s) => !s);
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [browserOS]);

  const uploadFiles = useCallback(
    (files: File[]) => {
      if (!files || files.length === 0) return;

      const apiHost = import.meta.env.VITE_API_HOST;

      if (files.length > 1) {
        const formData = new FormData();
        const indexToUiId: Record<number, string> = {};

        files.forEach((file, i) => {
          formData.append('file', file);
          const uiId = generateId();
          indexToUiId[i] = uiId;
          dispatch(
            addAttachment({
              id: uiId,
              fileName: file.name,
              progress: 0,
              status: 'uploading' as const,
              taskId: '',
            }),
          );
        });

        const xhr = new XMLHttpRequest();

        xhr.upload.addEventListener('progress', (event) => {
          if (event.lengthComputable) {
            const progress = Math.round((event.loaded / event.total) * 100);
            Object.values(indexToUiId).forEach((uiId) =>
              dispatch(
                updateAttachment({
                  id: uiId,
                  updates: { progress },
                }),
              ),
            );
          }
        });

        xhr.onload = () => {
          const status = xhr.status;
          if (status === 200) {
            try {
              const response = JSON.parse(xhr.responseText);

              if (Array.isArray(response?.tasks)) {
                const tasks = response.tasks as Array<{
                  task_id?: string;
                  filename?: string;
                  attachment_id?: string;
                  path?: string;
                }>;

                tasks.forEach((t, idx) => {
                  const uiId = indexToUiId[idx];
                  if (!uiId) return;
                  if (t?.task_id) {
                    dispatch(
                      updateAttachment({
                        id: uiId,
                        updates: {
                          taskId: t.task_id,
                          status: 'processing',
                          progress: 10,
                        },
                      }),
                    );
                  } else {
                    dispatch(
                      updateAttachment({
                        id: uiId,
                        updates: { status: 'failed' },
                      }),
                    );
                  }
                });

                if (tasks.length < files.length) {
                  for (let i = tasks.length; i < files.length; i++) {
                    const uiId = indexToUiId[i];
                    if (uiId) {
                      dispatch(
                        updateAttachment({
                          id: uiId,
                          updates: { status: 'failed' },
                        }),
                      );
                    }
                  }
                }
              } else if (response?.task_id) {
                if (files.length === 1) {
                  const uiId = indexToUiId[0];
                  if (uiId) {
                    dispatch(
                      updateAttachment({
                        id: uiId,
                        updates: {
                          taskId: response.task_id,
                          status: 'processing',
                          progress: 10,
                        },
                      }),
                    );
                  }
                } else {
                  console.warn(
                    'Server returned a single task_id for multiple files. Update backend to return tasks[].',
                  );
                  const firstUi = indexToUiId[0];
                  if (firstUi) {
                    dispatch(
                      updateAttachment({
                        id: firstUi,
                        updates: {
                          taskId: response.task_id,
                          status: 'processing',
                          progress: 10,
                        },
                      }),
                    );
                  }
                  for (let i = 1; i < files.length; i++) {
                    const uiId = indexToUiId[i];
                    if (uiId) {
                      dispatch(
                        updateAttachment({
                          id: uiId,
                          updates: { status: 'failed' },
                        }),
                      );
                    }
                  }
                }
              } else {
                console.error('Unexpected upload response shape', response);
                Object.values(indexToUiId).forEach((id) =>
                  dispatch(
                    updateAttachment({
                      id,
                      updates: { status: 'failed' },
                    }),
                  ),
                );
              }
            } catch (err) {
              console.error(
                'Failed to parse upload response',
                err,
                xhr.responseText,
              );
              Object.values(indexToUiId).forEach((id) =>
                dispatch(
                  updateAttachment({
                    id,
                    updates: { status: 'failed' },
                  }),
                ),
              );
            }
          } else {
            console.error('Upload failed', status, xhr.responseText);
            Object.values(indexToUiId).forEach((id) =>
              dispatch(
                updateAttachment({
                  id,
                  updates: { status: 'failed' },
                }),
              ),
            );
          }
        };

        xhr.onerror = () => {
          console.error('Upload network error');
          Object.values(indexToUiId).forEach((id) =>
            dispatch(
              updateAttachment({
                id,
                updates: { status: 'failed' },
              }),
            ),
          );
        };

        xhr.open('POST', `${apiHost}${endpoints.USER.STORE_ATTACHMENT}`);
        if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);
        xhr.send(formData);
        return;
      }

      // Single-file path: upload each file individually (original repo behavior)
      files.forEach((file) => {
        const formData = new FormData();
        formData.append('file', file);
        const xhr = new XMLHttpRequest();
        const uniqueId = generateId();

        const newAttachment = {
          id: uniqueId,
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
                id: uniqueId,
                updates: { progress },
              }),
            );
          }
        });

        xhr.onload = () => {
          if (xhr.status === 200) {
            try {
              const response = JSON.parse(xhr.responseText);
              if (response.task_id) {
                dispatch(
                  updateAttachment({
                    id: uniqueId,
                    updates: {
                      taskId: response.task_id,
                      status: 'processing',
                      progress: 10,
                    },
                  }),
                );
              } else {
                // If backend returned tasks[] for single-file, handle gracefully:
                if (
                  Array.isArray(response?.tasks) &&
                  response.tasks[0]?.task_id
                ) {
                  dispatch(
                    updateAttachment({
                      id: uniqueId,
                      updates: {
                        taskId: response.tasks[0].task_id,
                        status: 'processing',
                        progress: 10,
                      },
                    }),
                  );
                } else {
                  dispatch(
                    updateAttachment({
                      id: uniqueId,
                      updates: { status: 'failed' },
                    }),
                  );
                }
              }
            } catch (err) {
              console.error(
                'Failed to parse upload response',
                err,
                xhr.responseText,
              );
              dispatch(
                updateAttachment({
                  id: uniqueId,
                  updates: { status: 'failed' },
                }),
              );
            }
          } else {
            dispatch(
              updateAttachment({
                id: uniqueId,
                updates: { status: 'failed' },
              }),
            );
          }
        };

        xhr.onerror = () => {
          dispatch(
            updateAttachment({
              id: uniqueId,
              updates: { status: 'failed' },
            }),
          );
        };

        xhr.open('POST', `${apiHost}${endpoints.USER.STORE_ATTACHMENT}`);
        if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);
        xhr.send(formData);
      });
    },
    [dispatch, token],
  );

  const handleFileAttachment = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files || e.target.files.length === 0) return;
    const files = Array.from(e.target.files);
    uploadFiles(files);
    // clear input so same file can be selected again
    e.target.value = '';
  };

  // Drag & drop via react-dropzone
  const onDrop = useCallback(
    (acceptedFiles: File[]) => {
      uploadFiles(acceptedFiles);
      setHandleDragActive(false);
    },
    [uploadFiles],
  );

  const { getRootProps, getInputProps } = useDropzone({
    onDrop,
    noClick: true,
    noKeyboard: true,
    multiple: true,
    onDragEnter: () => {
      setHandleDragActive(true);
    },
    onDragLeave: () => {
      setHandleDragActive(false);
    },
    maxSize: 25000000,
    accept: {
      'application/pdf': ['.pdf'],
      'text/plain': ['.txt'],
      'text/x-rst': ['.rst'],
      'text/x-markdown': ['.md'],
      'application/zip': ['.zip'],
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document':
        ['.docx'],
      'application/json': ['.json'],
      'text/csv': ['.csv'],
      'text/html': ['.html'],
      'application/epub+zip': ['.epub'],
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': [
        '.xlsx',
      ],
      'application/vnd.openxmlformats-officedocument.presentationml.presentation':
        ['.pptx'],
      'image/png': ['.png'],
      'image/jpeg': ['.jpeg'],
      'image/jpg': ['.jpg'],
    },
  });

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
                  id: attachment.id,
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
                  id: attachment.id,
                  updates: { status: 'failed' },
                }),
              );
            } else if (data.status === 'PROGRESS' && data.result?.current) {
              dispatch(
                updateAttachment({
                  id: attachment.id,
                  updates: { progress: data.result.current },
                }),
              );
            }
          })
          .catch(() => {
            dispatch(
              updateAttachment({
                id: attachment.id,
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

  const handleInput = useCallback(() => {
    if (inputRef.current) {
      if (window.innerWidth < 350) inputRef.current.style.height = 'auto';
      else inputRef.current.style.height = '64px';
      inputRef.current.style.height = `${Math.min(
        inputRef.current.scrollHeight,
        96,
      )}px`;
    }
  }, []);

  const isMountedRef = useRef(true);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (autoFocus) inputRef.current?.focus();
    handleInput();
  }, [autoFocus, handleInput]);

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setValue(e.target.value);
    handleInput();
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
      handleInput();
    }
  };

  const handlePaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const clipboardItems = e.clipboardData?.items;
    const files: File[] = [];

    if (!clipboardItems) return;

    for (let i = 0; i < clipboardItems.length; i++) {
      const item = clipboardItems[i];

      if (item.kind === 'file') {
        const file = item.getAsFile();
        if (file) {
          files.push(file);
        }
      }
    }

    if (files.length > 0) {
      // Prevent weird binary stuff from being pasted as text
      e.preventDefault();
      uploadFiles(files);
    }
  };

  const handlePostDocumentSelect = (doc: any) => {
    console.log('Selected document:', doc);
  };

  const handleSubmit = () => {
    if (value.trim() && !loading) {
      onSubmit(value);
      setValue('');
      // Refocus input after submission if autoFocus is enabled
      if (autoFocus) {
        setTimeout(() => {
          if (isMountedRef.current) {
            inputRef.current?.focus();
          }
        }, 0);
      }
    }
  };

  const handleCancel = () => {
    handleAbort();
  };

  const [draggingId, setDraggingId] = useState<string | null>(null);

  const findIndexById = (id: string) =>
    attachments.findIndex((a) => a.id === id);

  const handleDragStart = (e: React.DragEvent, id: string) => {
    setDraggingId(id);
    try {
      e.dataTransfer.setData('text/plain', id);
      e.dataTransfer.effectAllowed = 'move';
    } catch (err) {
      // ignore
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  };

  const handleDropOn = (e: React.DragEvent, targetId: string) => {
    e.preventDefault();
    const sourceId = e.dataTransfer.getData('text/plain');
    if (!sourceId || sourceId === targetId) return;

    const sourceIndex = findIndexById(sourceId);
    const destIndex = findIndexById(targetId);
    if (sourceIndex === -1 || destIndex === -1) return;

    dispatch(reorderAttachments({ sourceIndex, destinationIndex: destIndex }));
    setDraggingId(null);
  };

  return (
    <div {...getRootProps()} className="flex w-full flex-col">
      {/* react-dropzone input (for drag/drop) */}
      <input {...getInputProps()} />

      <div className="border-dark-gray bg-lotion dark:border-grey relative flex w-full flex-col rounded-[23px] border dark:bg-transparent">
        <div className="flex flex-wrap gap-1.5 px-2 py-2 sm:gap-2 sm:px-3">
          {attachments.map((attachment) => {
            return (
              <div
                key={attachment.id}
                draggable={true}
                onDragStart={(e) => handleDragStart(e, attachment.id)}
                onDragOver={handleDragOver}
                onDrop={(e) => handleDropOn(e, attachment.id)}
                className={`group dark:text-bright-gray relative flex items-center rounded-xl bg-[#EFF3F4] px-2 py-1 text-[12px] text-[#5D5D5D] sm:px-3 sm:py-1.5 sm:text-[14px] dark:bg-[#393B3D] ${
                  attachment.status !== 'completed'
                    ? 'opacity-70'
                    : 'opacity-100'
                } ${
                  draggingId === attachment.id
                    ? 'ring-dashed opacity-60 ring-2 ring-purple-200'
                    : ''
                }`}
                title={attachment.fileName}
              >
                <div className="bg-purple-30 mr-2 flex h-8 w-8 items-center justify-center rounded-md p-1">
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
                    dispatch(removeAttachment(attachment.id));
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
            );
          })}
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
            className="inputbox-style no-scrollbar bg-lotion dark:text-bright-gray dark:placeholder:text-bright-gray/50 w-full overflow-x-hidden overflow-y-auto rounded-t-[23px] px-2 text-base leading-tight whitespace-pre-wrap opacity-100 placeholder:text-gray-500 focus:outline-hidden sm:px-3 dark:bg-transparent"
            onInput={handleInput}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            aria-label={t('inputPlaceholder')}
          />
        </div>

        <div className="flex items-center px-2 pb-1.5 sm:px-3 sm:pb-2">
          <div className="flex grow flex-wrap gap-1 sm:gap-2">
            {showSourceButton && (
              <button
                ref={sourceButtonRef}
                className="xs:px-3 xs:py-1.5 dark:border-purple-taupe flex max-w-[130px] items-center rounded-[32px] border border-[#AAAAAA] px-2 py-1 transition-colors hover:bg-gray-100 sm:max-w-[150px] dark:hover:bg-[#2C2E3C]"
                onClick={() => setIsSourcesPopupOpen(!isSourcesPopupOpen)}
                title={
                  selectedDocs && selectedDocs.length > 0
                    ? selectedDocs.map((doc) => doc.name).join(', ')
                    : t('conversation.sources.title')
                }
              >
                <img
                  src={SourceIcon}
                  alt="Sources"
                  className="mr-1 h-3.5 w-3.5 shrink-0 sm:mr-1.5 sm:h-4"
                />
                <span className="xs:text-[12px] dark:text-bright-gray truncate overflow-hidden text-[10px] font-medium text-[#5D5D5D] sm:text-[14px]">
                  {selectedDocs && selectedDocs.length > 0
                    ? selectedDocs.length === 1
                      ? selectedDocs[0].name
                      : `${selectedDocs.length} sources selected`
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
                multiple
                onChange={handleFileAttachment}
              />
            </label>
            {/* Additional badges can be added here in the future */}
          </div>

          {loading ? (
            <button
              onClick={handleCancel}
              aria-label={t('cancel')}
              className={`ml-auto flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[#7F54D6] text-white sm:h-9 sm:w-9`}
              disabled={!loading}
            >
              <div className="flex h-3 w-3 items-center justify-center rounded-[3px] bg-white sm:h-3.5 sm:w-3.5" />
            </button>
          ) : (
            <button
              onClick={handleSubmit}
              aria-label={t('send')}
              className={`ml-auto flex h-7 w-7 shrink-0 items-center justify-center rounded-full transition-colors duration-300 ease-in-out sm:h-9 sm:w-9 ${
                value.trim() && !loading
                  ? 'bg-purple-30 text-white'
                  : 'bg-[#EDEDED] text-[#959595] dark:bg-[#37383D] dark:text-[#77787D]'
              }`}
              disabled={!value.trim() || loading}
            >
              <SendArrowIcon
                className="mx-auto my-auto block h-3.5 w-3.5 sm:h-4 sm:w-4"
                aria-label={t('send')}
                role="img"
              />
            </button>
          )}
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

      {handleDragActive &&
        createPortal(
          <div className="dark:bg-gray-alpha/50 pointer-events-none fixed top-0 left-0 z-50 flex size-full flex-col items-center justify-center bg-white/85">
            <img className="filter dark:invert" src={DragFileUpload} />
            <span className="text-outer-space dark:text-silver px-2 text-2xl font-bold">
              {t('modals.uploadDoc.drag.title')}
            </span>
            <span className="text-s text-outer-space dark:text-silver w-48 p-2 text-center">
              {t('modals.uploadDoc.drag.description')}
            </span>
          </div>,
          document.body,
        )}
    </div>
  );
}
