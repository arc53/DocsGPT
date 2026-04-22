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
const LAST_BUBBLE_MARGIN = 'mb-40';
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
  const contentRef = useRef<HTMLDivElement>(null);
  const [scrollButtonVisible, setScrollButtonVisible] = useState(false);
  const userInterruptedRef = useRef(false);
  const [interrupted, setInterrupted] = useState(false);
  const lastTouchYRef = useRef<number | null>(null);
  const isInitialLoad = useRef(true);
  const prevQueriesRef = useRef(queries);
  const isAutoScrollingRef = useRef(false);
  const showButtonTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => {
    return () => clearTimeout(showButtonTimerRef.current);
  }, []);

  const isAtBottom = useCallback(() => {
    const el = conversationRef.current;
    if (!el) return true;
    return (
      el.scrollHeight - Math.max(0, el.scrollTop) - el.clientHeight <
      SCROLL_THRESHOLD
    );
  }, []);

  const markInterrupted = useCallback(() => {
    if (userInterruptedRef.current) return;
    userInterruptedRef.current = true;
    setInterrupted(true);
  }, []);

  const handleWheel = useCallback(
    (e: React.WheelEvent) => {
      if (e.deltaY < 0) markInterrupted();
    },
    [markInterrupted],
  );

  useEffect(() => {
    const el = conversationRef.current;
    if (!el) return;
    const onTouchStart = (e: TouchEvent) => {
      lastTouchYRef.current = e.touches[0].clientY;
    };
    const onTouchMove = (e: TouchEvent) => {
      const y = e.touches[0].clientY;
      if (lastTouchYRef.current !== null && y > lastTouchYRef.current) {
        markInterrupted();
      }
      lastTouchYRef.current = y;
    };
    el.addEventListener('touchstart', onTouchStart, { passive: true });
    el.addEventListener('touchmove', onTouchMove, { passive: true });
    return () => {
      el.removeEventListener('touchstart', onTouchStart);
      el.removeEventListener('touchmove', onTouchMove);
    };
  }, [markInterrupted]);

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

  const scrollToBottom = useCallback((instant = true) => {
    const el = conversationRef.current;
    if (!el) return;
    isAutoScrollingRef.current = true;
    if (instant) {
      el.scrollTop = el.scrollHeight;
    } else {
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
    }
    requestAnimationFrame(() => {
      isAutoScrollingRef.current = false;
    });
  }, []);

  const handleScroll = useCallback(() => {
    const el = conversationRef.current;
    if (!el) return;
    const atBottom = isAtBottom();
    if (atBottom) {
      if (userInterruptedRef.current) {
        userInterruptedRef.current = false;
        setInterrupted(false);
      }
      setButtonHidden();
      isAutoScrollingRef.current = false;
      return;
    }
    if (isAutoScrollingRef.current) return;
    setButtonVisibleDebounced();
  }, [isAtBottom, setButtonHidden, setButtonVisibleDebounced]);

  const lastQuery = queries[queries.length - 1];
  const lastQueryResponse = lastQuery?.response;
  const lastQueryError = lastQuery?.error;
  const lastQueryThought = lastQuery?.thought;

  useEffect(() => {
    const prevQueries = prevQueriesRef.current;
    const isConversationSwitch =
      prevQueries !== queries && prevQueries[0] !== queries[0];

    if (isInitialLoad.current || isConversationSwitch) {
      isInitialLoad.current = false;
      userInterruptedRef.current = false;
      prevQueriesRef.current = queries;
      scrollToBottom(true);
      return;
    }

    const isNewMessage = queries.length > prevQueries.length;
    prevQueriesRef.current = queries;

    if (isNewMessage) {
      userInterruptedRef.current = false;
      setInterrupted(false);
      scrollToBottom(true);
      return;
    }

    if (interrupted) return;

    scrollToBottom(true);
  }, [
    queries.length,
    lastQueryResponse,
    lastQueryError,
    lastQueryThought,
    interrupted,
    scrollToBottom,
  ]);

  useEffect(() => {
    if (status === 'idle') {
      userInterruptedRef.current = false;
      setInterrupted(false);
      scrollToBottom(true);
    }
  }, [status, scrollToBottom]);

  useEffect(() => {
    const el = contentRef.current;
    if (!el) return;
    const observer = new ResizeObserver(() => {
      if (!userInterruptedRef.current) {
        requestAnimationFrame(() => scrollToBottom(true));
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [scrollToBottom]);

  useEffect(() => {
    const el = contentRef.current;
    if (!el) return;
    const mo = new MutationObserver((mutations) => {
      if (userInterruptedRef.current) return;
      const hasSvg = mutations.some((m) =>
        Array.from(m.addedNodes).some(
          (n) =>
            n.nodeType === Node.ELEMENT_NODE &&
            ((n as Element).tagName.toLowerCase() === 'svg' ||
              !!(n as Element).querySelector('svg')),
        ),
      );
      if (hasSvg) requestAnimationFrame(() => scrollToBottom(true));
    });
    mo.observe(el, { subtree: true, childList: true });
    return () => mo.disconnect();
  }, [scrollToBottom]);

  useEffect(() => {
    const el = conversationRef.current;
    el?.addEventListener('scroll', handleScroll);
    return () => el?.removeEventListener('scroll', handleScroll);
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

    const isCurrentlyStreaming =
      status === 'loading' && index === queries.length - 1;

    if (
      query.thought ||
      query.response ||
      query.tool_calls ||
      query.research ||
      isCurrentlyStreaming
    ) {
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

    return null;
  };

  return (
    <div
      ref={conversationRef}
      onWheel={handleWheel}
      className="flex h-full w-full justify-center overflow-y-auto overscroll-y-contain will-change-scroll sm:pt-6 lg:pt-12"
    >
      {queries.length > 0 && (
        <button
          onClick={() => {
            userInterruptedRef.current = false;
            setInterrupted(false);
            scrollToBottom(false);
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
        ref={contentRef}
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
