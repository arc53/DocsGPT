import { Fragment, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import ArrowDown from '../assets/arrow-down.svg';
import Send from '../assets/send.svg';
import SendDark from '../assets/send_dark.svg';
import ShareIcon from '../assets/share.svg';
import SpinnerDark from '../assets/spinner-dark.svg';
import Spinner from '../assets/spinner.svg';
import RetryIcon from '../components/RetryIcon';
import Hero from '../Hero';
import { useDarkTheme } from '../hooks';
import { ShareConversationModal } from '../modals/ShareConversationModal';
import { selectConversationId } from '../preferences/preferenceSlice';
import { AppDispatch } from '../store';
import ConversationBubble from './ConversationBubble';
import { handleSendFeedback } from './conversationHandlers';
import { FEEDBACK, Query } from './conversationModels';
import {
  addQuery,
  fetchAnswer,
  selectQueries,
  selectStatus,
  updateQuery,
} from './conversationSlice';

export default function Conversation() {
  const queries = useSelector(selectQueries);
  const status = useSelector(selectStatus);
  const conversationId = useSelector(selectConversationId);
  const dispatch = useDispatch<AppDispatch>();
  const conversationRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const [isDarkTheme] = useDarkTheme();
  const [hasScrolledToLast, setHasScrolledToLast] = useState(true);
  const fetchStream = useRef<any>(null);
  const [eventInterrupt, setEventInterrupt] = useState(false);
  const [lastQueryReturnedErr, setLastQueryReturnedErr] = useState(false);
  const [isShareModalOpen, setShareModalState] = useState<boolean>(false);
  const { t } = useTranslation();

  const handleUserInterruption = () => {
    if (!eventInterrupt && status === 'loading') setEventInterrupt(true);
  };
  useEffect(() => {
    !eventInterrupt && scrollIntoView();
  }, [queries.length, queries[queries.length - 1]]);

  useEffect(() => {
    const element = document.getElementById('inputbox') as HTMLTextAreaElement;
    if (element) {
      element.focus();
    }
  }, []);

  useEffect(() => {
    fetchStream.current && fetchStream.current.abort();
  }, [conversationId]);

  useEffect(() => {
    if (queries.length) {
      queries[queries.length - 1].error && setLastQueryReturnedErr(true);
      queries[queries.length - 1].response && setLastQueryReturnedErr(false); //considering a query that initially returned error can later include a response property on retry
    }
  }, [queries[queries.length - 1]]);

  const scrollIntoView = () => {
    if (!conversationRef?.current || eventInterrupt) return;

    if (status === 'idle' || !queries[queries.length - 1].response) {
      conversationRef.current.scrollTo({
        behavior: 'smooth',
        top: conversationRef.current.scrollHeight,
      });
    } else {
      conversationRef.current.scrollTop = conversationRef.current.scrollHeight;
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
    setEventInterrupt(false);
    !isRetry && dispatch(addQuery({ prompt: question })); //dispatch only new queries
    fetchStream.current = dispatch(fetchAnswer({ question }));
  };

  const handleFeedback = (query: Query, feedback: FEEDBACK, index: number) => {
    const prevFeedback = query.feedback;
    dispatch(updateQuery({ index, query: { feedback } }));
    handleSendFeedback(query.prompt, query.response!, feedback).catch(() =>
      dispatch(updateQuery({ index, query: { feedback: prevFeedback } })),
    );
  };

  const handleQuestionSubmission = () => {
    if (inputRef.current?.value && status !== 'loading') {
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

  const prepResponseView = (query: Query, index: number) => {
    let responseView;
    if (query.response) {
      responseView = (
        <ConversationBubble
          className={`${index === queries.length - 1 ? 'mb-32' : 'mb-7'}`}
          key={`${index}ANSWER`}
          message={query.response}
          type={'ANSWER'}
          sources={query.sources}
          feedback={query.feedback}
          handleFeedback={(feedback: FEEDBACK) =>
            handleFeedback(query, feedback, index)
          }
        ></ConversationBubble>
      );
    } else if (query.error) {
      const retryBtn = (
        <button
          className="flex items-center justify-center gap-3 self-center rounded-full border border-silver py-3 px-5  text-lg text-gray-500 transition-colors delay-100 hover:border-gray-500 disabled:cursor-not-allowed dark:text-bright-gray"
          disabled={status === 'loading'}
          onClick={() => {
            handleQuestion({
              question: queries[queries.length - 1].prompt,
              isRetry: true,
            });
          }}
        >
          <RetryIcon
            fill={isDarkTheme ? 'rgb(236 236 241)' : 'rgb(107 114 120)'}
            stroke={isDarkTheme ? 'rgb(236 236 241)' : 'rgb(107 114 120)'}
          />
          Retry
        </button>
      );
      responseView = (
        <ConversationBubble
          className={`${index === queries.length - 1 ? 'mb-32' : 'mb-7'} `}
          key={`${index}ERROR`}
          message={query.error}
          type="ERROR"
          retryBtn={retryBtn}
        ></ConversationBubble>
      );
    }
    return responseView;
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

  useEffect(() => {
    handleInput();
    window.addEventListener('resize', handleInput);
    return () => {
      window.removeEventListener('resize', handleInput);
    };
  }, []);
  return (
    <div className="flex flex-col gap-1 h-[92%] sm:h-full justify-end">
      {conversationId && (
        <>
          {' '}
          <button
            title="Share"
            onClick={() => {
              setShareModalState(true);
            }}
            className="absolute top-4 right-20 z-20 rounded-full hover:bg-bright-gray dark:hover:bg-[#28292E]"
          >
            <img
              className="m-2 h-5 w-5 filter dark:invert"
              alt="share"
              src={ShareIcon}
            />
          </button>
          {isShareModalOpen && (
            <ShareConversationModal
              close={() => {
                setShareModalState(false);
              }}
              conversationId={conversationId}
            />
          )}
        </>
      )}
      <div
        ref={conversationRef}
        onWheel={handleUserInterruption}
        onTouchMove={handleUserInterruption}
        className="flex justify-center w-full overflow-y-auto h-auto min-h-full"
      >
        {queries.length > 0 && !hasScrolledToLast && (
          <button
            onClick={scrollIntoView}
            aria-label="scroll to bottom"
            className="fixed bottom-40 right-14 z-10 flex h-7 w-7  items-center justify-center rounded-full border-[0.5px] border-gray-alpha bg-gray-100 bg-opacity-50 dark:bg-purple-taupe md:h-9 md:w-9 md:bg-opacity-100 "
          >
            <img
              src={ArrowDown}
              alt="arrow down"
              className="h-4 w-4 opacity-50 md:h-5 md:w-5"
            />
          </button>
        )}

        {queries.length > 0 ? (
          <div className="w-full h-full md:w-8/12">
            {queries.map((query, index) => {
              return (
                <Fragment key={index}>
                  <ConversationBubble
                    className={'mb-1 last:mb-28 md:mb-7 first:mt-40'}
                    key={`${index}QUESTION`}
                    message={query.prompt}
                    type="QUESTION"
                    sources={query.sources}
                  ></ConversationBubble>

                  {prepResponseView(query, index)}
                </Fragment>
              );
            })}
          </div>
        ) : (
          <Hero handleQuestion={handleQuestion} />
        )}
      </div>

      <div className="flex w-11/12 flex-col items-end self-center rounded-2xl bg-opacity-0 pb-1 sm:w-[62%] h-auto">
        <div className="flex w-full items-center rounded-[40px] border border-silver bg-white py-1 dark:bg-raisin-black">
          <textarea
            id="inputbox"
            ref={inputRef}
            tabIndex={1}
            placeholder={t('inputPlaceholder')}
            className={`inputbox-style h-16 w-full overflow-y-auto overflow-x-hidden whitespace-pre-wrap rounded-full bg-white pt-5 pb-[22px] text-base leading-tight opacity-100 focus:outline-none dark:bg-raisin-black dark:text-bright-gray`}
            onInput={handleInput}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleQuestionSubmission();
              }
            }}
          ></textarea>
          {status === 'loading' ? (
            <img
              src={isDarkTheme ? SpinnerDark : Spinner}
              className="relative right-[38px] bottom-[24px] -mr-[30px] animate-spin cursor-pointer self-end bg-transparent"
            ></img>
          ) : (
            <div className="mx-1 cursor-pointer rounded-full p-3 text-center hover:bg-gray-3000 dark:hover:bg-dark-charcoal">
              <img
                className="ml-[4px] h-6 w-6 text-white "
                onClick={handleQuestionSubmission}
                src={isDarkTheme ? SendDark : Send}
              ></img>
            </div>
          )}
        </div>

        <p className="text-gray-595959 hidden w-[100vw] self-center bg-transparent py-2 text-center text-xs dark:text-bright-gray md:inline md:w-full">
          {t('tagline')}
        </p>
      </div>
    </div>
  );
}
