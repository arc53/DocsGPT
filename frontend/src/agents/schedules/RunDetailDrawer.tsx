import { useEffect } from 'react';

import { Button } from '../../components/ui/button';
import { formatDateTime } from '../../utils/dateTimeUtils';
import type { ScheduleRun } from '../types/schedule';
import ScheduleStatusBadge from './StatusBadge';

export type RunDetailDrawerProps = {
  run: ScheduleRun | null;
  onClose: () => void;
};

const formatTimestamp = (value?: string | null): string => {
  return value ? formatDateTime(value) : '—';
};

/** Side drawer with a single run's output / error (terminal-state only). */
export default function RunDetailDrawer({
  run,
  onClose,
}: RunDetailDrawerProps) {
  useEffect(() => {
    if (!run) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [run, onClose]);

  if (!run) return null;
  return (
    <>
      <div
        className="fixed inset-0 z-20 bg-black/40"
        onClick={onClose}
        aria-hidden="true"
      />
      <aside
        className="border-border bg-card fixed top-0 right-0 z-30 flex h-full w-full max-w-xl flex-col border-l p-6 shadow-lg"
        role="dialog"
        aria-label="Schedule run details"
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Run details</h2>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onClose}
            className="text-muted-foreground"
          >
            Close
          </Button>
        </div>
        <dl className="mb-4 grid grid-cols-2 gap-2 text-sm">
          <dt className="text-muted-foreground">Status</dt>
          <dd>
            <ScheduleStatusBadge status={run.status} />
          </dd>
          <dt className="text-muted-foreground">Scheduled for</dt>
          <dd>{formatTimestamp(run.scheduled_for)}</dd>
          <dt className="text-muted-foreground">Started</dt>
          <dd>{formatTimestamp(run.started_at)}</dd>
          <dt className="text-muted-foreground">Finished</dt>
          <dd>{formatTimestamp(run.finished_at)}</dd>
          <dt className="text-muted-foreground">Tokens</dt>
          <dd>
            {run.prompt_tokens} prompt · {run.generated_tokens} generated
          </dd>
          <dt className="text-muted-foreground">Trigger</dt>
          <dd>{run.trigger_source}</dd>
        </dl>
        {run.error && (
          <section className="mb-4">
            <h3 className="text-destructive text-sm font-semibold">
              Error{run.error_type ? ` (${run.error_type})` : ''}
            </h3>
            <pre className="bg-background mt-1 max-h-48 overflow-auto rounded-md p-3 font-mono text-xs">
              {run.error}
            </pre>
          </section>
        )}
        {run.output && (
          <section className="flex-1 overflow-hidden">
            <h3 className="text-sm font-semibold">
              Output
              {run.output_truncated && (
                <span className="text-muted-foreground ml-1 text-xs">
                  (truncated)
                </span>
              )}
            </h3>
            <pre className="bg-background mt-1 h-full overflow-auto rounded-md p-3 font-mono text-xs whitespace-pre-wrap">
              {run.output}
            </pre>
          </section>
        )}
      </aside>
    </>
  );
}
