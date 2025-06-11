import {
  Fragment,
  ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import { useTranslation } from 'react-i18next';

import ArrowDown from '../assets/arrow-down.svg';
import RetryIcon from '../components/RetryIcon';
import Hero from '../Hero';
import { useDarkTheme } from '../hooks';
import ConversationBubble from './ConversationBubble';
import { FEEDBACK, Query, Status } from './conversationModels';

const SCROLL_THRESHOLD = 10;
const LAST_BUBBLE_MARGIN = 'mb-32';
const DEFAULT_BUBBLE_MARGIN = 'mb-7';
const FIRST_QUESTION_BUBBLE_MARGIN_TOP = 'mt-5';

type ConversationMessagesProps = {
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
  headerContent?: ReactNode;
};

export default function ConversationMessages({
  handleQuestion,
  handleQuestionSubmission,
  queries,
  status,
  handleFeedback,
  showHeroOnEmpty = true,
  headerContent,
}: ConversationMessagesProps) {
  const [isDarkTheme] = useDarkTheme();
  const { t } = useTranslation();

  const conversationRef = useRef<HTMLDivElement>(null);
  const [hasScrolledToLast, setHasScrolledToLast] = useState(true);
  const [userInterruptedScroll, setUserInterruptedScroll] = useState(false);

  const handleUserScrollInterruption = useCallback(() => {
    if (!userInterruptedScroll && status === 'loading') {
      setUserInterruptedScroll(true);
    }
  }, [userInterruptedScroll, status]);

  const scrollConversationToBottom = useCallback(() => {
    if (!conversationRef.current || userInterruptedScroll) return;

    requestAnimationFrame(() => {
      if (!conversationRef?.current) return;

      if (status === 'idle' || !queries[queries.length - 1]?.response) {
        conversationRef.current.scrollTo({
          behavior: 'smooth',
          top: conversationRef.current.scrollHeight,
        });
      } else {
        conversationRef.current.scrollTop =
          conversationRef.current.scrollHeight;
      }
    });
  }, [userInterruptedScroll, status, queries]);

  const checkScrollPosition = useCallback(() => {
    const el = conversationRef.current;
    if (!el) return;
    const isAtBottom =
      el.scrollHeight - el.scrollTop - el.clientHeight < SCROLL_THRESHOLD;
    setHasScrolledToLast(isAtBottom);
  }, [setHasScrolledToLast]);

  useEffect(() => {
    if (!userInterruptedScroll) {
      scrollConversationToBottom();
    }
  }, [
    queries.length,
    queries[queries.length - 1]?.response,
    queries[queries.length - 1]?.error,
    queries[queries.length - 1]?.thought,
    userInterruptedScroll,
    scrollConversationToBottom,
  ]);

  useEffect(() => {
    if (status === 'idle') {
      setUserInterruptedScroll(false);
    }
  }, [status]);

  useEffect(() => {
    const currentConversationRef = conversationRef.current;
    currentConversationRef?.addEventListener('scroll', checkScrollPosition);
    return () => {
      currentConversationRef?.removeEventListener(
        'scroll',
        checkScrollPosition,
      );
    };
  }, [checkScrollPosition]);

  const retryIconProps = {
    width: 12,
    height: 12,
    fill: isDarkTheme ? 'rgb(236 236 241)' : 'rgb(107 114 120)',
    stroke: isDarkTheme ? 'rgb(236 236 241)' : 'rgb(107 114 120)',
    strokeWidth: 10,
  };

  const renderResponseView = (query: Query, index: number) => {
    const isLastMessage = index === queries.length - 1;
    const bubbleMargin = isLastMessage
      ? LAST_BUBBLE_MARGIN
      : DEFAULT_BUBBLE_MARGIN;

    if (query.thought || query.response || query.tool_calls) {
      const isCurrentlyStreaming =
        status === 'loading' && index === queries.length - 1;
      return (
        <ConversationBubble
          className={bubbleMargin}
          key={`${index}-ANSWER`}
          message={query.response}
          type={'ANSWER'}
          thought={query.thought}
          sources={query.sources}
          toolCalls={query.tool_calls}
          feedback={query.feedback}
          isStreaming={isCurrentlyStreaming}
          handleFeedback={
            handleFeedback
              ? (feedback) => handleFeedback(query, feedback, index)
              : undefined
          }
        />
      );
    }

    if (query.error) {
      const retryButton = (
        <button
          className="flex items-center justify-center gap-3 self-center rounded-full px-5 py-3 text-lg text-gray-500 transition-colors delay-100 hover:border-gray-500 disabled:cursor-not-allowed dark:text-bright-gray"
          disabled={status === 'loading'}
          onClick={() => {
            const questionToRetry = queries[index].prompt;
            handleQuestion({
              question: questionToRetry,
              isRetry: true,
              indx: index,
            });
          }}
          aria-label={t('Retry') || 'Retry'}
        >
          <RetryIcon {...retryIconProps} />
        </button>
      );
      return (
        <ConversationBubble
          className={bubbleMargin}
          key={`${index}-ERROR`}
          message={query.error}
          type="ERROR"
          retryBtn={retryButton}
        />
      );
    }
    return null;
  };

  return (
    <div
      ref={conversationRef}
      onWheel={handleUserScrollInterruption}
      onTouchMove={handleUserScrollInterruption}
      className="flex h-full w-full justify-center overflow-y-auto will-change-scroll sm:pt-6 lg:pt-12"
    >
      {queries.length > 0 && !hasScrolledToLast && (
        <button
          onClick={() => {
            setUserInterruptedScroll(false);
            scrollConversationToBottom();
          }}
          aria-label={t('Scroll to bottom') || 'Scroll to bottom'}
          className="fixed bottom-40 right-14 z-10 flex h-7 w-7 items-center justify-center rounded-full border-[0.5px] border-gray-alpha bg-gray-100 bg-opacity-50 dark:bg-gunmetal md:h-9 md:w-9 md:bg-opacity-100"
        >
          <img
            src={ArrowDown}
            alt="arrow down"
            className="h-4 w-4 opacity-50 filter dark:invert md:h-5 md:w-5"
          />
        </button>
      )}

      <div className="w-full max-w-[1300px] px-2 md:w-9/12 lg:w-8/12 xl:w-8/12 2xl:w-6/12">
        {headerContent && headerContent}

        {queries.length > 0 ? (
          queries.map((query, index) => (
            <Fragment key={`${index}-query-fragment`}>
              <ConversationBubble
                className={index === 0 ? FIRST_QUESTION_BUBBLE_MARGIN_TOP : ''}
                key={`${index}-QUESTION`}
                message={query.prompt}
                type="QUESTION"
                handleUpdatedQuestionSubmission={handleQuestionSubmission}
                questionNumber={index}
                sources={query.sources}
                filesAttached={query.attachments}
              />
              {renderResponseView(query, index)}
            </Fragment>
          ))
        ) : showHeroOnEmpty ? (
          <Hero handleQuestion={handleQuestion} />
        ) : null}
      </div>
    </div>
  );
}
