import {
  Bell,
  BookOpen,
  ChevronDown,
  Cloud,
  Database,
  type LucideIcon,
  Search,
  Send,
} from 'lucide-react';
import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';

import ConnectorIcon from '../connectors/ConnectorIcon';
import { connectorIconKey } from '../connectors/i18n';
import ToolIcon from '../components/ToolIcon';
import { Button } from '../components/ui/button';
import { CodeBlock, CodePanel } from '../components/ui/code-block';
import { Collapsible } from '../components/ui/collapsible';
import {
  getToolChipLabel,
  isToolCallRunning,
} from '../utils/streamingStatusUtils';
import { GroupEntry } from './answerLayout';
import { shownArguments, ToolCallsType } from './types';
import { cn, focusRing } from '@/lib/utils';

// The step column is one muted weight: a tool whose bundled icon is a brand
// mark in its own colours (or that has none, like the wiki) draws a lucide
// stand-in here. The Tools page keeps the brand marks.
const STEP_ICONS: Record<string, { key: string; Icon: LucideIcon }> = {
  wiki: { key: 'wiki', Icon: BookOpen },
  brave: { key: 'search', Icon: Search },
  duckduckgo: { key: 'search', Icon: Search },
  telegram: { key: 'telegram', Icon: Send },
  ntfy: { key: 'ntfy', Icon: Bell },
  postgres: { key: 'postgres', Icon: Database },
};

/** Which icon a call draws, so a group header shows each one once. */
function stepIconKey(call: ToolCallsType): string {
  if (call.connector_key) return `connector:${call.connector_key}`;
  return STEP_ICONS[call.tool_name]?.key ?? call.tool_name;
}

/**
 * A step's 16px muted icon. ToolIcon renders nothing for a tool with no
 * bundled icon, so a dot stands in via ``only:block`` to keep the row aligned.
 */
export function StepIcon({
  call,
  pulse,
}: {
  call: ToolCallsType;
  pulse?: boolean;
}) {
  const stand = STEP_ICONS[call.tool_name];
  return (
    <span
      className={cn(
        'flex size-4 shrink-0 items-center justify-center',
        pulse && 'animate-pulse',
      )}
    >
      {call.connector_key ? (
        <ConnectorIcon
          icon={connectorIconKey(call.connector_key)}
          className="text-muted-foreground size-4"
        />
      ) : stand ? (
        <stand.Icon className="text-muted-foreground size-4" aria-hidden />
      ) : (
        <ToolIcon
          name={call.tool_name}
          className="text-muted-foreground size-4"
        />
      )}
      <span className="bg-muted-foreground/50 hidden size-1.5 rounded-full only:block" />
    </span>
  );
}

/** A call's Arguments and Response panels, opened from its row. */
export function ToolCallDetail({
  toolCall,
  isLive,
  className,
}: {
  toolCall: ToolCallsType;
  isLive?: boolean;
  className?: string;
}) {
  const { t } = useTranslation();
  const isRunning = isToolCallRunning(toolCall);
  const args = JSON.stringify(shownArguments(toolCall), null, 2);
  // A tool that reports failure in its result (a 401 in ``status_code``) has
  // no ``error`` text; its result is what explains the failure.
  const failure =
    toolCall.status === 'error'
      ? (toolCall.error ??
        (typeof toolCall.result === 'string'
          ? toolCall.result
          : JSON.stringify(toolCall.result ?? {}, null, 2)))
      : '';
  const result = JSON.stringify(toolCall.result ?? {}, null, 2);

  return (
    <div
      className={cn(
        'animate-in fade-in flex flex-col gap-2 duration-160 ease-out motion-reduce:animate-none',
        className,
      )}
    >
      <CodePanel
        title={t('conversation.inlineSteps.arguments')}
        copyText={args}
      >
        <CodeBlock surface="bare" maxHeight="lg">
          {args}
        </CodeBlock>
      </CodePanel>
      <CodePanel
        title={t('conversation.inlineSteps.response')}
        copyText={toolCall.status === 'error' ? failure : result}
      >
        {isRunning && (
          <p
            className={cn(
              'text-xs',
              isLive ? 'shimmer-text' : 'text-muted-foreground',
            )}
          >
            {t('conversation.inlineSteps.running')}
          </p>
        )}
        {toolCall.status === 'error' && (
          <CodeBlock surface="bare" tone="destructive">
            {failure}
          </CodeBlock>
        )}
        {toolCall.status === 'denied' && (
          <p className="text-muted-foreground text-xs">
            {t('conversation.inlineSteps.denied')}
          </p>
        )}
        {!isRunning &&
          toolCall.status !== 'error' &&
          toolCall.status !== 'denied' && (
            <CodeBlock surface="bare" maxHeight="lg">
              {result}
            </CodeBlock>
          )}
      </CodePanel>
    </div>
  );
}

// A 28px row in an opened group. Its icon sits on the timeline rule (the icon's
// background masks the rule), its label is muted until hovered, and the
// chevron shows on hover or while open.
const rowClass = cn(
  focusRing,
  'group/row flex h-7 w-full min-w-0 items-center gap-2 rounded-sm text-left text-sm outline-none',
);

function RowChevron({ open }: { open: boolean }) {
  return (
    <ChevronDown
      aria-hidden
      className={cn(
        'text-muted-foreground size-3.5 shrink-0 transition-[transform,opacity] duration-200',
        open
          ? 'rotate-180 opacity-100'
          : 'opacity-0 group-hover/row:opacity-100 group-focus-visible/row:opacity-100',
      )}
    />
  );
}

function GroupCallRow({
  toolCall,
  isLive,
}: {
  toolCall: ToolCallsType;
  isLive: boolean;
}) {
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);
  const detailId = useId();
  const label = getToolChipLabel(toolCall, t);

  return (
    <div className="flex min-w-0 flex-col">
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        aria-expanded={isOpen}
        aria-controls={detailId}
        className={rowClass}
      >
        <span className="bg-background relative">
          <StepIcon call={toolCall} pulse={isLive} />
        </span>
        <span
          title={label}
          className={cn(
            'min-w-0 truncate',
            isLive
              ? 'shimmer-text'
              : 'text-muted-foreground group-hover/row:text-foreground',
          )}
        >
          {label}
        </span>
        {toolCall.status === 'error' && (
          <span className="text-destructive shrink-0 text-xs">
            {t('conversation.inlineSteps.failed')}
          </span>
        )}
        <RowChevron open={isOpen} />
      </button>
      <div id={detailId} hidden={!isOpen}>
        {isOpen && (
          <ToolCallDetail
            toolCall={toolCall}
            isLive={isLive}
            className="my-1 pl-6"
          />
        )}
      </div>
    </div>
  );
}

function GroupThoughtRow({ text }: { text: string }) {
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);
  const bodyId = useId();

  return (
    <div className="flex min-w-0 flex-col">
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        aria-expanded={isOpen}
        aria-controls={bodyId}
        className={rowClass}
      >
        <span className="bg-background relative flex size-4 shrink-0 items-center justify-center">
          <Cloud className="text-muted-foreground size-4" aria-hidden />
        </span>
        <span className="text-muted-foreground group-hover/row:text-foreground min-w-0 truncate">
          {t('conversation.reasoning')}
        </span>
        <RowChevron open={isOpen} />
      </button>
      <p
        id={bodyId}
        hidden={!isOpen}
        className="animate-in fade-in text-muted-foreground pb-1 pl-6 text-sm leading-normal wrap-break-word whitespace-pre-wrap duration-160 ease-out motion-reduce:animate-none"
      >
        {text}
      </p>
    </div>
  );
}

function StepTimeline({
  entries,
  isStreaming,
}: {
  entries: GroupEntry[];
  isStreaming: boolean;
}) {
  return (
    <div className="relative flex min-w-0 flex-col">
      {/* The rule runs through the icon centres (left-2 of a 16px icon). */}
      <span
        aria-hidden
        className="bg-border absolute top-3.5 bottom-3.5 left-2 w-px"
      />
      {entries.map((entry) => {
        if (entry.kind === 'call')
          return (
            <GroupCallRow
              key={`call-${entry.call.call_id}`}
              toolCall={entry.call}
              isLive={isStreaming && isToolCallRunning(entry.call)}
            />
          );
        if (entry.kind === 'thought')
          return (
            <GroupThoughtRow key={`thought-${entry.index}`} text={entry.text} />
          );
        return (
          <p
            key={`note-${entry.index}`}
            className="text-muted-foreground relative py-1 pl-6 text-sm leading-normal wrap-break-word"
          >
            {entry.text}
          </p>
        );
      })}
    </div>
  );
}

/**
 * Three or more steps in a row, as one row that opens into a compact list.
 * While it is the live end of a streaming answer it shows its last three rows
 * in a fixed window; once the answer moves on it closes. Opening or closing it
 * by hand wins over both.
 */
export default function StepGroup({
  entries,
  isLive,
  isStreaming,
}: {
  entries: GroupEntry[];
  /** The answer is streaming and nothing comes after this group yet. */
  isLive: boolean;
  isStreaming: boolean;
}) {
  const { t } = useTranslation();
  const [userOpen, setUserOpen] = useState<boolean | null>(null);
  const bodyId = useId();

  const calls = entries.flatMap((entry) =>
    entry.kind === 'call' ? [entry.call] : [],
  );
  const failed = calls.filter((call) => call.status === 'error').length;
  const icons = calls
    .filter(
      (call, i) =>
        calls.findIndex((other) => stepIconKey(other) === stepIconKey(call)) ===
        i,
    )
    .slice(0, 3);
  const showWindow = isLive && userOpen === null;
  const isOpen = userOpen ?? false;
  const expanded = isOpen || showWindow;

  return (
    <div className="my-2 flex w-full flex-col">
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={() => setUserOpen(!expanded)}
        aria-expanded={expanded}
        aria-controls={bodyId}
        // ml-3.5 plus size sm's own has-[>svg]:px-2.5 (the chevron is a direct
        // svg child) puts the first icon on the answer's ml-6 text column.
        className="ml-3.5 w-fit max-w-full justify-start"
      >
        <span className="flex shrink-0 items-center gap-1" aria-hidden>
          {icons.map((call) => (
            <StepIcon key={stepIconKey(call)} call={call} />
          ))}
        </span>
        <span className="text-muted-foreground min-w-0 truncate text-left">
          {t('conversation.stepGroup.steps', { count: calls.length })}
        </span>
        {failed > 0 && (
          <span className="text-destructive shrink-0 text-xs">
            {t('conversation.stepGroup.failed', { count: failed })}
          </span>
        )}
        <ChevronDown
          aria-hidden
          className={cn(
            'text-muted-foreground shrink-0 transition-transform duration-200',
            expanded && 'rotate-180',
          )}
        />
      </Button>
      {showWindow ? (
        // A fixed height, so arriving steps never resize the page and
        // retrigger the conversation scroll pin; the newest rows sit at the
        // bottom and older ones fade out at the top. A flex-end column whose
        // content outgrows it overflows at the top, so the newest row stays in
        // view without scrolling.
        <div
          id={bodyId}
          inert
          className="mt-1 mr-5 ml-6 flex h-21 flex-col justify-end overflow-hidden mask-t-from-50%"
        >
          <div className="shrink-0">
            <StepTimeline entries={entries} isStreaming={isStreaming} />
          </div>
        </div>
      ) : (
        <Collapsible id={bodyId} open={isOpen} className="mr-5 ml-6">
          <div className="pt-1">
            <StepTimeline entries={entries} isStreaming={isStreaming} />
          </div>
        </Collapsible>
      )}
    </div>
  );
}
