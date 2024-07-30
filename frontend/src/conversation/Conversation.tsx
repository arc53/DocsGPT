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
  const endMessageRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLDivElement>(null);
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
    const element = document.getElementById('inputbox') as HTMLInputElement;
    if (element) {
      element.focus();
    }
  }, []);

  useEffect(() => {
    return () => {
      if (status !== 'idle') {
        fetchStream.current && fetchStream.current.abort(); //abort previous stream
      }
    };
  }, [status]);

  useEffect(() => {
    const observerCallback: IntersectionObserverCallback = (entries) => {
      entries.forEach((entry) => {
        setHasScrolledToLast(entry.isIntersecting);
      });
    };

    const observer = new IntersectionObserver(observerCallback, {
      root: null,
      threshold: [1, 0.8],
    });
    if (endMessageRef.current) {
      observer.observe(endMessageRef.current);
    }

    return () => {
      observer.disconnect();
    };
  }, [endMessageRef.current]);

  useEffect(() => {
    if (queries.length) {
      queries[queries.length - 1].error && setLastQueryReturnedErr(true);
      queries[queries.length - 1].response && setLastQueryReturnedErr(false); //considering a query that initially returned error can later include a response property on retry
    }
  }, [queries[queries.length - 1]]);

  const scrollIntoView = () => {
    endMessageRef?.current?.scrollIntoView({
      behavior: 'smooth',
      block: 'start',
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
    if (inputRef.current?.textContent && status !== 'loading') {
      if (lastQueryReturnedErr) {
        // update last failed query with new prompt
        dispatch(
          updateQuery({
            index: queries.length - 1,
            query: {
              prompt: inputRef.current.textContent,
            },
          }),
        );
        handleQuestion({
          question: queries[queries.length - 1].prompt,
          isRetry: true,
        });
      } else {
        handleQuestion({ question: inputRef.current.textContent });
      }
      inputRef.current.textContent = '';
    }
  };

  const prepResponseView = (query: Query, index: number) => {
    let responseView;
    if (query.response) {
      responseView = (
        <ConversationBubble
          ref={endMessageRef}
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
          ref={endMessageRef}
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

  const handlePaste = (e: React.ClipboardEvent) => {
    e.preventDefault();
    const text = e.clipboardData.getData('text/plain');
    inputRef.current && (inputRef.current.innerText = text);
  };

  return (
    <div className="flex h-screen flex-col gap-7 pb-2">
      {conversationId && (
        <>
          <button
            title="Share"
            onClick={() => {
              setShareModalState(true);
            }}
            className="fixed top-4 right-20 z-0 rounded-full hover:bg-bright-gray dark:hover:bg-[#28292E]"
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
        onWheel={handleUserInterruption}
        onTouchMove={handleUserInterruption}
        className="flex h-[90%] w-full flex-1 justify-center overflow-y-auto p-4 md:h-[83vh]"
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

        {queries.length > 0 && (
          <div className="mt-16 w-full md:w-8/12">
            {queries.map((query, index) => {
              return (
                <Fragment key={index}>
                  <ConversationBubble
                    className={'mb-1 last:mb-28 md:mb-7'}
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
        )}

        {queries.length === 0 && <Hero handleQuestion={handleQuestion} />}
      </div>

      <div className="flex w-11/12 flex-col items-end self-center rounded-2xl bg-opacity-0 pb-1 sm:w-6/12">
        <div className="flex h-full w-full items-center rounded-[40px] border border-silver bg-white py-1 dark:bg-raisin-black">
          <div
            id="inputbox"
            ref={inputRef}
            tabIndex={1}
            placeholder={t('inputPlaceholder')}
            contentEditable
            onPaste={handlePaste}
            className={`inputbox-style max-h-24 w-full overflow-y-auto overflow-x-hidden whitespace-pre-wrap rounded-full bg-white pt-5 pb-[22px] text-base leading-tight opacity-100 focus:outline-none dark:bg-raisin-black dark:text-bright-gray`}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleQuestionSubmission();
              }
            }}
          ></div>
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

        <p className="text-gray-595959 hidden w-[100vw] self-center  bg-white bg-transparent py-2 text-center text-xs dark:bg-raisin-black dark:text-bright-gray md:inline md:w-full">
          {t('tagline')}
        </p>
      </div>
    </div>
  );
}
