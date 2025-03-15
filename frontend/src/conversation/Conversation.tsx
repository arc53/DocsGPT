import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import { useDropzone } from 'react-dropzone';
import DragFileUpload from '../assets/DragFileUpload.svg';
import newChatIcon from '../assets/openNewChat.svg';
import Send from '../assets/send.svg';
import SendDark from '../assets/send_dark.svg';
import ShareIcon from '../assets/share.svg';
import SpinnerDark from '../assets/spinner-dark.svg';
import Spinner from '../assets/spinner.svg';
import { useDarkTheme, useMediaQuery } from '../hooks';
import { ShareConversationModal } from '../modals/ShareConversationModal';
import { selectConversationId } from '../preferences/preferenceSlice';
import { AppDispatch } from '../store';
import { handleSendFeedback } from './conversationHandlers';
import { FEEDBACK, Query } from './conversationModels';
import {
  addQuery,
  fetchAnswer,
  resendQuery,
  selectQueries,
  selectStatus,
  setConversation,
  updateConversationId,
  updateQuery,
} from './conversationSlice';
import Upload from '../upload/Upload';
import { ActiveState } from '../models/misc';
import ConversationMessages from './ConversationMessages';

export default function Conversation() {
  const queries = useSelector(selectQueries);
  const navigate = useNavigate();
  const status = useSelector(selectStatus);
  const conversationId = useSelector(selectConversationId);
  const dispatch = useDispatch<AppDispatch>();
  const conversationRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const [isDarkTheme] = useDarkTheme();
  const fetchStream = useRef<any>(null);
  const [lastQueryReturnedErr, setLastQueryReturnedErr] = useState(false);
  const [isShareModalOpen, setShareModalState] = useState<boolean>(false);
  const { t } = useTranslation();
  const { isMobile } = useMediaQuery();
  const [uploadModalState, setUploadModalState] =
    useState<ActiveState>('INACTIVE');
  const [files, setFiles] = useState<File[]>([]);
  const [handleDragActive, setHandleDragActive] = useState<boolean>(false);

  const onDrop = useCallback((acceptedFiles: File[]) => {
    setUploadModalState('ACTIVE');
    setFiles(acceptedFiles);
    setHandleDragActive(false);
  }, []);

  const { getRootProps, getInputProps } = useDropzone({
    onDrop,
    noClick: true,
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
    },
  });

  useEffect(() => {
    const element = document.getElementById('inputbox') as HTMLTextAreaElement;
    if (element) {
      element.focus();
    }
  }, []);

  useEffect(() => {
    if (queries.length) {
      queries[queries.length - 1].error && setLastQueryReturnedErr(true);
      queries[queries.length - 1].response && setLastQueryReturnedErr(false); //considering a query that initially returned error can later include a response property on retry
    }
  }, [queries[queries.length - 1]]);

  const handleQuestion = ({
    question,
    isRetry = false,
    updated = null,
    indx = undefined,
  }: {
    question: string;
    isRetry?: boolean;
    updated?: boolean | null;
    indx?: number;
  }) => {
    if (updated === true) {
      !isRetry &&
        dispatch(resendQuery({ index: indx as number, prompt: question })); //dispatch only new queries
      fetchStream.current = dispatch(fetchAnswer({ question, indx }));
    } else {
      question = question.trim();
      if (question === '') return;
      !isRetry && dispatch(addQuery({ prompt: question })); //dispatch only new queries
      fetchStream.current = dispatch(fetchAnswer({ question }));
    }
  };

  const handleFeedback = (query: Query, feedback: FEEDBACK, index: number) => {
    const prevFeedback = query.feedback;
    dispatch(updateQuery({ index, query: { feedback } }));
    handleSendFeedback(
      query.prompt,
      query.response!,
      feedback,
      conversationId as string,
      index,
    ).catch(() =>
      handleSendFeedback(
        query.prompt,
        query.response!,
        feedback,
        conversationId as string,
        index,
      ).catch(() =>
        dispatch(updateQuery({ index, query: { feedback: prevFeedback } })),
      ),
    );
  };

  const handleQuestionSubmission = (
    updatedQuestion?: string,
    updated?: boolean,
    indx?: number,
  ) => {
    if (updated === true) {
      handleQuestion({ question: updatedQuestion as string, updated, indx });
    } else if (inputRef.current?.value && status !== 'loading') {
      if (lastQueryReturnedErr) {
        // update last failed query with new prompt
        dispatch(
          updateQuery({
            index: queries.length - 1,
            query: {
              prompt: inputRef.current.value,
            },
          }),
        );
        handleQuestion({
          question: queries[queries.length - 1].prompt,
          isRetry: true,
        });
      } else {
        handleQuestion({ question: inputRef.current.value });
      }
      inputRef.current.value = '';
      handleInput();
    }
  };
  const resetConversation = () => {
    dispatch(setConversation([]));
    dispatch(
      updateConversationId({
        query: { conversationId: null },
      }),
    );
  };
  const newChat = () => {
    if (queries && queries.length > 0) resetConversation();
  };

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

  return (
    <div className="flex flex-col gap-1 h-full justify-end">
      {conversationId && queries.length > 0 && (
        <div className="absolute top-4 right-20">
          <div className="flex mt-2 items-center gap-4">
            {isMobile && queries.length > 0 && (
              <button
                title="Open New Chat"
                onClick={() => {
                  newChat();
                }}
                className="hover:bg-bright-gray dark:hover:bg-[#28292E] rounded-full p-2"
              >
                <img
                  className="h-5 w-5 filter dark:invert"
                  alt="NewChat"
                  src={newChatIcon}
                />
              </button>
            )}

            <button
              title="Share"
              onClick={() => {
                setShareModalState(true);
              }}
              className="hover:bg-bright-gray dark:hover:bg-[#28292E] rounded-full p-2"
            >
              <img
                className="h-5 w-5 filter dark:invert"
                alt="share"
                src={ShareIcon}
              />
            </button>
          </div>
          {isShareModalOpen && (
            <ShareConversationModal
              close={() => {
                setShareModalState(false);
              }}
              conversationId={conversationId}
            />
          )}
        </div>
      )}

      <ConversationMessages
        handleQuestion={handleQuestion}
        handleQuestionSubmission={handleQuestionSubmission}
        handleFeedback={handleFeedback}
        queries={queries}
        status={status}
      />

      <div className="flex flex-col items-end self-center rounded-2xl bg-opacity-0 z-3 w-[calc(min(742px,92%))] h-auto py-1">
        <div
          {...getRootProps()}
          className="flex w-full items-center rounded-[40px] border dark:border-grey border-dark-gray bg-lotion dark:bg-charleston-green-3"
        >
          <label htmlFor="file-upload" className="sr-only">
            {t('modals.uploadDoc.label')}
          </label>
          <input {...getInputProps()} id="file-upload" />
          <label htmlFor="message-input" className="sr-only">
            {t('inputPlaceholder')}
          </label>
          <textarea
            id="message-input"
            ref={inputRef}
            tabIndex={1}
            placeholder={t('inputPlaceholder')}
            className={`inputbox-style w-full overflow-y-auto overflow-x-hidden whitespace-pre-wrap rounded-full bg-lotion dark:bg-charleston-green-3 py-5 text-base leading-tight opacity-100 focus:outline-none dark:text-bright-gray dark:placeholder-bright-gray dark:placeholder-opacity-50`}
            onInput={handleInput}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleQuestionSubmission();
              }
            }}
            aria-label={t('inputPlaceholder')}
          ></textarea>
          {status === 'loading' ? (
            <img
              src={isDarkTheme ? SpinnerDark : Spinner}
              className="relative right-[38px] bottom-[24px] -mr-[30px] animate-spin cursor-pointer self-end bg-transparent"
              alt={t('loading')}
            />
          ) : (
            <div className="mx-1 cursor-pointer rounded-full p-3 text-center hover:bg-gray-3000 dark:hover:bg-dark-charcoal">
              <button
                onClick={() => handleQuestionSubmission()}
                aria-label={t('send')}
                className="flex items-center justify-center"
              >
                <img
                  className="ml-[4px] h-6 w-6 text-white filter dark:invert-[0.45] invert-[0.35]"
                  src={isDarkTheme ? SendDark : Send}
                  alt={t('send')}
                />
              </button>
            </div>
          )}
        </div>

        <p className="text-gray-4000 hidden w-[100vw] self-center bg-transparent py-2 text-center text-xs dark:text-sonic-silver md:inline md:w-full">
          {t('tagline')}
        </p>
      </div>
      {handleDragActive && (
        <div className="pointer-events-none fixed top-0 left-0 z-30 flex flex-col size-full items-center justify-center bg-opacity-50 bg-white dark:bg-gray-alpha">
          <img className="filter dark:invert" src={DragFileUpload} />
          <span className="px-2 text-2xl font-bold text-outer-space dark:text-silver">
            {t('modals.uploadDoc.drag.title')}
          </span>
          <span className="p-2 text-s w-48 text-center text-outer-space dark:text-silver">
            {t('modals.uploadDoc.drag.description')}
          </span>
        </div>
      )}
      {uploadModalState === 'ACTIVE' && (
        <Upload
          receivedFile={files}
          setModalState={setUploadModalState}
          isOnboarding={false}
          renderTab={'file'}
          close={() => setUploadModalState('INACTIVE')}
        ></Upload>
      )}
    </div>
  );
}
