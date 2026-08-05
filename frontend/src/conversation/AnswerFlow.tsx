import { Fragment, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import SchedulerToolCallCard from '../agents/schedules/SchedulerToolCallCard';
import ChevronDown from '../assets/chevron-down.svg?react';
import Cloud from '../assets/cloud.svg';
import DocsGPT3 from '../assets/cute_docsgpt3.svg';
import CopyButton from '../components/CopyButton';
import ToolIcon from '../components/ToolIcon';
import { Avatar } from '../components/ui/avatar';
import { Button } from '../components/ui/button';
import { usePacedText } from '../hooks';
import { getToolChipLabel } from '../utils/streamingStatusUtils';
import { AnswerSegment, getAnswerSegments } from './answerSegments';
import MarkdownAnswer from './MarkdownAnswer';
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
  renderApproval: (toolCall: ToolCallsType) => React.ReactNode;
  renderWikiWrite: (toolCall: ToolCallsType) => React.ReactNode;
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
  renderApproval,
  renderWikiWrite,
}: AnswerFlowProps) {
  const { t } = useTranslation();
  const steps = getAnswerSegments({ thought, tool_calls: toolCalls, segments });
  const callById = new Map((toolCalls ?? []).map((c) => [c.call_id, c]));
  const lastIndex = steps.length - 1;

  return (
    <>
      {steps.map((step, index) => {
        if (step.kind === 'thought') {
          return (
            <InlineThoughtChip
              key={`thought-${index}`}
              thought={step.text}
              isActive={isStreaming && index === lastIndex && !message}
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
              {renderWikiWrite(call)}
            </Fragment>
          );

        if (call.tool_name === 'scheduler')
          return (
            <div key={`scheduler-${call.call_id}`} className="my-2 w-full">
              <SchedulerToolCallCard
                result={call.result}
                actionName={call.action_name}
                status={call.status}
                agentId={agentId}
              />
            </div>
          );

        return (
          <InlineToolCallChip key={`tool-${call.call_id}`} toolCall={call} />
        );
      })}
      {message && (
        <div className="flex max-w-full flex-col flex-wrap items-start self-start lg:flex-nowrap">
          <div className="my-2 flex flex-row items-center justify-center gap-3">
            <Avatar
              src={DocsGPT3}
              alt={t('conversation.answer')}
              className="h-8.5 w-8.5 text-2xl"
              imgClassName="h-full w-full object-cover"
            />
            <p className="text-base font-semibold">
              {t('conversation.answer')}
            </p>
          </div>
          <div className="fade-in-bubble mr-5 flex max-w-full flex-col rounded-3xl py-4.5">
            <MarkdownAnswer content={message} isStreaming={isStreaming} />
          </div>
        </div>
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
        className="hover:bg-muted/60 flex h-auto w-fit max-w-full items-center justify-start gap-2 rounded-lg bg-transparent px-2 py-1.5 text-sm font-normal"
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
          className="text-muted-foreground mt-1 ml-3 h-24 overflow-hidden scroll-smooth mask-[linear-gradient(to_bottom,transparent,black_40%)] text-sm leading-normal motion-reduce:scroll-auto"
        >
          <div className="flex min-h-full flex-col justify-end wrap-break-word whitespace-pre-wrap">
            {pacedThought}
          </div>
        </div>
      )}
      {!showLiveWindow && !isOpen && (
        <p className="text-muted-foreground mt-0.5 ml-3 truncate text-sm">
          {thought}
        </p>
      )}
      {isOpen && (
        <p className="fade-in text-muted-foreground mt-0.5 ml-3 text-sm leading-normal wrap-break-word whitespace-pre-wrap">
          {thought}
        </p>
      )}
    </div>
  );
}

function InlineToolCallChip({ toolCall }: { toolCall: ToolCallsType }) {
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);
  const isPending = toolCall.status === 'pending';
  const label = getToolChipLabel(toolCall, t);

  return (
    <div className="my-2 flex w-full flex-col">
      <Button
        type="button"
        variant="ghost"
        onClick={() => setIsOpen(!isOpen)}
        aria-expanded={isOpen}
        className="hover:bg-muted/60 flex h-auto w-fit max-w-full items-center justify-start gap-2 rounded-lg bg-transparent px-2 py-1.5 text-sm font-normal"
      >
        {/* ToolIcon renders nothing for a tool with no bundled icon, so the
            dot below stands in via ``only:block`` to keep the row aligned. */}
        <span
          className={`flex h-4 w-4 shrink-0 items-center justify-center ${
            isPending ? 'animate-pulse' : ''
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
            isPending ? 'shimmer-text' : 'text-muted-foreground'
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
        <div className="fade-in mt-2 flex flex-col gap-2">
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
            {isPending && (
              <p className="shimmer-text text-xs">
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
            {!isPending &&
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
