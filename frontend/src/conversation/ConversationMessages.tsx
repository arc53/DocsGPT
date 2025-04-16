import { Fragment, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import ArrowDown from '../assets/arrow-down.svg';
import RetryIcon from '../components/RetryIcon';
import Hero from '../Hero';
import { useDarkTheme } from '../hooks';
import ConversationBubble from './ConversationBubble';
import { FEEDBACK, Query, Status } from './conversationModels';

interface ConversationMessagesProps {
  handleQuestion: (params: {
    question: string;
    isRetry?: boolean;
    updated?: boolean | null;
    indx?: number;
  }) => void;
  handleQuestionSubmission: (
    updatedQuestion?: string,
    updated?: boolean,
    indx?: number,
  ) => void;
  handleFeedback?: (query: Query, feedback: FEEDBACK, index: number) => void;
  queries: Query[];
  status: Status;
  showHeroOnEmpty?: boolean;
}

export default function ConversationMessages({
  handleQuestion,
  handleQuestionSubmission,
  queries,
  status,
  handleFeedback,
  showHeroOnEmpty = true,
}: ConversationMessagesProps) {
  const [isDarkTheme] = useDarkTheme();
  const { t } = useTranslation();

  const conversationRef = useRef<HTMLDivElement>(null);
  const [hasScrolledToLast, setHasScrolledToLast] = useState(true);
  const [eventInterrupt, setEventInterrupt] = useState(false);

  const handleUserInterruption = () => {
    if (!eventInterrupt && status === 'loading') {
      setEventInterrupt(true);
    }
  };

  const scrollIntoView = () => {
    if (!conversationRef?.current || eventInterrupt) return;

    if (status === 'idle' || !queries[queries.length - 1]?.response) {
      conversationRef.current.scrollTo({
        behavior: 'smooth',
        top: conversationRef.current.scrollHeight,
      });
    } else {
      conversationRef.current.scrollTop = conversationRef.current.scrollHeight;
    }
  };

  const checkScroll = () => {
    const el = conversationRef.current;
    if (!el) return;
    const isBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 10;
    setHasScrolledToLast(isBottom);
  };

  useEffect(() => {
    !eventInterrupt && scrollIntoView();
  }, [queries.length, queries[queries.length - 1]]);

  useEffect(() => {
    if (status === 'idle') {
      setEventInterrupt(false);
    }
  }, [status]);

  useEffect(() => {
    conversationRef.current?.addEventListener('scroll', checkScroll);
    return () => {
      conversationRef.current?.removeEventListener('scroll', checkScroll);
    };
  }, []);

  const prepResponseView = (query: Query, index: number) => {
    let responseView;
    if (query.thought || query.response) {
      responseView = (
        <ConversationBubble
          className={`${index === queries.length - 1 ? 'mb-32' : 'mb-7'}`}
          key={`${index}ANSWER`}
          message={query.response}
          type={'ANSWER'}
          thought={query.thought}
          sources={query.sources}
          toolCalls={query.tool_calls}
          feedback={query.feedback}
          handleFeedback={
            handleFeedback
              ? (feedback) => handleFeedback(query, feedback, index)
              : undefined
          }
        />
      );
    } else if (query.error) {
      const retryBtn = (
        <button
          className="flex items-center justify-center gap-3 self-center rounded-full py-3 px-5 text-lg text-gray-500 transition-colors delay-100 hover:border-gray-500 disabled:cursor-not-allowed dark:text-bright-gray"
          disabled={status === 'loading'}
          onClick={() => {
            handleQuestion({
              question: queries[queries.length - 1].prompt,
              isRetry: true,
            });
          }}
        >
          <RetryIcon
            width={12}
            height={12}
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
        />
      );
    }
    return responseView;
  };

  return (
    <div
      ref={conversationRef}
      onWheel={handleUserInterruption}
      onTouchMove={handleUserInterruption}
      className="flex justify-center w-full overflow-y-auto h-full sm:pt-12"
    >
      {queries.length > 0 && !hasScrolledToLast && (
        <button
          onClick={scrollIntoView}
          aria-label="scroll to bottom"
          className="fixed bottom-40 right-14 z-10 flex h-7 w-7 items-center justify-center rounded-full border-[0.5px] border-gray-alpha bg-gray-100 bg-opacity-50 dark:bg-gunmetal md:h-9 md:w-9 md:bg-opacity-100"
        >
          <img
            src={ArrowDown}
            alt="arrow down"
            className="h-4 w-4 opacity-50 md:h-5 md:w-5 filter dark:invert"
          />
        </button>
      )}

      <div className="w-full md:w-9/12 lg:w-8/12 xl:w-8/12 2xl:w-6/12 max-w-[1300px] px-2">
        {queries.length > 0 ? (
          queries.map((query, index) => (
            <Fragment key={index}>
              <ConversationBubble
                className={'first:mt-5'}
                key={`${index}QUESTION`}
                message={query.prompt}
                type="QUESTION"
                handleUpdatedQuestionSubmission={handleQuestionSubmission}
                questionNumber={index}
                sources={query.sources}
              />
              {prepResponseView(query, index)}
            </Fragment>
          ))
        ) : showHeroOnEmpty ? (
          <Hero handleQuestion={handleQuestion} />
        ) : null}
      </div>
    </div>
  );
}
