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
import { useDarkTheme, useMediaQuery } from '../hooks';
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
  const { isMobile } = useMediaQuery();

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
    if (queries.length) {
      queries[queries.length - 1].error && setLastQueryReturnedErr(true);
      queries[queries.length - 1].response && setLastQueryReturnedErr(false); // considering a query that initially returned error can later include a response property on retry
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
    !isRetry && dispatch(addQuery({ prompt: question })); // dispatch only new queries
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
          className="flex items-center justify-center gap-3 self-center rounded-full py-3 px-5  text-lg text-gray-500 transition-colors delay-100 hover:border-gray-500 disabled:cursor-not-allowed dark:text-bright-gray"
          disabled={status === 'loading'}
          onClick={() => {
            handleQuestion({
              question: queries[queries.length - 1].prompt,
              isRetry: true,
            });
          }}
        >
          <RetryIcon
            width={isMobile ? 12 : 12} // change the width and height according to device size if necessary
            height={isMobile ? 12 : 12}
            fill={isDarkTheme ? 'rgb(236 236 241)' : 'rgb(107 114 120)'}
            stroke={isDarkTheme ? 'rgb(236 236 241)' : 'rgb(107 114 120)'}
            strokeWidth={10}
          />
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

  const checkScroll = () => {
    const el = conversationRef.current;
    if (!el) return;
    const isBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 10;
    setHasScrolledToLast(isBottom);
  };

  // Prevent Safari refresh by touch scrolling beyond bounds
  useEffect(() => {
    const handleTouchMove = (e: TouchEvent) => {
      const conversationDiv = conversationRef.current;
      if (conversationDiv) {
        const { scrollTop, scrollHeight, clientHeight } = conversationDiv;

        // Prevent default if trying to scroll beyond top or bottom
        if ((scrollTop === 0 && e.touches[0].clientY > 0) || (scrollTop + clientHeight >= scrollHeight)) {
          e.preventDefault();
        }
      }
    };

    const conversationDiv = conversationRef.current;
    if (conversationDiv) {
      conversationDiv.addEventListener('touchmove', handleTouchMove, { passive: false });
    }

    return () => {
      if (conversationDiv) {
        conversationDiv.removeEventListener('touchmove', handleTouchMove);
      }
    };
  }, []);

  useEffect(() => {
    handleInput();
    window.addEventListener('resize', handleInput);
    conversationRef.current?.addEventListener('scroll', checkScroll);
    return () => {
      window.removeEventListener('resize', handleInput);
      conversationRef.current?.removeEventListener('scroll', checkScroll);
    };
  }, []);

  return (
    <div className="flex flex-col gap-1 h-full justify-end">
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
        className="flex justify-center w-full overflow-y-auto h-screen sm:mt-12"
      >
        {queries.length > 0 && !hasScrolledToLast && (
          <button
            className="absolute bottom-32 z-10 flex h-8 w-8 animate-bounce items-center justify-center rounded-full border-0 bg-white p-1 drop-shadow-md dark:bg-black dark:ring-bright-gray dark:hover:bg-[#28292E]"
            title={t('scroll-to-bottom')}
            onClick={() =>
              conversationRef.current?.scrollTo({
                behavior: 'smooth',
                top: conversationRef.current.scrollHeight,
              })
            }
          >
            <img
              className="filter dark:invert"
              alt="arrow down"
              src={ArrowDown}
            />
          </button>
        )}
        <div className="min-w-9/12 flex w-full flex-col sm:max-w-2xl">
          <Hero />
          {queries.length > 0 &&
            queries.map((query, index) => (
              <Fragment key={index}>
                <ConversationBubble
                  className={'mt-7'}
                  key={`${index}PROMPT`}
                  message={query.prompt}
                  type={'PROMPT'}
                />
                {prepResponseView(query, index)}
              </Fragment>
            ))}
          {status === 'loading' && (
            <ConversationBubble
              className={'mb-32'}
              type={'ANSWER'}
              message={
                <div className="w-full text-center">
                  <img
                    alt="spinner"
                    className="m-auto h-8 w-8 animate-spin dark:hidden"
                    src={Spinner}
                  />
                  <img
                    alt="spinner"
                    className="m-auto hidden h-8 w-8 animate-spin dark:inline"
                    src={SpinnerDark}
                  />
                </div>
              }
            />
          )}
        </div>
      </div>
      <div className="fixed bottom-0 z-20 flex w-full bg-white py-2 dark:bg-[#202123] sm:relative sm:bg-transparent">
        <div className="mx-2 flex h-10 w-full max-w-2xl flex-row gap-2">
          <textarea
            id="inputbox"
            onInput={handleInput}
            className="block w-full resize-none overflow-hidden rounded-lg border-0 bg-[#F4F4F5] px-4 text-black shadow-xl outline-none focus:outline-none dark:bg-[#343541] dark:text-white sm:rounded-none sm:rounded-bl-lg sm:border-b sm:border-l sm:border-bright-gray"
            placeholder={t('ask-placeholder') as string}
            rows={1}
            ref={inputRef}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                handleQuestionSubmission();
              }
            }}
          />
          <button
            onClick={handleQuestionSubmission}
            className="rounded-lg bg-[#19C37D] py-2 pr-2 shadow-xl hover:bg-[#13a067] active:bg-[#13a067] dark:bg-[#10a37f] dark:hover:bg-[#0e7e63] sm:rounded-none sm:rounded-br-lg"
          >
            <img
              src={isDarkTheme ? SendDark : Send}
              alt="send"
              className="mx-3 inline-block h-5 w-5"
            />
          </button>
        </div>
      </div>
    </div>
  );
}
