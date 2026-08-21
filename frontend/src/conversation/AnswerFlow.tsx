import { Fragment, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import SchedulerToolCallCard from '../agents/schedules/SchedulerToolCallCard';
import ChevronDown from '../assets/chevron-down.svg?react';
import Cloud from '../assets/cloud.svg';
import CopyButton from '../components/CopyButton';
import ToolIcon from '../components/ToolIcon';
import { Button } from '../components/ui/button';
import { usePacedText } from '../hooks';
import {
  getToolChipLabel,
  isToolCallRunning,
} from '../utils/streamingStatusUtils';
import { AnswerSegment, getAnswerSegments } from './answerSegments';
import MarkdownAnswer from './MarkdownAnswer';
import { type SandboxArtifact } from './sandboxLinks';
import StreamingStatusLine from './StreamingStatusLine';
import { ToolCallsType } from './types';
import { isWikiWriteCall } from './wikiToolCall';

type AnswerFlowProps = {
  message?: string;
  thought?: string;
  toolCalls?: ToolCallsType[];
  // Absent on reload, where the order is synthesized from the flat fields.
  segments?: AnswerSegment[];
  isStreaming?: boolean;
  agentId?: string;
  /** Set when the bubble already carries its own progress UI (a research run). */
  suppressStatusLine?: boolean;
  /** Artifacts produced on this turn, so ``sandbox:`` links can reach them. */
  artifacts?: SandboxArtifact[];
  onOpenArtifact?: (artifact: { id: string; toolName: string }) => void;
  renderApproval: (toolCall: ToolCallsType) => React.ReactNode;
  renderWikiWrite: (
    toolCall: ToolCallsType,
    isLive: boolean,
  ) => React.ReactNode;
};

/**
 * Never splits the answer with a step, which is what keeps a streaming answer and
 * the same answer fetched back rendering identically.
 */
export default function AnswerFlow({
  message,
  thought,
  toolCalls,
  segments,
  isStreaming,
  agentId,
  suppressStatusLine,
  artifacts,
  onOpenArtifact,
  renderApproval,
  renderWikiWrite,
}: AnswerFlowProps) {
  const steps = getAnswerSegments({ thought, tool_calls: toolCalls, segments });
  const callById = new Map((toolCalls ?? []).map((c) => [c.call_id, c]));
  const lastIndex = steps.length - 1;

  // One derivation of "something here is already announcing activity": every
  // chip shimmers off this, and the status line below fills only the gaps it
  // leaves. Deriving it a second time from the flat fields let the two disagree,
  // which showed up as no indicator at all between a settled step and the answer.
  const liveSteps = steps.map((step, index) => {
    if (!isStreaming) return false;
    if (step.kind === 'thought') return index === lastIndex && !message;
    const call = callById.get(step.call_id);
    return Boolean(call && isToolCallRunning(call));
  });
  const hasLiveStep = liveSteps.some(Boolean);

  return (
    <>
      {steps.map((step, index) => {
        if (step.kind === 'thought') {
          return (
            <InlineThoughtChip
              key={`thought-${index}`}
              thought={step.text}
              isActive={liveSteps[index]}
            />
          );
        }

        const call = callById.get(step.call_id);
        if (!call) return null;

        if (call.status === 'awaiting_approval')
          return (
            <Fragment key={`approval-${call.call_id}`}>
              {renderApproval(call)}
            </Fragment>
          );

        if (isWikiWriteCall(call))
          return (
            <Fragment key={`wiki-${call.call_id}`}>
              {renderWikiWrite(call, liveSteps[index])}
            </Fragment>
          );

        if (call.tool_name === 'scheduler')
          return (
            <div key={`scheduler-${call.call_id}`} className="my-2 mr-5 ml-6">
              <SchedulerToolCallCard
                result={call.result}
                actionName={call.action_name}
                status={call.status}
                agentId={agentId}
              />
            </div>
          );

        return (
          <InlineToolCallChip
            key={`tool-${call.call_id}`}
            toolCall={call}
            isLive={liveSteps[index]}
          />
        );
      })}
      {message && (
        <div className="flex max-w-full flex-col flex-wrap items-start self-start lg:flex-nowrap">
          {/* ``ml-6`` is the answer's text column: step labels sit at the same
              offset, with their icons in the gutter to its left. */}
          <div className="fade-in-bubble my-2 mr-5 ml-6 flex max-w-full flex-col">
            <MarkdownAnswer
              content={message}
              isStreaming={isStreaming}
              artifacts={artifacts}
              onOpenArtifact={onOpenArtifact}
            />
          </div>
        </div>
      )}
      {isStreaming && !hasLiveStep && !suppressStatusLine && (
        <StreamingStatusLine
          hasAnswerText={Boolean(message)}
          className="my-2 ml-6"
        />
      )}
    </>
  );
}

function InlineThoughtChip({
  thought,
  isActive,
}: {
  thought: string;
  isActive?: boolean;
}) {
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);
  const liveRef = useRef<HTMLDivElement>(null);

  // Expanding means the user wants it all now, so pace the live window only.
  const pacedThought = usePacedText(thought, Boolean(isActive) && !isOpen);
  const showLiveWindow = Boolean(isActive) && !isOpen;

  // The window keeps a fixed height so deltas never resize the page and
  // retrigger the conversation scroll pin; scrolling it instead (with CSS
  // scroll-smooth) glides the text up rather than snapping a line at a time.
  useEffect(() => {
    const el = liveRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [pacedThought, isOpen]);

  return (
    <div className="my-2 flex w-full flex-col">
      <Button
        type="button"
        variant="ghost"
        onClick={() => setIsOpen(!isOpen)}
        aria-expanded={isOpen}
        // ml-4 plus the button's own px-2 puts the icon on the answer's ml-6
        // text column. has-[>svg]:px-2 restates that padding under the same
        // variant the button's own has-[>svg]:px-3 uses; a plain px-2 does not
        // override it, and the chevron makes it match.
        className="hover:bg-muted/60 ml-4 flex h-auto w-fit max-w-full items-center justify-start gap-2 rounded-lg bg-transparent px-2 py-1.5 text-sm font-normal has-[>svg]:px-2"
      >
        <img src={Cloud} alt="" aria-hidden className="h-4 w-4 shrink-0" />
        <span
          className={`min-w-0 truncate text-left ${
            isActive ? 'shimmer-text' : 'text-muted-foreground'
          }`}
        >
          {t('conversation.reasoning')}
        </span>
        <ChevronDown
          aria-hidden
          className={`text-muted-foreground h-4 w-4 shrink-0 transform transition-transform duration-200 ${
            isOpen ? 'rotate-180' : ''
          }`}
        />
      </Button>
      {showLiveWindow && (
        <div
          ref={liveRef}
          className="text-muted-foreground mt-1 ml-6 h-24 overflow-hidden scroll-smooth mask-[linear-gradient(to_bottom,transparent,black_40%)] text-sm leading-normal motion-reduce:scroll-auto"
        >
          <div className="flex min-h-full flex-col justify-end wrap-break-word whitespace-pre-wrap">
            {pacedThought}
          </div>
        </div>
      )}
      {!showLiveWindow && !isOpen && (
        <p className="text-muted-foreground mt-0.5 ml-6 truncate text-sm">
          {thought}
        </p>
      )}
      {isOpen && (
        <p className="fade-in text-muted-foreground mt-0.5 ml-6 text-sm leading-normal wrap-break-word whitespace-pre-wrap">
          {thought}
        </p>
      )}
    </div>
  );
}

function InlineToolCallChip({
  toolCall,
  isLive,
}: {
  toolCall: ToolCallsType;
  isLive?: boolean;
}) {
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);
  // Liveness is what animates; running is what the call's own status means, so
  // a call left pending by a dropped stream still reads in the present tense.
  const isRunning = isToolCallRunning(toolCall);
  const label = getToolChipLabel(toolCall, t);

  return (
    <div className="my-2 flex w-full flex-col">
      <Button
        type="button"
        variant="ghost"
        onClick={() => setIsOpen(!isOpen)}
        aria-expanded={isOpen}
        // ml-4 plus the button's own px-2 puts the icon on the answer's ml-6
        // text column. has-[>svg]:px-2 restates that padding under the same
        // variant the button's own has-[>svg]:px-3 uses; a plain px-2 does not
        // override it, and the chevron makes it match.
        className="hover:bg-muted/60 ml-4 flex h-auto w-fit max-w-full items-center justify-start gap-2 rounded-lg bg-transparent px-2 py-1.5 text-sm font-normal has-[>svg]:px-2"
      >
        {/* ToolIcon renders nothing for a tool with no bundled icon, so the
            dot below stands in via ``only:block`` to keep the row aligned. */}
        <span
          className={`flex h-4 w-4 shrink-0 items-center justify-center ${
            isLive ? 'animate-pulse' : ''
          }`}
        >
          <ToolIcon
            name={toolCall.tool_name}
            className="text-muted-foreground h-4 w-4"
          />
          <span className="bg-muted-foreground/50 hidden h-1.5 w-1.5 rounded-full only:block" />
        </span>
        <span
          className={`min-w-0 truncate text-left ${
            isLive ? 'shimmer-text' : 'text-muted-foreground'
          }`}
        >
          {label}
        </span>
        {toolCall.status === 'error' && (
          <span className="text-destructive shrink-0 text-xs">
            {t('conversation.inlineSteps.failed')}
          </span>
        )}
        <ChevronDown
          aria-hidden
          className={`text-muted-foreground h-4 w-4 shrink-0 transform transition-transform duration-200 ${
            isOpen ? 'rotate-180' : ''
          }`}
        />
      </Button>
      {isOpen && (
        <div className="fade-in mt-2 mr-5 ml-6 flex flex-col gap-2">
          <ToolCallPanel
            title={t('conversation.inlineSteps.arguments')}
            copyText={JSON.stringify(toolCall.arguments ?? {}, null, 2)}
          >
            <p className="max-h-80 overflow-y-auto font-mono text-xs whitespace-pre-wrap">
              {JSON.stringify(toolCall.arguments ?? {}, null, 2)}
            </p>
          </ToolCallPanel>
          <ToolCallPanel
            title={t('conversation.inlineSteps.response')}
            copyText={
              toolCall.status === 'error'
                ? (toolCall.error ?? '')
                : JSON.stringify(toolCall.result ?? {}, null, 2)
            }
          >
            {isRunning && (
              <p
                className={`text-xs ${isLive ? 'shimmer-text' : 'text-muted-foreground'}`}
              >
                {t('conversation.inlineSteps.running')}
              </p>
            )}
            {toolCall.status === 'error' && (
              <p className="text-destructive font-mono text-xs whitespace-pre-wrap">
                {toolCall.error}
              </p>
            )}
            {toolCall.status === 'denied' && (
              <p className="text-muted-foreground text-xs">
                {t('conversation.inlineSteps.denied')}
              </p>
            )}
            {!isRunning &&
              toolCall.status !== 'error' &&
              toolCall.status !== 'denied' && (
                <p className="max-h-80 overflow-y-auto font-mono text-xs whitespace-pre-wrap">
                  {JSON.stringify(toolCall.result ?? {}, null, 2)}
                </p>
              )}
          </ToolCallPanel>
        </div>
      )}
    </div>
  );
}

function ToolCallPanel({
  title,
  copyText,
  children,
}: {
  title: string;
  copyText: string;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-muted/50 dark:bg-answer-bubble overflow-hidden rounded-xl">
      <div className="flex items-center justify-between px-3 py-1.5">
        <span className="text-muted-foreground text-xs font-medium">
          {title}
        </span>
        <CopyButton textToCopy={copyText} />
      </div>
      <div className="px-3 pb-2">{children}</div>
    </div>
  );
}
