import { useEffect, useRef,useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDarkTheme } from '../hooks';
import { useSelector, useDispatch } from 'react-redux';
import userService from '../api/services/userService';
import endpoints from '../api/endpoints';
import { getOS, isTouchDevice } from '../utils/browserUtils';
import PaperPlane from '../assets/paper_plane.svg';
import SourceIcon from '../assets/source.svg';
import ToolIcon from '../assets/tool.svg';
import SpinnerDark from '../assets/spinner-dark.svg';
import Spinner from '../assets/spinner.svg';
import ExitIcon from '../assets/exit.svg';
import AlertIcon from '../assets/alert.svg';
import SourcesPopup from './SourcesPopup';
import ToolsPopup from './ToolsPopup';
import { selectSelectedDocs, selectToken } from '../preferences/preferenceSlice';
import { ActiveState } from '../models/misc';
import Upload from '../upload/Upload';
import ClipIcon from '../assets/clip.svg';
import { 
  addAttachment, 
  updateAttachment, 
  removeAttachment,
  selectAttachments 
} from '../conversation/conversationSlice';


interface MessageInputProps {
  value: string;
  onChange: (e: React.ChangeEvent<HTMLTextAreaElement>) => void;
  onSubmit: () => void;
  loading: boolean;
}

interface UploadState {
  taskId: string;
  fileName: string;
  progress: number;
  attachment_id?: string;
  token_count?: number;
  status: 'uploading' | 'processing' | 'completed' | 'failed';
}

export default function MessageInput({
  value,
  onChange,
  onSubmit,
  loading,
}: MessageInputProps) {
  const { t } = useTranslation();
  const [isDarkTheme] = useDarkTheme();
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const sourceButtonRef = useRef<HTMLButtonElement>(null);
  const toolButtonRef = useRef<HTMLButtonElement>(null);
  const [isSourcesPopupOpen, setIsSourcesPopupOpen] = useState(false);
  const [isToolsPopupOpen, setIsToolsPopupOpen] = useState(false);
  const [uploadModalState, setUploadModalState] = useState<ActiveState>('INACTIVE');

  const selectedDocs = useSelector(selectSelectedDocs);
  const token = useSelector(selectToken);
  const attachments = useSelector(selectAttachments);
  
  const dispatch = useDispatch();

  const browserOS = getOS();
  const isTouch = isTouchDevice();

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (
        ((browserOS === 'win' || browserOS === 'linux') && event.ctrlKey && event.key === 'k') ||
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
        dispatch(updateAttachment({ 
          taskId: newAttachment.taskId, 
          updates: { progress } 
        }));
      }
    });

    xhr.onload = () => {
      if (xhr.status === 200) {
        const response = JSON.parse(xhr.responseText);
        if (response.task_id) {
          dispatch(updateAttachment({
            taskId: newAttachment.taskId,
            updates: {
              taskId: response.task_id,
              status: 'processing',
              progress: 10
            }
          }));
        }
      } else {
        dispatch(updateAttachment({
          taskId: newAttachment.taskId,
          updates: { status: 'failed' }
        }));
      }
    };

    xhr.onerror = () => {
      dispatch(updateAttachment({
        taskId: newAttachment.taskId,
        updates: { status: 'failed' }
      }));
    };

    xhr.open('POST', `${apiHost}${endpoints.USER.STORE_ATTACHMENT}`);
    xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    xhr.send(formData);
    e.target.value = '';
  };

  useEffect(() => {
    const checkTaskStatus = () => {
      const processingAttachments = attachments.filter(att => 
        att.status === 'processing' && att.taskId
      );

      processingAttachments.forEach(attachment => {
        userService
          .getTaskStatus(attachment.taskId!, null)
          .then((data) => data.json())
          .then((data) => {
            if (data.status === 'SUCCESS') {
              dispatch(updateAttachment({
                taskId: attachment.taskId!,
                updates: {
                  status: 'completed',
                  progress: 100,
                  id: data.result?.attachment_id,
                  token_count: data.result?.token_count
                }
              }));
            } else if (data.status === 'FAILURE') {
              dispatch(updateAttachment({
                taskId: attachment.taskId!,
                updates: { status: 'failed' }
              }));
            } else if (data.status === 'PROGRESS' && data.result?.current) {
              dispatch(updateAttachment({
                taskId: attachment.taskId!,
                updates: { progress: data.result.current }
              }));
            }
          })
          .catch(() => {
            dispatch(updateAttachment({
              taskId: attachment.taskId!,
              updates: { status: 'failed' }
            }));
          });
      });
    };

    const interval = setInterval(() => {
      if (attachments.some(att => att.status === 'processing')) {
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
    onSubmit();
  };
  return (
    <div className="flex flex-col w-full mx-2">
      <div className="flex flex-col w-full rounded-[23px] border dark:border-grey border-dark-gray bg-lotion dark:bg-transparent relative">
        <div className="flex flex-wrap gap-1.5 sm:gap-2 px-4 sm:px-6 pt-3 pb-0">
          {attachments.map((attachment, index) => (
            <div
              key={index}
              className={`flex items-center px-2 sm:px-3 py-1 sm:py-1.5 rounded-[32px] border border-[#AAAAAA] dark:border-purple-taupe bg-white dark:bg-[#1F2028] text-[12px] sm:text-[14px] text-[#5D5D5D] dark:text-bright-gray group relative ${
                attachment.status !== 'completed' ? 'opacity-70' : 'opacity-100'
              }`}
              title={attachment.fileName}
            >
              <span className="font-medium truncate max-w-[120px] sm:max-w-[150px]">{attachment.fileName}</span>

              {attachment.status === 'completed' && (
                <button 
                  className="absolute right-2 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity bg-white dark:bg-[#1F2028] rounded-full p-1 hover:bg-white/95 dark:hover:bg-[#1F2028]/95"
                  onClick={() => {
                    if (attachment.id) {
                      dispatch(removeAttachment(attachment.id));
                    }
                  }}
                  aria-label="Remove attachment"
                >
                  <img 
                    src={ExitIcon} 
                    alt="Remove" 
                    className="w-2.5 h-2.5 filter dark:invert" 
                  />
                </button>
              )}
            
              {attachment.status === 'failed' && (
                <img 
                  src={AlertIcon} 
                  alt="Upload failed" 
                  className="ml-2 w-3.5 h-3.5" 
                  title="Upload failed"
                />
              )}
            
              {(attachment.status === 'uploading' || attachment.status === 'processing') && (
                <div className="ml-2 w-4 h-4 relative">
                  <svg className="w-4 h-4" viewBox="0 0 24 24">
                    {/* Background circle */}
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
                      strokeDashoffset={62.83 * (1 - attachment.progress / 100)}
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
            className="inputbox-style w-full overflow-y-auto overflow-x-hidden whitespace-pre-wrap rounded-t-[23px] bg-lotion dark:bg-transparent py-3 sm:py-5 text-base leading-tight opacity-100 focus:outline-none dark:text-bright-gray dark:placeholder-bright-gray dark:placeholder-opacity-50 px-4 sm:px-6 no-scrollbar"
            onInput={handleInput}
            onKeyDown={handleKeyDown}
            aria-label={t('inputPlaceholder')}
          />
        </div>

        <div className="flex items-center px-3 sm:px-4 py-1.5 sm:py-2">
          <div className="flex-grow flex flex-wrap gap-1 sm:gap-2">
            <button
              ref={sourceButtonRef}
              className="flex items-center px-2 xs:px-3 py-1 xs:py-1.5 rounded-[32px] border border-[#AAAAAA] dark:border-purple-taupe hover:bg-gray-100 dark:hover:bg-[#2C2E3C] transition-colors max-w-[130px] sm:max-w-[150px]"
              onClick={() => setIsSourcesPopupOpen(!isSourcesPopupOpen)}
              title={selectedDocs ? selectedDocs.name : t('conversation.sources.title')}
            >
              <img src={SourceIcon} alt="Sources" className="w-3.5 h-3.5 sm:h-4 mr-1 sm:mr-1.5 flex-shrink-0" />
              <span className="text-[10px] xs:text-[12px] sm:text-[14px] text-[#5D5D5D] dark:text-bright-gray font-medium truncate overflow-hidden">
                {selectedDocs
                  ? selectedDocs.name
                  : t('conversation.sources.title')}
              </span>
              {!isTouch && (
                <span className="hidden sm:inline-block ml-1 text-[10px] text-gray-500 dark:text-gray-400">
                  {browserOS === 'mac' ? '(⌘K)' : '(ctrl+K)'}
                </span>
              )}
            </button>

            <button
              ref={toolButtonRef}
              className="flex items-center px-2 xs:px-3 py-1 xs:py-1.5 rounded-[32px] border border-[#AAAAAA] dark:border-purple-taupe hover:bg-gray-100 dark:hover:bg-[#2C2E3C] transition-colors max-w-[130px] xs:max-w-[150px]"
              onClick={() => setIsToolsPopupOpen(!isToolsPopupOpen)}
            >
              <img src={ToolIcon} alt="Tools" className="w-3.5 sm:w-4 h-3.5 sm:h-4 mr-1 sm:mr-1.5 flex-shrink-0" />
              <span className="text-[10px] xs:text-[12px] sm:text-[14px] text-[#5D5D5D] dark:text-bright-gray font-medium truncate overflow-hidden">
                {t('settings.tools.label')}
              </span>
            </button>
            <label className="flex items-center px-2 xs:px-3 py-1 xs:py-1.5 rounded-[32px] border border-[#AAAAAA] dark:border-purple-taupe hover:bg-gray-100 dark:hover:bg-[#2C2E3C] transition-colors cursor-pointer">
              <img src={ClipIcon} alt="Attach" className="w-3.5 sm:w-4 h-3.5 sm:h-4 mr-1 sm:mr-1.5" />
              <span className="text-[10px] xs:text-[12px] sm:text-[14px] text-[#5D5D5D] dark:text-bright-gray font-medium">
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
            className={`flex items-center justify-center p-2 sm:p-2.5 rounded-full ${loading ? 'bg-gray-300 dark:bg-gray-600' : 'bg-black dark:bg-white'} ml-auto flex-shrink-0`}
            disabled={loading}
          >
            {loading ? (
              <img
                src={isDarkTheme ? SpinnerDark : Spinner}
                className="w-3.5 sm:w-4 h-3.5 sm:h-4 animate-spin"
                alt={t('loading')}
              />
            ) : (
              <img
                className={`w-3.5 sm:w-4 h-3.5 sm:h-4 ${isDarkTheme ? 'filter invert' : ''}`}
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
