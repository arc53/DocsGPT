import {
  Fragment,
  ReactNode,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from 'react';
import { useTranslation } from 'react-i18next';

import Retry from '../assets/retry.svg?react';
import { Button } from '../components/ui/button';
import {
  MessageScroller,
  MessageScrollerButton,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerProvider,
  MessageScrollerViewport,
} from '../components/ui/message-scroller';
import Hero from '../Hero';
import ConversationBubble from './ConversationBubble';
import { FEEDBACK, Query, Status } from './conversationModels';
import StreamingStatusLine from './StreamingStatusLine';

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
  /** Active agent id; threaded into SchedulerToolCallCard. */
  agentId?: string;
};

const MS_VIEWPORT_SELECTOR = '[data-slot="message-scroller-viewport"]';
const STICK_THRESHOLD_PX = 48;

const DEFAULT_BUBBLE_MARGIN = 'mb-7';
const FIRST_QUESTION_BUBBLE_MARGIN_TOP = 'mt-5';
// Below DEFAULT_BUBBLE_MARGIN so a question groups with its own answer.
const QUESTION_BUBBLE_MARGIN_BOTTOM = 'mb-3';

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
  agentId,
}: ConversationMessagesProps) {
  const { t } = useTranslation();

  const hasMessages = queries.length > 0;
  const lastQuery = queries[queries.length - 1];
  const lastTurnContentLength =
    (lastQuery?.thought?.length ?? 0) + (lastQuery?.response?.length ?? 0);
  const stickToBottomRef = useRef(true);

  // pin-to-top jump
  // once the user scrolls up past the pin's reserved spacer, collapse it (via the scroller's
  // own spacerClassName) so it never lingers as dead space. Re-arms on the next
  // turn so the following question can pin to the top again.
  const [spacerCollapsed, setSpacerCollapsed] = useState(false);
  const spacerCollapsedRef = useRef(false);
  const prevQueryCountRef = useRef(queries.length);
  useEffect(() => {
    if (queries.length > prevQueryCountRef.current) {
      spacerCollapsedRef.current = false;
      setSpacerCollapsed(false);
    }
    prevQueryCountRef.current = queries.length;
  }, [queries.length]);

  useEffect(() => {
    if (!hasMessages) return;
    const vp = document.querySelector<HTMLElement>(MS_VIEWPORT_SELECTOR);
    if (!vp) return;
    const onScroll = () => {
      const dist = vp.scrollHeight - vp.scrollTop - vp.clientHeight;
      stickToBottomRef.current = dist < STICK_THRESHOLD_PX;
      // Collapse only once the spacer has scrolled fully below the fold
      // (dist >= its height) so removing it never shifts the visible content.
      // Reading style.height (the primitive's inline value) avoids a reflow.
      if (!spacerCollapsedRef.current) {
        const spacer = vp.querySelector<HTMLElement>('.msc-spacer');
        const spacerH = spacer ? parseFloat(spacer.style.height) || 0 : 0;
        if (spacerH > STICK_THRESHOLD_PX && dist >= spacerH) {
          spacerCollapsedRef.current = true;
          setSpacerCollapsed(true);
        }
      }
    };
    onScroll();
    vp.addEventListener('scroll', onScroll, { passive: true });
    return () => vp.removeEventListener('scroll', onScroll);
  }, [hasMessages]);

  useLayoutEffect(() => {
    if (status !== 'loading' || !hasMessages) return;
    const vp = document.querySelector<HTMLElement>(MS_VIEWPORT_SELECTOR);
    if (!vp) return;
    const dist = vp.scrollHeight - vp.scrollTop - vp.clientHeight;
    if (stickToBottomRef.current && dist > 0) vp.scrollTop = vp.scrollHeight;
  }, [status, lastTurnContentLength, hasMessages]);

  const columnClass = isSplitView
    ? 'w-full max-w-325 px-2'
    : 'w-full max-w-325 px-2 md:w-11/12 lg:w-10/12 xl:w-9/12 2xl:w-8/12';

  // The empty state sits directly on top of the composer with nothing between
  // them, so it takes the composer's width rather than the wider message column.
  const emptyStateColumnClass = isSplitView
    ? 'w-full max-w-290 px-2'
    : 'w-full max-w-290 px-2 md:w-10/12 lg:w-9/12 xl:w-8/12 2xl:w-7/12';

  const renderResponseView = (query: Query, index: number) => {
    const isLastMessage = index === queries.length - 1;
    const bubbleMargin = DEFAULT_BUBBLE_MARGIN;

    // Error first; reconciler-failed rows may carry partial thought/
    // tool_calls and would otherwise fall into the answer branch.
    if (query.error) {
      const retryButton = (
        <Button
          type="button"
          variant="ghost"
          className="dark:text-foreground h-auto self-center rounded-full px-5 py-3 text-lg text-gray-500 delay-100 hover:border-gray-500"
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
          <Retry
            width={12}
            height={12}
            className="text-gray-500 dark:text-[#ECECF1]"
          />
        </Button>
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

    // tool_calls.length, not tool_calls — empty arrays are JS-truthy.
    // ``notice`` is included so a non-fatal notice still surfaces even when the
    // run produced no textual answer (e.g. an artifact-only workflow).
    const hasContent =
      query.thought ||
      query.response ||
      (query.tool_calls && query.tool_calls.length > 0) ||
      query.research ||
      query.notice ||
      // An artifact-only workflow run may produce no textual answer / tool_calls;
      // the run id alone is enough to render its produced artifacts.
      query.workflow_run_id;
    if (hasContent) {
      const isCurrentlyStreaming =
        status === 'loading' && index === queries.length - 1;
      return (
        <Fragment key={`${index}-ANSWER`}>
          {query.notice ? (
            <div
              role="status"
              className={`${bubbleMargin} mr-5 self-start rounded-2xl border border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-800 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-200`}
            >
              {query.notice}
            </div>
          ) : null}
          <ConversationBubble
            className={bubbleMargin}
            message={query.response}
            type={'ANSWER'}
            thought={query.thought}
            sources={query.sources}
            toolCalls={query.tool_calls}
            segments={query.segments}
            workflowRunId={query.workflow_run_id}
            research={query.research}
            onOpenArtifact={onOpenArtifact}
            onToolAction={onToolAction}
            feedback={query.feedback}
            isStreaming={isCurrentlyStreaming}
            agentId={agentId}
            handleFeedback={
              handleFeedback
                ? (feedback) => handleFeedback(query, feedback, index)
                : undefined
            }
          />
        </Fragment>
      );
    }

    if (status === 'loading' && index === queries.length - 1) {
      return (
        <div
          className={`fade-in-bubble group dark:text-foreground flex flex-col flex-wrap self-start ${bubbleMargin}`}
        >
          <div className="flex max-w-full flex-col flex-wrap items-start self-start lg:flex-nowrap">
            <StreamingStatusLine className="my-2 ml-6" />
          </div>
        </div>
      );
    }

    return null;
  };

  if (queries.length === 0) {
    return (
      <div className="flex h-full w-full justify-center overflow-y-auto will-change-scroll sm:pt-6 lg:pt-12">
        <div className={emptyStateColumnClass}>
          {headerContent}
          {showHeroOnEmpty ? <Hero handleQuestion={handleQuestion} /> : null}
        </div>
      </div>
    );
  }

  return (
    <MessageScrollerProvider autoScroll>
      <MessageScroller>
        <MessageScrollerViewport className="sm:pt-6 lg:pt-12">
          <MessageScrollerContent
            spacerClassName={
              spacerCollapsed ? 'msc-spacer max-h-0' : 'msc-spacer'
            }
            className={`mx-auto pb-7 ${columnClass}`}
          >
            {headerContent}
            {queries.map((query, index) => {
              const responseView = renderResponseView(query, index);
              return (
                <Fragment key={`${index}-query-fragment`}>
                  <MessageScrollerItem messageId={`q-${index}`} scrollAnchor>
                    <ConversationBubble
                      className={`${QUESTION_BUBBLE_MARGIN_BOTTOM} ${
                        index === 0 ? FIRST_QUESTION_BUBBLE_MARGIN_TOP : ''
                      }`}
                      message={query.prompt}
                      type="QUESTION"
                      handleUpdatedQuestionSubmission={handleQuestionSubmission}
                      questionNumber={index}
                      sources={query.sources}
                      filesAttached={query.attachments}
                    />
                  </MessageScrollerItem>
                  {responseView && (
                    <MessageScrollerItem messageId={`a-${index}`}>
                      {responseView}
                    </MessageScrollerItem>
                  )}
                </Fragment>
              );
            })}
          </MessageScrollerContent>
        </MessageScrollerViewport>
        <MessageScrollerButton />
      </MessageScroller>
    </MessageScrollerProvider>
  );
}
