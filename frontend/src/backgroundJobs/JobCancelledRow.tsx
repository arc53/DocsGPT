import { Ban } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import type { ToolCallsType } from '../conversation/types';
import { cn } from '@/lib/utils';

import { effectiveJobStatus } from './BackgroundJobCard';
import { selectBackgroundJob } from './backgroundSlice';

/** `run_code` -> "Run code". */
const actionWords = (name: string | undefined): string => {
  const words = (name ?? '').replace(/_/g, ' ').trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
};

function CancelledRow({ toolCall }: { toolCall: ToolCallsType }) {
  const { t } = useTranslation();
  const job = useSelector(selectBackgroundJob(toolCall.job_id));
  if (effectiveJobStatus(toolCall, job) !== 'cancelled') return null;
  const label = actionWords(toolCall.action_name);
  return (
    <div
      className="text-muted-foreground ml-3.5 flex h-8 w-fit max-w-full items-center gap-1.5 px-2.5 text-sm [&_svg]:size-4 [&_svg]:shrink-0"
      data-testid="job-cancelled-row"
    >
      <Ban aria-hidden />
      <span className="shrink-0">{t('backgroundJobs.wake.cancelled')}</span>
      {label && (
        <span className="text-muted-foreground/70 min-w-0 truncate">
          {label}
        </span>
      )}
    </div>
  );
}

/**
 * A system row under a turn for each of its background jobs the user
 * cancelled: the reply above was written while the job ran and may still
 * promise a follow-up, and a cancelled job wakes no one, so this row is what
 * says it ended. Nothing is sent to the model.
 */
export default function JobCancelledRows({
  toolCalls,
  className,
}: {
  toolCalls?: ToolCallsType[];
  className?: string;
}) {
  const calls = (toolCalls ?? []).filter((call) => call.job_id);
  if (!calls.length) return null;
  return (
    <div className={cn('flex flex-col', className)}>
      {calls.map((call) => (
        <CancelledRow key={call.call_id ?? call.job_id} toolCall={call} />
      ))}
    </div>
  );
}
