import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDarkTheme } from '../hooks';
import { useSelector } from 'react-redux';
import userService from '../api/services/userService';
import endpoints from '../api/endpoints';
import PaperPlane from '../assets/paper_plane.svg';
import SourceIcon from '../assets/source.svg';
import ToolIcon from '../assets/tool.svg';
import SpinnerDark from '../assets/spinner-dark.svg';
import Spinner from '../assets/spinner.svg';
import SourcesPopup from './SourcesPopup';
import ToolsPopup from './ToolsPopup';
import { selectSelectedDocs, selectToken } from '../preferences/preferenceSlice';
import { ActiveState } from '../models/misc';
import Upload from '../upload/Upload';
import ClipIcon from '../assets/clip.svg';


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
  const [uploads, setUploads] = useState<UploadState[]>([]);

  const selectedDocs = useSelector(selectSelectedDocs);
  const token = useSelector(selectToken);

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
      status: 'uploading'
    };
    
    setUploads(prev => [...prev, uploadState]);
    const uploadIndex = uploads.length;
    
    xhr.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable) {
        const progress = Math.round((event.loaded / event.total) * 100);
        setUploads(prev => prev.map((upload, index) => 
          index === uploadIndex 
            ? { ...upload, progress }
            : upload
        ));
      }
    });
    
    xhr.onload = () => {
      if (xhr.status === 200) {
        const response = JSON.parse(xhr.responseText);
        console.log('File uploaded successfully:', response);
        
        if (response.task_id) {
          setUploads(prev => prev.map((upload, index) => 
            index === uploadIndex 
              ? { ...upload, taskId: response.task_id, status: 'processing' }
              : upload
          ));
        }
      } else {
        setUploads(prev => prev.map((upload, index) => 
          index === uploadIndex 
            ? { ...upload, status: 'failed' }
            : upload
        ));
        console.error('Error uploading file:', xhr.responseText);
      }
    };
    
    xhr.onerror = () => {
      setUploads(prev => prev.map((upload, index) => 
        index === uploadIndex 
          ? { ...upload, status: 'failed' }
          : upload
      ));
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
      const processingUploads = uploads.filter(upload => 
        upload.status === 'processing' && upload.taskId
      );
      
      processingUploads.forEach(upload => {
        userService
          .getTaskStatus(upload.taskId, null)
          .then((data) => data.json())
          .then((data) => {
            console.log('Task status:', data);
            
            setUploads(prev => prev.map(u => {
              if (u.taskId !== upload.taskId) return u;
              
              if (data.status === 'SUCCESS') {
                return {
                  ...u,
                  status: 'completed',
                  progress: 100,
                  attachment_id: data.result?.attachment_id,
                  token_count: data.result?.token_count
                };
              } else if (data.status === 'FAILURE') {
                return { ...u, status: 'failed' };
              } else if (data.status === 'PROGRESS' && data.result?.current) {
                return { ...u, progress: data.result.current };
              }
              return u;
            }));
            
            if (data.status !== 'SUCCESS' && data.status !== 'FAILURE') {
              const timeoutId = window.setTimeout(() => checkTaskStatus(), 2000);
              timeoutIds.push(timeoutId);
            }
          })
          .catch((error) => {
            console.error('Error checking task status:', error);
            setUploads(prev => prev.map(u => 
              u.taskId === upload.taskId 
                ? { ...u, status: 'failed' }
                : u
            ));
          });
      });
    };
    
    if (uploads.some(upload => upload.status === 'processing')) {
      const timeoutId = window.setTimeout(checkTaskStatus, 2000);
      timeoutIds.push(timeoutId);
    }
    
    return () => {
      timeoutIds.forEach(id => clearTimeout(id));
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
      onSubmit();
      if (inputRef.current) {
        inputRef.current.value = '';
        handleInput();
      }
    }
  };

  const handlePostDocumentSelect = (doc: any) => {
    console.log('Selected document:', doc);
  };

  const renderUploadStatus = () => {
    const activeUploads = uploads.filter(u => 
      u.status === 'uploading' || u.status === 'processing'
    );
    
    if (activeUploads.length === 0) {
      return 'Attach';
    }
    
    return `Uploading ${activeUploads.length} file(s)`;
  };

  return (
    <div className="flex flex-col w-full mx-2">
      <div className="flex flex-col w-full rounded-[23px] border dark:border-grey border-dark-gray bg-lotion dark:bg-transparent relative">
        <div className="flex flex-wrap gap-2 px-6 pt-3 pb-0">
          {uploads.map((upload, index) => (
            <div 
              key={index}
              className="flex items-center px-3 py-1.5 rounded-[32px] border border-[#AAAAAA] dark:border-purple-taupe bg-white dark:bg-[#1F2028] text-[14px] text-[#5D5D5D] dark:text-bright-gray"
            >
              <span className="font-medium truncate max-w-[150px]">{upload.fileName}</span>
              
              {upload.status === 'completed' && (
                <span className="ml-2 text-green-500">✓</span>
              )}
              
              {upload.status === 'failed' && (
                <span className="ml-2 text-red-500">✗</span>
              )}
              
              {(upload.status === 'uploading' || upload.status === 'processing') && (
                <div className="ml-2 w-4 h-4 relative">
                  <svg className="w-4 h-4" viewBox="0 0 24 24">
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
            className="inputbox-style w-full overflow-y-auto overflow-x-hidden whitespace-pre-wrap rounded-t-[23px] bg-lotion dark:bg-transparent py-5 text-base leading-tight opacity-100 focus:outline-none dark:text-bright-gray dark:placeholder-bright-gray dark:placeholder-opacity-50 px-6 no-scrollbar"
            onInput={handleInput}
            onKeyDown={handleKeyDown}
            aria-label={t('inputPlaceholder')}
          />
        </div>

        <div className="flex flex-wrap items-center gap-2 px-4 py-2">
          <div className="flex-grow flex flex-wrap gap-2">
            <button
              ref={sourceButtonRef}
              className="flex items-center px-3 py-1.5 rounded-[32px] border border-[#AAAAAA] dark:border-purple-taupe hover:bg-gray-100 dark:hover:bg-[#2C2E3C] transition-colors max-w-[200px]"
              onClick={() => setIsSourcesPopupOpen(!isSourcesPopupOpen)}
            >
              <img src={SourceIcon} alt="Sources" className="w-4 h-4 mr-1.5 flex-shrink-0" />
              <span className="text-[14px] text-[#5D5D5D] dark:text-bright-gray font-medium truncate overflow-hidden">
                {selectedDocs
                  ? selectedDocs.name
                  : t('conversation.sources.title')}
              </span>
            </button>
            
            <button
              ref={toolButtonRef}
              className="flex items-center px-3 py-1.5 rounded-[32px] border border-[#AAAAAA] dark:border-purple-taupe hover:bg-gray-100 dark:hover:bg-[#2C2E3C] transition-colors max-w-[200px]"
              onClick={() => setIsToolsPopupOpen(!isToolsPopupOpen)}
            >
              <img src={ToolIcon} alt="Tools" className="w-4 h-4 mr-1.5 flex-shrink-0" />
              <span className="text-[14px] text-[#5D5D5D] dark:text-bright-gray font-medium truncate overflow-hidden">
                {t('settings.tools.label')}
              </span>
            </button>
            <label className="flex items-center px-3 py-1.5 rounded-[32px] border border-[#AAAAAA] dark:border-purple-taupe hover:bg-gray-100 dark:hover:bg-[#2C2E3C] transition-colors cursor-pointer">
              <img src={ClipIcon} alt="Attach" className="w-4 h-4 mr-1.5" />
              <span className="text-[14px] text-[#5D5D5D] dark:text-bright-gray font-medium">
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
            onClick={loading ? undefined : onSubmit}
            aria-label={loading ? t('loading') : t('send')}
            className={`flex items-center justify-center p-2.5 rounded-full ${loading ? 'bg-gray-300 dark:bg-gray-600' : 'bg-black dark:bg-white'} ml-auto`}
            disabled={loading}
          >
            {loading ? (
              <img
                src={isDarkTheme ? SpinnerDark : Spinner}
                className="w-4 h-4 animate-spin"
                alt={t('loading')}
              />
            ) : (
              <img
                className={`w-4 h-4 ${isDarkTheme ? 'filter invert' : ''}`}
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
