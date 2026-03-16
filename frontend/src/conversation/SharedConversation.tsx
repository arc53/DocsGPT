import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate, useParams } from 'react-router-dom';

import conversationService from '../api/services/conversationService';
import MessageInput from '../components/MessageInput';
import { selectToken } from '../preferences/preferenceSlice';
import { AppDispatch } from '../store';
import { formatDate } from '../utils/dateTimeUtils';
import ConversationMessages from './ConversationMessages';
import {
  addQuery,
  fetchSharedAnswer,
  selectClientAPIKey,
  selectDate,
  selectQueries,
  selectStatus,
  selectTitle,
  setClientApiKey,
  setFetchedData,
  setIdentifier,
  updateQuery,
} from './sharedConversationSlice';
import { selectCompletedAttachments } from '../upload/uploadSlice';
import { Head as DocumentHead } from '../components/Head';

export const SharedConversation = () => {
  const navigate = useNavigate();
  const { identifier } = useParams(); //identifier is a uuid, not conversationId

  const token = useSelector(selectToken);
  const queries = useSelector(selectQueries);
  const title = useSelector(selectTitle);
  const date = useSelector(selectDate);
  const apiKey = useSelector(selectClientAPIKey);
  const status = useSelector(selectStatus);
  const completedAttachments = useSelector(selectCompletedAttachments);

  const { t } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();

  const [lastQueryReturnedErr, setLastQueryReturnedErr] = useState(false);

  useEffect(() => {
    identifier && dispatch(setIdentifier(identifier));
  }, [identifier, dispatch]);

  useEffect(() => {
    if (queries.length) {
      queries[queries.length - 1].error && setLastQueryReturnedErr(true);
      queries[queries.length - 1].response && setLastQueryReturnedErr(false); 
    }
  }, [queries]);

  const fetchQueries = () => {
    identifier &&
      conversationService
        .getSharedConversation(identifier || '', token)
        .then((res) => {
          if (res.status === 404 || res.status === 400)
            navigate('/pagenotfound');
          return res.json();
        })
        .then((data) => {
          if (data.success) {
            dispatch(
              setFetchedData({
                queries: data.queries,
                title: data.title,
                date: formatDate(data.timestamp),
                identifier,
              }),
            );
            data.api_key && dispatch(setClientApiKey(data.api_key));
          }
        });
  };

  const handleQuestionSubmission = (
    question?: string,
    updated?: boolean,
    indx?: number,
    imageBase64?: string,
  ) => {
    // FIXED: Safely checking for either text or image
    if ((question || imageBase64) && status !== 'loading') {
      const trimmedQuestion = (question || '').trim(); // FIXED: Safe fallback to empty string
      
      if (lastQueryReturnedErr) {
        dispatch(
          updateQuery({
            index: queries.length - 1,
            query: {
              prompt: trimmedQuestion,
            },
          }),
        );
        handleQuestion({
          question: queries[queries.length - 1].prompt,
          isRetry: true,
          imageBase64,
        });
      } else {
        handleQuestion({ question: trimmedQuestion, imageBase64 });
      }
    }
  };

  const handleQuestion = ({
    question,
    imageBase64,
    isRetry = false,
  }: {
    question: string;
    imageBase64?: string;
    isRetry?: boolean;
  }) => {
    const promptText = question.trim();
    if (promptText === '' && !imageBase64) return;

    const filesAttached = completedAttachments
      .filter((a) => a.id)
      .map((a) => ({ id: a.id as string, fileName: a.fileName }));

    !isRetry &&
      dispatch(
        addQuery({
          prompt: promptText,
          attachments: filesAttached,
          imageBase64,
        }),
      );

    dispatch(
      fetchSharedAnswer({
        question: promptText,
        imageBase64, 
      }),
    );
  };
  
  useEffect(() => {
    fetchQueries();
  }, []);

  return (
    <>
      <DocumentHead
        title={`DocsGPT | ${title}`}
        description="Shared conversations with DocsGPT"
        ogTitle={title}
        ogDescription="Shared conversations with DocsGPT"
        twitterCard="summary_large_image"
        twitterTitle={title}
        twitterDescription="Shared conversations with DocsGPT"
      />
      <div className="dark:bg-raisin-black flex h-full flex-col items-center justify-between gap-2 overflow-y-hidden">
        <div className="dark:border-b-silver w-full max-w-[1200px] border-b p-2 md:w-9/12 lg:w-8/12 xl:w-8/12 2xl:w-6/12">
          <h1 className="font-semi-bold text-chinese-black dark:text-chinese-silver text-4xl">
            {title}
          </h1>
          <h2 className="font-semi-bold text-chinese-black dark:text-chinese-silver text-base">
            {t('sharedConv.subtitle')}{' '}
            <a href="/" className="text-[#007DFF]">
              DocsGPT
            </a>
          </h2>
          <h2 className="font-semi-bold text-chinese-black dark:text-chinese-silver text-base">
            {date}
          </h2>
        </div>
        <ConversationMessages
          handleQuestion={handleQuestion}
          handleQuestionSubmission={handleQuestionSubmission}
          queries={queries}
          status={status}
        />
        <div className="flex w-full max-w-[1200px] flex-col items-center gap-4 pb-2 md:w-9/12 lg:w-8/12 xl:w-8/12 2xl:w-6/12">
          {apiKey ? (
            <div className="w-full px-2">
              <MessageInput
                onSubmit={({ text, imageBase64 }) => {
                  handleQuestionSubmission(text, false, undefined, imageBase64);
                }}
                loading={status === 'loading'}
                showSourceButton={false}
                showToolButton={false}
              />
            </div>
          ) : (
            <button
              onClick={() => navigate('/')}
              className="bg-purple-30 hover:bg-violets-are-blue mb-14 w-fit rounded-full px-5 py-3 text-white shadow-xl transition-colors duration-200 sm:mb-0"
            >
              {t('sharedConv.button')}
            </button>
          )}

          <p className="text-gray-4000 dark:text-sonic-silver hidden w-screen self-center bg-transparent py-2 text-center text-xs md:inline md:w-full">
            {t('sharedConv.meta')}
          </p>
        </div>
      </div>
    </>
  );
};