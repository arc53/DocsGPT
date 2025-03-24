import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDarkTheme } from '../hooks';
import { useSelector } from 'react-redux';
import PaperPlane from '../assets/paper_plane.svg';
import SourceIcon from '../assets/source.svg';
import ToolIcon from '../assets/tool.svg';
import SpinnerDark from '../assets/spinner-dark.svg';
import Spinner from '../assets/spinner.svg';
import SourcesPopup from './SourcesPopup';
import ToolsPopup from './ToolsPopup';
import { selectSelectedDocs } from '../preferences/preferenceSlice';
import { ActiveState } from '../models/misc';
import Upload from '../upload/Upload';
import ClipIcon from '../assets/clip.svg';

interface MessageInputProps {
  value: string;
  onChange: (e: React.ChangeEvent<HTMLTextAreaElement>) => void;
  onSubmit: () => void;
  loading: boolean;
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
  const [uploadModalState, setUploadModalState] =
    useState<ActiveState>('INACTIVE');

  const selectedDocs = useSelector(selectSelectedDocs);

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

  return (
    <div className="flex flex-col w-full mx-2">
      <div className="flex flex-col w-full rounded-[23px] border dark:border-grey border-dark-gray bg-lotion dark:bg-transparent relative">
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
            {/*<button
              className="flex items-center px-3 py-1.5 rounded-[32px] border border-[#AAAAAA] dark:border-purple-taupe hover:bg-gray-100 dark:hover:bg-[#2C2E3C] transition-colors"
              onClick={() => setUploadModalState('ACTIVE')}
            >
              <img src={ClipIcon} alt="Attach" className="w-4 h-4 mr-1.5" />
              <span className="text-[14px] text-[#5D5D5D] dark:text-bright-gray font-medium">
                Attach
              </span>
            </button>*/}

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
