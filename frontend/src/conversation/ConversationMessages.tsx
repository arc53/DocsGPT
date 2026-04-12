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
import DocsGPT3 from '../assets/cute_docsgpt3.svg';
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
    index?: number;
  }) => void;
  handleQuestionSubmission: (
    updatedQuestion?: string,
    updated?: boolean,
    index?: number,
  ) => void;
  handleFeedback?: (query: Query, feedback: FEEDBACK, index: number) => void;
  queries: Query[];
  status: Status;
  showHeroOnEmpty?: boolean;
  headerContent?: ReactNode;
  onOpenArtifact?: (artifact: { id: string; toolName: string }) => void;
  onToolAction?: (
    callId: string,
    decision: 'approved' | 'denied',
    comment?: string,
  ) => void;
  isSplitView?: boolean;
};

export default function ConversationMessages({
  handleQuestion,
  handleQuestionSubmission,
  queries,
  status,
  handleFeedback,
  showHeroOnEmpty = true,
  headerContent,
  onOpenArtifact,
  onToolAction,
  isSplitView = false,
}: ConversationMessagesProps) {
  const [isDarkTheme] = useDarkTheme();
  const { t } = useTranslation();

  const conversationRef = useRef<HTMLDivElement>(null);
  const [scrollButtonVisible, setScrollButtonVisible] = useState(false);
  const userInterruptedRef = useRef(false);
  const [interrupted, setInterrupted] = useState(false);
  const lastTouchYRef = useRef<number | null>(null);
  const isInitialLoad = useRef(true);
  const prevQueriesRef = useRef(queries);
  const isAutoScrollingRef = useRef(false);
  const smoothScrollTimeoutRef =
    useRef<ReturnType<typeof setTimeout>>(undefined);
  const showButtonTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => {
    return () => {
      clearTimeout(smoothScrollTimeoutRef.current);
      clearTimeout(showButtonTimerRef.current);
    };
  }, []);

  const isAtBottom = useCallback(() => {
    const el = conversationRef.current;
    if (!el) return true;
    return el.scrollHeight - el.scrollTop - el.clientHeight < SCROLL_THRESHOLD;
  }, []);

  // Arm on upward scroll intent; requiring !isAtBottom() missed small nudges still inside SCROLL_THRESHOLD.
  const markInterruptedIfLoading = useCallback(() => {
    if (userInterruptedRef.current || status !== 'loading') return;
    userInterruptedRef.current = true;
    setInterrupted(true);
  }, [status]);

  const handleWheel = useCallback(
    (e: React.WheelEvent) => {
      if (e.deltaY < 0) markInterruptedIfLoading();
    },
    [markInterruptedIfLoading],
  );

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    lastTouchYRef.current = e.touches[0].clientY;
  }, []);

  const handleTouchMove = useCallback(
    (e: React.TouchEvent) => {
      const y = e.touches[0].clientY;
      if (lastTouchYRef.current !== null && y > lastTouchYRef.current) {
        markInterruptedIfLoading();
      }
      lastTouchYRef.current = y;
    },
    [markInterruptedIfLoading],
  );

  const setButtonHidden = useCallback(() => {
    clearTimeout(showButtonTimerRef.current);
    showButtonTimerRef.current = undefined;
    setScrollButtonVisible(false);
  }, []);

  const setButtonVisibleDebounced = useCallback(() => {
    if (showButtonTimerRef.current) return;
    showButtonTimerRef.current = setTimeout(() => {
      setScrollButtonVisible(true);
      showButtonTimerRef.current = undefined;
    }, 300);
  }, []);

  const scrollConversationToBottom = useCallback(
    (instant?: boolean) => {
      if (!conversationRef.current) return;

      isAutoScrollingRef.current = true;
      clearTimeout(smoothScrollTimeoutRef.current);

      requestAnimationFrame(() => {
        if (!conversationRef?.current) return;

        if (instant) {
          conversationRef.current.scrollTop =
            conversationRef.current.scrollHeight;
          if (isAtBottom()) {
            setButtonHidden();
          }
          isAutoScrollingRef.current = false;
        } else {
          conversationRef.current.scrollTo({
            behavior: 'smooth',
            top: conversationRef.current.scrollHeight,
          });
          smoothScrollTimeoutRef.current = setTimeout(() => {
            if (isAtBottom()) {
              setButtonHidden();
            }
            isAutoScrollingRef.current = false;
          }, 500);
        }
      });
    },
    [isAtBottom, setButtonHidden],
  );

  const handleScroll = useCallback(() => {
    const el = conversationRef.current;
    if (!el) return;

    const atBottom = isAtBottom();

    if (atBottom && userInterruptedRef.current) {
      userInterruptedRef.current = false;
      setInterrupted(false);
    }

    if (atBottom) {
      setButtonHidden();
      isAutoScrollingRef.current = false;
      return;
    }

    if (isAutoScrollingRef.current) {
      return;
    }

    setButtonVisibleDebounced();
  }, [isAtBottom, setButtonHidden, setButtonVisibleDebounced]);

  const lastQuery = queries[queries.length - 1];
  const lastQueryResponse = lastQuery?.response;
  const lastQueryError = lastQuery?.error;
  const lastQueryThought = lastQuery?.thought;

  useEffect(() => {
    if (interrupted) return;

    const prevQueries = prevQueriesRef.current;
    const isConversationSwitch =
      prevQueries !== queries && prevQueries[0] !== queries[0];

    if (isInitialLoad.current || isConversationSwitch) {
      isInitialLoad.current = false;
      scrollConversationToBottom(true);
      prevQueriesRef.current = queries;
      return;
    }

    const isNewMessage = queries.length > prevQueries.length;
    prevQueriesRef.current = queries;

    scrollConversationToBottom(isNewMessage ? false : true);
  }, [
    queries.length,
    lastQueryResponse,
    lastQueryError,
    lastQueryThought,
    interrupted,
    scrollConversationToBottom,
  ]);

  useEffect(() => {
    if (status === 'idle') {
      userInterruptedRef.current = false;
      setInterrupted(false);
    }
  }, [status]);

  useEffect(() => {
    const currentConversationRef = conversationRef.current;
    currentConversationRef?.addEventListener('scroll', handleScroll);
    return () => {
      currentConversationRef?.removeEventListener('scroll', handleScroll);
    };
  }, [handleScroll]);

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

    if (query.thought || query.response || query.tool_calls || query.research) {
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
          research={query.research}
          onOpenArtifact={onOpenArtifact}
          onToolAction={onToolAction}
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
          className="dark:text-foreground flex items-center justify-center gap-3 self-center rounded-full px-5 py-3 text-lg text-gray-500 transition-colors delay-100 hover:border-gray-500 disabled:cursor-not-allowed"
          disabled={status === 'loading'}
          onClick={() => {
            const questionToRetry = queries[index].prompt;
            handleQuestion({
              question: questionToRetry,
              isRetry: true,
              index,
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

    if (status === 'loading' && isLastMessage) {
      return (
        <div
          className={`fade-in-bubble flex flex-wrap self-start ${bubbleMargin} group dark:text-foreground flex-col`}
        >
          <div className="flex max-w-full flex-col flex-wrap items-start self-start lg:flex-nowrap">
            <div className="my-2 flex flex-row items-center justify-center gap-3">
              <div className="flex h-8.5 w-8.5 items-center justify-center overflow-hidden rounded-full">
                <img
                  src={DocsGPT3}
                  alt={t('conversation.answer')}
                  className="h-full w-full object-cover"
                />
              </div>
              <p className="text-base font-semibold">
                {t('conversation.answer')}
              </p>
            </div>
            <div className="bg-gray-1000 dark:bg-gun-metal mr-5 flex rounded-3xl px-6 py-5">
              <div className="thinking-dots">
                <span></span>
                <span></span>
                <span></span>
              </div>
            </div>
          </div>
        </div>
      );
    }

    return null;
  };

  return (
    <div
      ref={conversationRef}
      onWheel={handleWheel}
      onTouchStart={handleTouchStart}
      onTouchMove={handleTouchMove}
      className="flex h-full w-full justify-center overflow-y-auto will-change-scroll sm:pt-6 lg:pt-12"
    >
      {queries.length > 0 && (
        <button
          onClick={() => {
            userInterruptedRef.current = false;
            setInterrupted(false);
            scrollConversationToBottom();
          }}
          aria-label={t('Scroll to bottom') || 'Scroll to bottom'}
          className={`border-border bg-card fixed bottom-40 left-1/2 z-10 flex h-7 w-7 -translate-x-1/2 items-center justify-center rounded-full border transition-all duration-300 ease-in-out md:right-14 md:left-auto md:h-9 md:w-9 md:translate-x-0 ${
            scrollButtonVisible
              ? 'pointer-events-auto scale-100 opacity-100'
              : 'pointer-events-none scale-75 opacity-0'
          }`}
        >
          <img
            src={ArrowDown}
            alt="arrow down"
            className="h-4 w-4 opacity-50 filter md:h-5 md:w-5 dark:invert"
          />
        </button>
      )}

      <div
        className={
          isSplitView
            ? 'w-full max-w-325 px-2'
            : 'w-full max-w-325 px-2 md:w-9/12 lg:w-8/12 xl:w-8/12 2xl:w-6/12'
        }
      >
        {headerContent}

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
