import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import { useDropzone } from 'react-dropzone';
import DragFileUpload from '../assets/DragFileUpload.svg';
import newChatIcon from '../assets/openNewChat.svg';
import ShareIcon from '../assets/share.svg';
import { useMediaQuery } from '../hooks';
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
import MessageInput from '../components/MessageInput';

export default function Conversation() {
  const queries = useSelector(selectQueries);
  const navigate = useNavigate();
  const status = useSelector(selectStatus);
  const conversationId = useSelector(selectConversationId);
  const dispatch = useDispatch<AppDispatch>();
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const [input, setInput] = useState('');
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
    } else if (input && status !== 'loading') {
      if (lastQueryReturnedErr) {
        // update last failed query with new prompt
        dispatch(
          updateQuery({
            index: queries.length - 1,
            query: {
              prompt: input,
            },
          }),
        );
        handleQuestion({
          question: queries[queries.length - 1].prompt,
          isRetry: true,
        });
      } else {
        handleQuestion({ question: input });
      }
      setInput('');
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

      <div className="flex flex-col items-end self-center rounded-2xl bg-opacity-0 z-3 w-full md:w-6/12 h-auto py-1">
        <div
          {...getRootProps()}
          className="flex w-full items-center rounded-[40px]"
        >
          <label htmlFor="file-upload" className="sr-only">
            {t('modals.uploadDoc.label')}
          </label>
          <input {...getInputProps()} id="file-upload" />
          <MessageInput
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onSubmit={handleQuestionSubmission}
            loading={status === 'loading'}
          />
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
