import { useEffect, useState } from 'react';
import { Helmet } from 'react-helmet';
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

export const SharedConversation = () => {
  const navigate = useNavigate();
  const { identifier } = useParams(); //identifier is a uuid, not conversationId

  const token = useSelector(selectToken);
  const queries = useSelector(selectQueries);
  const title = useSelector(selectTitle);
  const date = useSelector(selectDate);
  const apiKey = useSelector(selectClientAPIKey);
  const status = useSelector(selectStatus);

  const [input, setInput] = useState('');
  const { t } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();

  const [lastQueryReturnedErr, setLastQueryReturnedErr] = useState(false);

  useEffect(() => {
    identifier && dispatch(setIdentifier(identifier));
  }, []);

  useEffect(() => {
    if (queries.length) {
      queries[queries.length - 1].error && setLastQueryReturnedErr(true);
      queries[queries.length - 1].response && setLastQueryReturnedErr(false); //considering a query that initially returned error can later include a response property on retry
    }
  }, [queries[queries.length - 1]]);

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

  const handleQuestionSubmission = () => {
    if (input && status !== 'loading') {
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

  const handleQuestion = ({
    question,
    isRetry = false,
  }: {
    question: string;
    isRetry?: boolean;
  }) => {
    question = question.trim();
    if (question === '') return;
    !isRetry && dispatch(addQuery({ prompt: question })); //dispatch only new queries
    dispatch(fetchSharedAnswer({ question }));
  };
  useEffect(() => {
    fetchQueries();
  }, []);

  return (
    <>
      <Helmet>
        <title>{`DocsGPT | ${title}`}</title>
        <meta name="description" content="Shared conversations with DocsGPT" />
        <meta property="og:title" content={title} />
        <meta
          property="og:description"
          content="Shared conversations with DocsGPT"
        />
        <meta name="twitter:card" content="summary_large_image" />
        <meta name="twitter:title" content={title} />
        <meta
          name="twitter:description"
          content="Shared conversations with DocsGPT"
        />
      </Helmet>
      <div className="flex h-full flex-col items-center justify-between gap-2 overflow-y-hidden dark:bg-raisin-black ">
        <div className="border-b p-2 dark:border-b-silver w-full md:w-9/12 lg:w-8/12 xl:w-8/12 2xl:w-6/12 max-w-[1200px]">
          <h1 className="font-semi-bold text-4xl text-chinese-black dark:text-chinese-silver">
            {title}
          </h1>
          <h2 className="font-semi-bold text-base text-chinese-black dark:text-chinese-silver">
            {t('sharedConv.subtitle')}{' '}
            <a href="/" className="text-[#007DFF]">
              DocsGPT
            </a>
          </h2>
          <h2 className="font-semi-bold text-base text-chinese-black dark:text-chinese-silver">
            {date}
          </h2>
        </div>
        <ConversationMessages
          handleQuestion={handleQuestion}
          handleQuestionSubmission={handleQuestionSubmission}
          queries={queries}
          status={status}
        />
        <div className="flex flex-col items-center gap-4 pb-2 w-full md:w-9/12 lg:w-8/12 xl:w-8/12 2xl:w-6/12 max-w-[1200px]">
          {apiKey ? (
            <MessageInput
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onSubmit={() => handleQuestionSubmission()}
              loading={status === 'loading'}
            />
          ) : (
            <button
              onClick={() => navigate('/')}
              className="w-fit rounded-full bg-purple-30 py-3 px-5 text-white shadow-xl transition-colors duration-200 hover:bg-violets-are-blue mb-14 sm:mb-0"
            >
              {t('sharedConv.button')}
            </button>
          )}

          <p className="text-gray-4000 hidden w-[100vw] self-center bg-transparent py-2 text-center text-xs dark:text-sonic-silver md:inline md:w-full">
            {t('sharedConv.meta')}
          </p>
        </div>
      </div>
    </>
  );
};
