import { ChevronDown, Cloud } from 'lucide-react';
import { Fragment, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import SchedulerToolCallCard from '../agents/schedules/SchedulerToolCallCard';
import BackgroundJobCard from '../backgroundJobs/BackgroundJobCard';
import { Button } from '../components/ui/button';
import { usePacedText } from '../hooks';
import MonitorLinkCard, { parseMonitorLink } from '../monitors/MonitorLinkCard';
import {
  getToolChipLabel,
  isToolCallRunning,
} from '../utils/streamingStatusUtils';
import { layoutAnswer } from './answerLayout';
import { AnswerSegment, getAnswerSegments } from './answerSegments';
import MarkdownAnswer from './MarkdownAnswer';
import { type SandboxArtifact } from './sandboxLinks';
import StepGroup, { NotRunBadge, StepIcon, ToolCallDetail } from './StepGroup';
import StreamingStatusLine from './StreamingStatusLine';
import { ToolCallsType } from './types';
import { isWikiWriteCall } from './wikiToolCall';
import { cn } from '@/lib/utils';

type AnswerFlowProps = {
  message?: string;
  thought?: string;
  toolCalls?: ToolCallsType[];
  // Absent on reload, where the order is synthesized from the flat fields.
  segments?: AnswerSegment[];
  isStreaming?: boolean;
  /** How many sources the answer can cite; see `MarkdownAnswer`. */
  sourceCount?: number;
  /** Opens a cited source's reader; see `MarkdownAnswer`. */
  onOpenSource?: (index: number) => void;
  agentId?: string;
  /** Set when the bubble already carries its own progress UI (a research run). */
  suppressStatusLine?: boolean;
  /** Every artifact in the conversation, so ``sandbox:`` links can reach them. */
  artifacts?: SandboxArtifact[];
  /** This turn's own artifacts, which win when a link names a bare filename. */
  turnArtifacts?: SandboxArtifact[];
  onOpenArtifact?: (artifact: { id: string; toolName: string }) => void;
  renderApproval: (toolCall: ToolCallsType) => React.ReactNode;
  renderWikiWrite: (
    toolCall: ToolCallsType,
    isLive: boolean,
  ) => React.ReactNode;
};

/**
 * The answer column in the order its parts streamed: answer text, reasoning,
 * single steps, and step groups for runs of three or more calls (see
 * ``layoutAnswer``). The order is saved with the message, so a streaming answer
 * and the same answer fetched back render identically; without a saved order
 * the steps come first and the answer after them.
 */
export default function AnswerFlow({
  message,
  thought,
  toolCalls,
  segments,
  isStreaming,
  sourceCount,
  onOpenSource,
  agentId,
  suppressStatusLine,
  artifacts,
  turnArtifacts,
  onOpenArtifact,
  renderApproval,
  renderWikiWrite,
}: AnswerFlowProps) {
  const steps = getAnswerSegments({
    thought,
    tool_calls: toolCalls,
    segments,
    response: message,
  });
  const callById = new Map((toolCalls ?? []).map((c) => [c.call_id, c]));
  const items = layoutAnswer(steps, callById);
  const lastStep = steps.length - 1;
  const lastItem = items.length - 1;

  // One derivation of "something here is already announcing activity": every
  // chip shimmers off this, and the status line below fills only the gaps it
  // leaves. Deriving it a second time from the flat fields let the two disagree,
  // which showed up as no indicator at all between a settled step and the answer.
  const isLiveThought = (index: number) =>
    Boolean(isStreaming) && index === lastStep;
  const isLiveCall = (call: ToolCallsType) =>
    Boolean(isStreaming) && isToolCallRunning(call);
  const hasLiveStep = steps.some((step, index) => {
    if (step.kind === 'thought') return isLiveThought(index);
    if (step.kind !== 'tool') return false;
    const call = callById.get(step.call_id);
    return Boolean(call && isLiveCall(call));
  });

  return (
    <>
      {items.map((item, position) => {
        if (item.kind === 'thought')
          return (
            <InlineThoughtChip
              key={`thought-${item.index}`}
              thought={item.text}
              isActive={isLiveThought(item.index)}
            />
          );

        if (item.kind === 'group')
          return (
            <StepGroup
              key={`group-${item.index}`}
              entries={item.entries}
              isLive={Boolean(isStreaming) && position === lastItem}
              isStreaming={Boolean(isStreaming)}
            />
          );

        if (item.kind === 'text')
          return (
            <div
              key={`text-${item.index}`}
              className="flex w-full min-w-0 flex-col"
            >
              {/* ``ml-6`` is the answer's text column: step labels sit at the
                  same offset, with their icons in the gutter to its left.
                  Stretched, not ``self-start max-w-full``: a shrink-to-fit box
                  sizes to its longest code line, and ``max-w-full`` caps it at
                  100% before the margins land on top, so the chat scrolled
                  sideways on a phone. */}
              <div className="animate-in fade-in slide-in-from-bottom-1.5 my-2 mr-5 ml-6 flex min-w-0 flex-col duration-260 ease-out motion-reduce:animate-none">
                <MarkdownAnswer
                  content={item.text}
                  isStreaming={Boolean(isStreaming) && position === lastItem}
                  sourceCount={sourceCount}
                  onOpenSource={onOpenSource}
                  artifacts={artifacts}
                  turnArtifacts={turnArtifacts}
                  onOpenArtifact={onOpenArtifact}
                />
              </div>
            </div>
          );

        const call = item.call;
        if (call.status === 'awaiting_approval')
          return (
            <Fragment key={`approval-${call.call_id}`}>
              {renderApproval(call)}
            </Fragment>
          );

        if (isWikiWriteCall(call))
          return (
            <Fragment key={`wiki-${call.call_id}`}>
              {renderWikiWrite(call, isLiveCall(call))}
            </Fragment>
          );

        if (call.job_id)
          return (
            <BackgroundJobCard key={`job-${call.call_id}`} toolCall={call} />
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

        const monitorLink =
          call.tool_name === 'monitor' ? parseMonitorLink(call.result) : null;
        if (monitorLink)
          return (
            <MonitorLinkCard
              key={`monitor-link-${call.call_id}`}
              link={monitorLink}
            />
          );

        return (
          <InlineToolCallChip
            key={`tool-${call.call_id}`}
            toolCall={call}
            isLive={isLiveCall(call)}
          />
        );
      })}
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
        size="sm"
        // ml-3.5 plus size sm's own has-[>svg]:px-2.5 (the chevron is a direct
        // svg child) puts the icon on the answer's ml-6 text column.
        className="ml-3.5 w-fit max-w-full justify-start"
      >
        <Cloud className="text-muted-foreground" aria-hidden />
        <span
          className={cn(
            'min-w-0 truncate text-left',
            isActive ? 'shimmer-text' : 'text-muted-foreground',
          )}
        >
          {t('conversation.reasoning')}
        </span>
        <ChevronDown
          aria-hidden
          className={cn(
            'text-muted-foreground shrink-0 transition-transform duration-200',
            isOpen ? 'rotate-180' : '',
          )}
        />
      </Button>
      {showLiveWindow && (
        <div
          ref={liveRef}
          className="text-muted-foreground mt-1 ml-6 h-24 overflow-hidden scroll-smooth mask-t-from-60% text-sm leading-normal motion-reduce:scroll-auto"
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
        <p className="animate-in fade-in text-muted-foreground mt-0.5 ml-6 text-sm leading-normal wrap-break-word whitespace-pre-wrap duration-160 ease-out motion-reduce:animate-none">
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
  // Liveness is what animates; the label's tense follows the call's own
  // status, so a call left pending by a dropped stream still reads as running.
  const label = getToolChipLabel(toolCall, t);

  return (
    <div className="my-2 flex w-full flex-col">
      <Button
        type="button"
        variant="ghost"
        onClick={() => setIsOpen(!isOpen)}
        aria-expanded={isOpen}
        size="sm"
        // ml-3.5 plus size sm's own has-[>svg]:px-2.5 (the chevron is a direct
        // svg child) puts the icon on the answer's ml-6 text column.
        className="ml-3.5 w-fit max-w-full justify-start"
      >
        <StepIcon call={toolCall} pulse={isLive} />
        <span
          title={label}
          className={cn(
            'min-w-0 truncate text-left',
            isLive ? 'shimmer-text' : 'text-muted-foreground',
          )}
        >
          {label}
        </span>
        {toolCall.status === 'error' && (
          <span className="text-destructive shrink-0 text-xs">
            {t('conversation.inlineSteps.failed')}
          </span>
        )}
        <NotRunBadge toolCall={toolCall} />
        <ChevronDown
          aria-hidden
          className={cn(
            'text-muted-foreground shrink-0 transition-transform duration-200',
            isOpen ? 'rotate-180' : '',
          )}
        />
      </Button>
      {isOpen && (
        <ToolCallDetail
          toolCall={toolCall}
          isLive={isLive}
          className="mt-2 mr-5 ml-6"
        />
      )}
    </div>
  );
}
