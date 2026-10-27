import {
  ChevronDown,
  Circle,
  CircleCheck,
  CircleX,
  Workflow,
} from 'lucide-react';
import { useEffect, useId, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { NODE_COLORS, NODE_ICONS } from '../agents/workflow/nodeVisuals';
import { Button } from '../components/ui/button';
import { Collapsible } from '../components/ui/collapsible';
import { Spinner } from '../components/ui/spinner';
import { WorkflowProgress, WorkflowStep } from './conversationModels';
import { runningStep } from './workflowProgress';
import { cn } from '@/lib/utils';

/** Steps shown under the header while the run works; the header opens to all. */
const LIVE_STEP_LIMIT = 4;

type WorkflowRunProgressProps = {
  workflow: WorkflowProgress;
  isStreaming?: boolean;
  /** Once the answer itself streams, only the header stays. */
  hasAnswerText?: boolean;
};

/** Ticks once a second while ``active``, for the elapsed labels. */
function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [active]);
  return now;
}

function formatDuration(ms: number): string {
  const seconds = Math.max(0, Math.round(ms / 1000));
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, '0')}s`;
}

function StatusIcon({ step }: { step: WorkflowStep }) {
  if (step.status === 'running')
    return <Spinner size="xs" className="text-primary" />;
  if (step.status === 'failed')
    return <CircleX aria-hidden className="text-destructive size-4" />;
  return <CircleCheck aria-hidden className="text-success size-4" />;
}

/** One step: status, node icon, title and time, then a line about its result. */
function StepRow({
  step,
  now,
  connector,
}: {
  step: WorkflowStep;
  now: number;
  connector?: boolean;
}) {
  const Icon = NODE_ICONS[step.nodeType] || Circle;
  const duration = step.startedAt
    ? formatDuration((step.endedAt ?? now) - step.startedAt)
    : null;
  return (
    <div className="animate-in fade-in flex items-stretch gap-3 duration-160 ease-out motion-reduce:animate-none">
      <div className="flex flex-col items-center pt-0.5">
        <span className="flex size-4 shrink-0 items-center justify-center">
          <StatusIcon step={step} />
        </span>
        {connector && <span className="bg-border mt-1 w-px flex-1" />}
      </div>
      <div className="min-w-0 flex-1 pb-3">
        <div className="flex min-w-0 items-center gap-1.5 text-sm">
          <Icon
            aria-hidden
            className={cn(
              'size-3.5 shrink-0',
              NODE_COLORS[step.nodeType] || NODE_COLORS.state,
            )}
          />
          <span
            title={step.title}
            className={cn(
              'min-w-0 truncate',
              step.status === 'running'
                ? 'shimmer-text font-medium'
                : 'text-foreground',
            )}
          >
            {step.title}
          </span>
          {duration && (
            <span className="text-muted-foreground shrink-0 text-xs tabular-nums">
              {duration}
            </span>
          )}
        </div>
        {step.error ? (
          <p className="text-destructive mt-0.5 text-xs wrap-break-word">
            {step.error}
          </p>
        ) : (
          step.detail && (
            <p
              className="text-muted-foreground mt-0.5 truncate text-xs"
              title={step.detail}
            >
              {step.detail}
            </p>
          )
        )}
      </div>
    </div>
  );
}

function StepList({ steps, now }: { steps: WorkflowStep[]; now: number }) {
  return (
    <div className="flex flex-col pt-1">
      {steps.map((step, i) => (
        <StepRow
          key={step.nodeId}
          step={step}
          now={now}
          connector={i < steps.length - 1}
        />
      ))}
    </div>
  );
}

/**
 * A workflow agent's run as one row, like a tool call: the header says how far
 * along it is, the latest steps show under it while the run works, and it
 * opens to every step with its time and result.
 */
export default function WorkflowRunProgress({
  workflow,
  isStreaming = false,
  hasAnswerText = false,
}: WorkflowRunProgressProps) {
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);
  const bodyId = useId();
  const current = runningStep(workflow);
  const isLive = isStreaming && Boolean(current);
  const now = useNow(isLive);
  if (workflow.steps.length === 0) return null;

  const showLiveSteps = isStreaming && !hasAnswerText && !isOpen;
  const position = current
    ? workflow.steps.indexOf(current) + 1
    : workflow.steps.length;
  const first = workflow.steps[0].startedAt;
  const last = workflow.steps.at(-1)?.endedAt;
  const total = first && last && !isLive ? formatDuration(last - first) : null;
  const failed = workflow.steps.some((s) => s.status === 'failed');
  const meta = isLive
    ? workflow.total
      ? t('conversation.workflow.stepOf', {
          step: Math.min(position, workflow.total),
          total: workflow.total,
        })
      : t('conversation.workflow.step', { step: position })
    : t('conversation.workflow.stepCount', { count: workflow.steps.length });

  return (
    <div className="my-2 flex w-full flex-col">
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={() => setIsOpen(!isOpen)}
        aria-expanded={isOpen}
        aria-controls={bodyId}
        // ml-3.5 plus size sm's own has-[>svg]:px-2.5 puts the icon on the
        // answer's ml-6 text column, like the other step rows.
        className="ml-3.5 w-fit max-w-full justify-start"
      >
        <Workflow
          aria-hidden
          className={cn('text-muted-foreground', isLive && 'animate-pulse')}
        />
        <span
          className={cn(
            'min-w-0 truncate',
            isLive ? 'shimmer-text' : 'text-muted-foreground',
          )}
        >
          {t('conversation.workflow.title')}
        </span>
        <span className="text-muted-foreground/70 font-normal tabular-nums">
          {meta}
          {total && ` · ${total}`}
        </span>
        {failed && (
          <span className="text-destructive shrink-0 text-xs">
            {t('conversation.inlineSteps.failed')}
          </span>
        )}
        <ChevronDown
          aria-hidden
          className={cn(
            'text-muted-foreground shrink-0 transition-transform duration-200',
            isOpen && 'rotate-180',
          )}
        />
      </Button>
      {showLiveSteps && (
        <div className="mt-1 mr-5 ml-6" role="status" aria-live="polite">
          <StepList steps={workflow.steps.slice(-LIVE_STEP_LIMIT)} now={now} />
        </div>
      )}
      <Collapsible open={isOpen} id={bodyId} className="mr-5 ml-6">
        <div className="pt-2">
          <StepList steps={workflow.steps} now={now} />
        </div>
      </Collapsible>
    </div>
  );
}
