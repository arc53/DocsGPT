import {
  Fragment,
  ReactNode,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { flushSync } from 'react-dom';
import { RotateCcw } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Alert, AlertDescription } from '../components/ui/alert';
import { IconButton } from '../components/ui/icon-button';
import {
  MessageScroller,
  MessageScrollerButton,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerProvider,
  MessageScrollerViewport,
} from '../components/ui/message-scroller';
import Hero from '../Hero';
import AgentStarters from '../hero/AgentStarters';
import AddToKnowledgeAction from './AddToKnowledgeAction';
import { deriveArtifactChips } from './artifactChips';
import JobCancelledRows from '../backgroundJobs/JobCancelledRow';
import WakeEventRow from '../backgroundJobs/WakeEventRow';
import type { OpenArtifactRequest } from './artifactCards';
import ChatLoadingSkeleton from './ChatLoadingSkeleton';
import ConversationBubble from './ConversationBubble';
import {
  FEEDBACK,
  Query,
  Status,
  TERMINATED_RESPONSE_PLACEHOLDER,
} from './conversationModels';
import { curatedErrorText } from './curatedError';
import StreamingStatusLine from './StreamingStatusLine';
import { cn } from '@/lib/utils';

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
  /**
   * The chat is still being read (opened by its URL): with nothing to show
   * yet, it draws as a loading chat, not as the empty one's hero.
   */
  isLoading?: boolean;
  /** The agent's starters, under `headerContent` while the chat is empty. */
  starters?: string[] | null;
  headerContent?: ReactNode;
  onOpenArtifact?: (artifact: OpenArtifactRequest) => void;
  onToolAction?: (
    callId: string,
    decision: 'approved' | 'denied',
    comment?: string,
  ) => void;
  isSplitView?: boolean;
  /** Active agent id; threaded into SchedulerToolCallCard. */
  agentId?: string;
  /**
   * Whether a turn whose files did not fit may offer Add to Knowledge. Only
   * the main chat, where the user picks the Knowledge the chat searches.
   */
  canAddToKnowledge?: boolean;
  /** A failed turn's files were accepted as Knowledge; ``index`` is the turn. */
  onKnowledgeAdded?: (index: number) => void;
};

// The backend's code for a turn that did not fit the model's window.
const CONTEXT_LENGTH_EXCEEDED = 'context_length_exceeded';

const MS_VIEWPORT_SELECTOR = '[data-slot="message-scroller-viewport"]';
const MS_SPACER_SELECTOR = '[data-message-scroller-spacer]';
const STICK_THRESHOLD_PX = 48;
// The keys the message-scroller primitive treats as a user scroll.
const SCROLL_KEYS = new Set([
  'ArrowDown',
  'ArrowUp',
  'End',
  'Home',
  'PageDown',
  'PageUp',
  ' ',
]);

/** The pin spacer's rendered height; 0 when the primitive shows none. */
function spacerHeight(vp: HTMLElement): number {
  return vp.querySelector<HTMLElement>(MS_SPACER_SELECTOR)?.offsetHeight ?? 0;
}

/**
 * How far the content's end lies below the viewport's bottom. The pin spacer
 * is room, not content: while it shows, the end is above the bottom and this
 * is negative.
 */
function contentEndDistance(
  vp: HTMLElement,
  spacer: number = spacerHeight(vp),
): number {
  return vp.scrollHeight - spacer - vp.scrollTop - vp.clientHeight;
}

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
  isLoading = false,
  starters,
  headerContent,
  onOpenArtifact,
  onToolAction,
  isSplitView = false,
  agentId,
  canAddToKnowledge = false,
  onKnowledgeAdded,
}: ConversationMessagesProps) {
  const { t } = useTranslation();

  // Artifact refs (A1, A2, ...) are CONVERSATION-scoped on the backend — a
  // ref minted on turn 1 still resolves, and edit_artifact still accepts it,
  // on turn 5. Resolving inline links against only the current turn's
  // artifacts made "the CSV from earlier" render as dead plain text.
  const conversationArtifacts = useMemo(
    () => queries.flatMap((query) => deriveArtifactChips(query.tool_calls)),
    [queries],
  );

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

  // A scroll gesture (the primitive's own user-intent events) releases its pin
  // on the latest question but leaves the spacer at its height; re-armed when
  // the next question arrives. Before the follow effect, so it runs first.
  const pinReleasedRef = useRef(false);
  // The primitive goes back to following the bottom whenever the content's
  // end is in view, measured without the spacer, so with a spacer showing it
  // always is. After a gesture that meant the next resize scrolled to the end
  // with the spacer gone, and the turn dropped by the spacer's height; once
  // the answer has ended, a late diagram that outgrew the spacer scrolled the
  // question off the top. So while a spacer shows after either, the primitive
  // does not follow the bottom; it scrolls freely or keeps the question
  // pinned, and this component follows the answer's end itself.
  const [pinHeld, setPinHeld] = useState(false);
  const pinHeldRef = useRef(false);
  const holdPin = (hold: boolean, sync = false) => {
    if (pinHeldRef.current === hold) return;
    pinHeldRef.current = hold;
    if (sync) flushSync(() => setPinHeld(hold));
    else setPinHeld(hold);
  };
  useLayoutEffect(() => {
    pinReleasedRef.current = false;
    holdPin(false);
  }, [queries.length]);
  // Whether the question is pinned to the top: the follow and the resize
  // re-pin below leave the scroll to the primitive then.
  const isPinned = (vp: HTMLElement) =>
    !pinReleasedRef.current && (pinHeldRef.current || spacerHeight(vp) > 0);

  useLayoutEffect(() => {
    if (status !== 'idle' || !hasMessages) return;
    const vp = document.querySelector<HTMLElement>(MS_VIEWPORT_SELECTOR);
    if (vp && spacerHeight(vp) > 0) holdPin(true);
  }, [status, hasMessages]);

  useEffect(() => {
    if (!hasMessages) return;
    const vp = document.querySelector<HTMLElement>(MS_VIEWPORT_SELECTOR);
    if (!vp) return;
    const releasePin = () => {
      pinReleasedRef.current = true;
      // Synchronous, so the primitive reads it on the scroll this gesture makes.
      if (spacerHeight(vp) > 0) holdPin(true, true);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (SCROLL_KEYS.has(event.key)) releasePin();
    };
    // Opening or closing a step while the chat follows the answer's end
    // resized the content and the follow scrolled it straight back to the
    // bottom: the step just clicked jumped away from the pointer. A toggle is
    // a gesture too, so it stops the follow the way a wheel does (the
    // primitive only reads intent from wheel, touch and key events) and the
    // step opens in place. While the pin holds the question at the top the
    // step already stays put, so the pin is left alone; a released pin's
    // leftover spacer holds nothing, as in the follow effect.
    const onToggleClick = (event: MouseEvent) => {
      const target = event.target as Element | null;
      if (!target?.closest('[aria-expanded]')) return;
      if (isPinned(vp)) return;
      if (contentEndDistance(vp) >= STICK_THRESHOLD_PX) return;
      stickToBottomRef.current = false;
      vp.dispatchEvent(new WheelEvent('wheel', { bubbles: true }));
    };
    vp.addEventListener('wheel', releasePin, { passive: true });
    vp.addEventListener('touchmove', releasePin, { passive: true });
    vp.addEventListener('keydown', onKeyDown);
    vp.addEventListener('click', onToggleClick, true);
    return () => {
      vp.removeEventListener('wheel', releasePin);
      vp.removeEventListener('touchmove', releasePin);
      vp.removeEventListener('keydown', onKeyDown);
      vp.removeEventListener('click', onToggleClick, true);
    };
  }, [hasMessages]);

  // While an answer streams, its turn only grows. A row swapped for a shorter
  // one (the status line handing over to a grouped tool step, a step group
  // folding) shrank the content, and the browser clamps the scroll a frame
  // before the scroller re-pins: the turn jumped and snapped back. Each growth
  // raises the answer's min-height to match, so a shrink leaves blank space at
  // its end instead. The end of the stream (or a pause for approval) is such
  // a shrink too: the live step window folds, and with no text there is no
  // action row to take the status line's place. So the hold stays until the
  // row stops being the latest answer, when the next question arrives.
  const [streamingAnswer, setStreamingAnswer] = useState<HTMLElement | null>(
    null,
  );
  const holdStreamingAnswer = status === 'loading';
  const prevStatusRef = useRef(status);
  useLayoutEffect(() => {
    const el = streamingAnswer;
    if (!el) return;
    return () => {
      el.style.minHeight = '';
    };
  }, [streamingAnswer]);
  useLayoutEffect(() => {
    const el = streamingAnswer;
    if (!el || !holdStreamingAnswer || typeof ResizeObserver === 'undefined')
      return;
    // A retry streams a new answer into the same row, so it starts its own
    // hold; a turn resuming after an approval keeps the one it had.
    if (prevStatusRef.current !== 'awaiting_tool_actions')
      el.style.minHeight = '';
    let tallest = parseFloat(el.style.minHeight) || 0;
    const observer = new ResizeObserver(([entry]) => {
      const height =
        entry.borderBoxSize?.[0]?.blockSize ??
        el.getBoundingClientRect().height;
      if (height <= tallest) return;
      tallest = height;
      el.style.minHeight = `${height}px`;
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [streamingAnswer, holdStreamingAnswer]);
  // After the hold effect, so it reads the status the last commit had.
  useLayoutEffect(() => {
    prevStatusRef.current = status;
  }, [status]);

  useEffect(() => {
    if (!hasMessages) return;
    const vp = document.querySelector<HTMLElement>(MS_VIEWPORT_SELECTOR);
    if (!vp) return;
    const onScroll = () => {
      const dist = vp.scrollHeight - vp.scrollTop - vp.clientHeight;
      // Reading style.height (the primitive's inline value) avoids a reflow.
      const spacer = vp.querySelector<HTMLElement>(MS_SPACER_SELECTOR);
      const spacerH = spacer ? parseFloat(spacer.style.height) || 0 : 0;
      const shownSpacerH = spacerCollapsedRef.current ? 0 : spacerH;
      // At the bottom means at the content's end, spacer or not.
      stickToBottomRef.current =
        contentEndDistance(vp, shownSpacerH) < STICK_THRESHOLD_PX;
      // The spacer is gone (the scroll-to-end button, a new pin): nothing
      // left to hold.
      if (shownSpacerH === 0) holdPin(false);
      // Collapse only once the spacer has scrolled fully below the fold
      // (dist >= its height) so removing it never shifts the visible content.
      if (
        !spacerCollapsedRef.current &&
        spacerH > STICK_THRESHOLD_PX &&
        dist >= spacerH
      ) {
        spacerCollapsedRef.current = true;
        setSpacerCollapsed(true);
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
    // While the pin spacer holds the latest question at the top, the primitive
    // re-pins on resize a frame later; scrolling to the bottom here first made
    // the turn jump up and back on every growth. Once a gesture has released
    // the pin, its leftover spacer no longer holds anything: follow the
    // answer's end, not the spacer's, and only once it passes the bottom.
    if (isPinned(vp)) return;
    const dist = contentEndDistance(vp);
    if (stickToBottomRef.current && dist > 0) vp.scrollTop += dist;
  }, [status, lastTurnContentLength, hasMessages]);

  // The primitive re-pins to the bottom a frame after a resize, so content
  // resizing in view while the chat sat at its end (an image with no size, a
  // diagram rendering, an MCP App sizing itself, a run's artifact cards, the
  // action row at the end of a stream) painted one frame with the end pushed
  // below the fold. A ResizeObserver runs after layout and before paint, so
  // following here lands in the same frame. Growth above the viewport is the
  // browser's scroll anchoring, and a pinned question the primitive's.
  const [contentEl, setContentEl] = useState<HTMLElement | null>(null);
  useEffect(() => {
    const vp = contentEl?.closest<HTMLElement>(MS_VIEWPORT_SELECTOR);
    if (!contentEl || !vp || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => {
      if (!stickToBottomRef.current || isPinned(vp)) return;
      const dist = contentEndDistance(vp);
      if (dist > 0) vp.scrollTop += dist;
    });
    observer.observe(contentEl);
    return () => observer.disconnect();
  }, [contentEl]);

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
      // A woken turn's prompt is the background event: retrying would send
      // it as the user's own message.
      const retryButton = query.wake ? undefined : (
        <IconButton
          label={t('conversation.retry')}
          variant="ghost-muted"
          size="icon-sm"
          shape="pill"
          disabled={status === 'loading'}
          onClick={() => {
            const questionToRetry = queries[index].prompt;
            handleQuestion({
              question: questionToRetry,
              isRetry: true,
              index,
            });
          }}
        >
          <RotateCcw aria-hidden="true" />
        </IconButton>
      );
      // Files that overflowed the window are better searched than sent:
      // offer to make them Knowledge, then the question can be asked again.
      const knowledgeFiles =
        canAddToKnowledge &&
        query.errorCode === CONTEXT_LENGTH_EXCEEDED &&
        query.attachments?.length
          ? query.attachments
          : null;
      const partialResponse =
        query.response === TERMINATED_RESPONSE_PLACEHOLDER
          ? ''
          : query.response;
      const hasPartialProgress =
        partialResponse ||
        query.thought ||
        query.tool_calls?.length ||
        query.research ||
        query.workflow_run_id;
      // A workflow that failed keeps its steps in view: which one failed,
      // and why.
      const showPartial =
        (query.errorCode === 'time_limit' && hasPartialProgress) ||
        Boolean(query.workflow?.steps.length);
      return (
        <Fragment key={`${index}-ERROR`}>
          {showPartial ? (
            <ConversationBubble
              className={bubbleMargin}
              message={partialResponse}
              type="ANSWER"
              thought={query.thought}
              sources={query.sources}
              toolCalls={query.tool_calls}
              segments={query.segments}
              workflowRunId={query.workflow_run_id}
              workflow={query.workflow}
              research={query.research}
              conversationArtifacts={conversationArtifacts}
              onOpenArtifact={onOpenArtifact}
              onToolAction={onToolAction}
              agentId={agentId}
              messageId={query.messageId}
              isStreaming={false}
            />
          ) : null}
          <ConversationBubble
            className={bubbleMargin}
            message={curatedErrorText(
              t,
              query.error,
              query.errorCode,
              query.errorParams,
              { offersKnowledge: Boolean(knowledgeFiles) },
            )}
            type="ERROR"
            retryBtn={retryButton}
            errorCode={query.errorCode}
            errorAction={
              knowledgeFiles ? (
                <AddToKnowledgeAction
                  files={knowledgeFiles}
                  onAdded={() => onKnowledgeAdded?.(index)}
                />
              ) : undefined
            }
          />
        </Fragment>
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
            <Alert
              variant="warning"
              role="status"
              className={cn(bubbleMargin, 'mr-5 w-auto')}
            >
              <AlertDescription>{query.notice}</AlertDescription>
            </Alert>
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
            workflow={query.workflow}
            research={query.research}
            conversationArtifacts={conversationArtifacts}
            onOpenArtifact={onOpenArtifact}
            onToolAction={onToolAction}
            feedback={query.feedback}
            isStreaming={isCurrentlyStreaming}
            agentId={agentId}
            messageId={query.messageId}
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
          className={cn(
            'animate-in fade-in slide-in-from-bottom-1.5 group flex flex-col flex-wrap self-start duration-260 ease-out motion-reduce:animate-none',
            bubbleMargin,
          )}
        >
          <div className="flex max-w-full flex-col flex-wrap items-start self-start lg:flex-nowrap">
            <StreamingStatusLine className="my-2 ml-6" />
          </div>
        </div>
      );
    }

    return null;
  };

  if (queries.length === 0 && isLoading) {
    return (
      <div className="flex h-full w-full justify-center overflow-hidden sm:pt-6 lg:pt-12">
        <div className={columnClass}>
          {headerContent}
          <ChatLoadingSkeleton />
        </div>
      </div>
    );
  }

  if (queries.length === 0) {
    return (
      <div className="flex h-full w-full justify-center overflow-y-auto will-change-scroll sm:pt-6 lg:pt-12">
        <div className={emptyStateColumnClass}>
          {showHeroOnEmpty ? (
            <>
              {headerContent}
              <Hero handleQuestion={handleQuestion} />
            </>
          ) : (
            // The agent's card on top, its starters down by the composer,
            // where the hero's suggestions sit.
            <div className="flex h-full flex-col">
              {headerContent}
              <AgentStarters
                className="mt-auto mb-3"
                starters={starters}
                onAsk={(question) => handleQuestion({ question })}
              />
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <MessageScrollerProvider autoScroll={!pinHeld}>
      <MessageScroller>
        <MessageScrollerViewport className="sm:pt-6 lg:pt-12">
          <MessageScrollerContent
            ref={setContentEl}
            spacerClassName={spacerCollapsed ? 'max-h-0' : undefined}
            className={cn('mx-auto pb-7', columnClass)}
          >
            {headerContent}
            {queries.map((query, index) => {
              const responseView = renderResponseView(query, index);
              return (
                <Fragment key={`${index}-query-fragment`}>
                  <MessageScrollerItem messageId={`q-${index}`} scrollAnchor>
                    {query.wake ? (
                      <WakeEventRow
                        wake={query.wake}
                        prompt={query.prompt}
                        className={cn(
                          QUESTION_BUBBLE_MARGIN_BOTTOM,
                          index === 0 ? FIRST_QUESTION_BUBBLE_MARGIN_TOP : '',
                        )}
                      />
                    ) : (
                      <ConversationBubble
                        className={cn(
                          QUESTION_BUBBLE_MARGIN_BOTTOM,
                          index === 0 ? FIRST_QUESTION_BUBBLE_MARGIN_TOP : '',
                        )}
                        message={query.prompt}
                        type="QUESTION"
                        handleUpdatedQuestionSubmission={
                          handleQuestionSubmission
                        }
                        questionNumber={index}
                        sources={query.sources}
                        filesAttached={query.attachments}
                      />
                    )}
                  </MessageScrollerItem>
                  {responseView && (
                    <MessageScrollerItem
                      messageId={`a-${index}`}
                      ref={
                        index === queries.length - 1
                          ? setStreamingAnswer
                          : undefined
                      }
                    >
                      {responseView}
                    </MessageScrollerItem>
                  )}
                  {query.tool_calls?.some((call) => call.job_id) && (
                    <MessageScrollerItem messageId={`c-${index}`}>
                      <JobCancelledRows toolCalls={query.tool_calls} />
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
