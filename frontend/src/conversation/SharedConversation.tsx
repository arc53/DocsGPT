import { Fragment, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';
import { useDarkTheme } from '../hooks';

import conversationService from '../api/services/conversationService';
import ConversationMessages from './ConversationMessages';
import Send from '../assets/send.svg';
import SendDark from '../assets/send_dark.svg';
import Spinner from '../assets/spinner.svg';
import SpinnerDark from '../assets/spinner-dark.svg';
import {
  setClientApiKey,
  addQuery,
  fetchSharedAnswer,
} from './sharedConversationSlice';
import { setIdentifier, setFetchedData } from './sharedConversationSlice';

import { useDispatch } from 'react-redux';
import { AppDispatch } from '../store';

import {
  selectDate,
  selectTitle,
  selectQueries,
  selectClientAPIKey,
  selectStatus,
} from './sharedConversationSlice';
import { useSelector } from 'react-redux';
import { Helmet } from 'react-helmet';

export const SharedConversation = () => {
  const navigate = useNavigate();
  const { identifier } = useParams(); //identifier is a uuid, not conversationId
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const [isDarkTheme] = useDarkTheme();

  const queries = useSelector(selectQueries);
  const title = useSelector(selectTitle);
  const date = useSelector(selectDate);
  const apiKey = useSelector(selectClientAPIKey);
  const status = useSelector(selectStatus);
  const { t } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();

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
    identifier && dispatch(setIdentifier(identifier));
    fetchQueries();
  }, []);

  const fetchQueries = () => {
    identifier &&
      conversationService
        .getSharedConversation(identifier || '')
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
                date: data.date,
                identifier,
              }),
            );
            data.api_key && dispatch(setClientApiKey(data.api_key));
          }
        });
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
    !isRetry && dispatch(addQuery({ prompt: question }));
    dispatch(fetchSharedAnswer({ question }));
  };

  const handleQuestionSubmission = (
    updatedQuestion?: string,
    updated?: boolean,
    indx?: number,
  ) => {
    if (updatedQuestion && status !== 'loading') {
      handleQuestion({ question: updatedQuestion });
    }
  };

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

      <div className="flex h-full flex-col items-center justify-between gap-2 overflow-y-hidden dark:bg-raisin-black">
        {/* Header section */}
        <div className="w-11/12 md:w-10/12 lg:w-6/12 mt-4">
          <div className="mb-2 w-full border-b pb-2 dark:border-b-silver">
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
        </div>

        {/* Conditionally render based on API key */}
        {!apiKey ? (
          <div className="flex flex-col items-center justify-center h-full">
            <button
              onClick={() => navigate('/')}
              className="w-fit rounded-full bg-purple-30 p-4 text-white shadow-xl transition-colors duration-200 hover:bg-purple-taupe mb-14 sm:mb-0"
            >
              {t('sharedConv.button')}
            </button>
            <span className="mb-2 hidden text-xs text-dark-charcoal dark:text-silver sm:inline">
              {t('sharedConv.meta')}
            </span>
          </div>
        ) : (
          <>
            <ConversationMessages
              handleQuestion={handleQuestion}
              handleQuestionSubmission={handleQuestionSubmission}
              queries={queries}
              status={status}
            />

            {/* Add the textarea input here */}
            <div className="flex flex-col items-center self-center rounded-2xl bg-opacity-0 z-3 w-full px-4 md:px-0">
              <div className="w-full md:w-8/12 lg:w-7/12 xl:w-6/12 2xl:w-5/12 max-w-[1200px]">
                <div className="flex w-full items-center rounded-[40px] border dark:border-grey border-dark-gray bg-lotion dark:bg-charleston-green-3">
                  <label htmlFor="message-input" className="sr-only">
                    {t('inputPlaceholder')}
                  </label>
                  <textarea
                    id="message-input"
                    ref={inputRef}
                    tabIndex={1}
                    placeholder={t('inputPlaceholder')}
                    className="inputbox-style w-full overflow-y-auto overflow-x-hidden whitespace-pre-wrap rounded-full bg-lotion dark:bg-charleston-green-3 py-5 text-base leading-tight opacity-100 focus:outline-none dark:text-bright-gray dark:placeholder-bright-gray dark:placeholder-opacity-50 px-6"
                    onInput={handleInput}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        handleQuestionSubmission(inputRef.current?.value);
                        if (inputRef.current) {
                          inputRef.current.value = '';
                          handleInput();
                        }
                      }
                    }}
                    aria-label={t('inputPlaceholder')}
                  />
                  {status === 'loading' ? (
                    <img
                      src={isDarkTheme ? SpinnerDark : Spinner}
                      className="relative right-[38px] bottom-[24px] -mr-[30px] animate-spin cursor-pointer self-end bg-transparent"
                      alt={t('loading')}
                    />
                  ) : (
                    <div className="mx-1 cursor-pointer rounded-full p-3 text-center hover:bg-gray-3000 dark:hover:bg-dark-charcoal">
                      <button
                        onClick={() =>
                          handleQuestionSubmission(inputRef.current?.value)
                        }
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
              </div>
              <p className="text-gray-4000 hidden w-full bg-transparent py-2 text-center text-xs dark:text-sonic-silver md:inline">
                {t('tagline')}
              </p>
            </div>
          </>
        )}
      </div>
    </>
  );
};
