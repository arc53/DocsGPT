import { CircleAlert, CircleCheck } from 'lucide-react';
import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { Link } from 'react-router-dom';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Spinner } from '@/components/ui/spinner';
import { TableContainer } from '@/components/ui/table';

import { selectToken } from '../../preferences/preferenceSlice';
import type { AppDispatch, RootState } from '../../store';
import { agentEditPath } from '../paths';
import type { ScheduleRunStatus } from '../types/schedule';
import { RunTable } from './RunLog';
import { loadRunsForSchedule, selectRunsForSchedule } from './schedulesSlice';

const FINISHED: ScheduleRunStatus[] = [
  'success',
  'failed',
  'timeout',
  'skipped',
];

// How often a run still going is read again, in case its SSE result was
// missed (a dropped stream doesn't always replay it).
const POLL_MS = 10_000;

export type TestRunResultProps = {
  scheduleId: string;
  runId: string;
  /** The schedule's agent; without one the fix is in the user's tools. */
  agentId?: string | null;
};

/**
 * A schedule's test run as it goes: running, then its run-log row and what
 * it means. A run the agent can't do shows its reason and where to fix it.
 */
export default function TestRunResult({
  scheduleId,
  runId,
  agentId,
}: TestRunResultProps) {
  const { t } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();
  const token = useSelector(selectToken);
  const run = useSelector((state: RootState) =>
    selectRunsForSchedule(state, scheduleId).find((item) => item.id === runId),
  );
  const finished = Boolean(run && FINISHED.includes(run.status));

  // The SSE result carries the status and error only: read the run again
  // once it ends for its duration and tokens (or when a chat card mounts
  // before the store has it).
  const hasRun = Boolean(run);
  const loadedFinished = useRef(false);
  useEffect(() => {
    if (hasRun && !finished) return;
    if (finished) {
      if (loadedFinished.current) return;
      loadedFinished.current = true;
    }
    dispatch(loadRunsForSchedule({ id: scheduleId, token }));
  }, [dispatch, scheduleId, token, finished, hasRun]);

  useEffect(() => {
    if (!hasRun || finished) return;
    const timer = setInterval(
      () => dispatch(loadRunsForSchedule({ id: scheduleId, token })),
      POLL_MS,
    );
    return () => clearInterval(timer);
  }, [dispatch, scheduleId, token, finished, hasRun]);

  const cannotComplete =
    run?.error_type === 'cannot_complete' ? run.error || '' : null;
  const failed = finished && run?.status !== 'success';

  return (
    <div className="flex flex-col gap-3" data-testid="schedule-test-run">
      <div className="flex items-center gap-2 text-sm">
        {!finished ? (
          <Spinner size="xs" className="text-muted-foreground" />
        ) : failed ? (
          <CircleAlert className="text-destructive size-4 shrink-0" />
        ) : (
          <CircleCheck className="text-success size-4 shrink-0" />
        )}
        <p className={failed ? 'text-destructive font-medium' : 'font-medium'}>
          {!finished
            ? t('agents.schedules.testRun.running')
            : failed
              ? t('agents.schedules.testRun.failed')
              : t('agents.schedules.testRun.succeeded')}
        </p>
      </div>
      {/* Its own scroller: a narrow dialog or chat card scrolls the row
          sideways, and the sticky head stays on it. */}
      {run && (
        <TableContainer>
          <RunTable runs={[run]} />
        </TableContainer>
      )}
      {cannotComplete !== null && (
        <>
          <Alert variant="warning">
            <AlertDescription>
              {cannotComplete
                ? t('agents.schedules.testRun.cannotComplete', {
                    reason: cannotComplete,
                    interpolation: { escapeValue: false },
                  })
                : t('agents.schedules.testRun.cannotCompleteNoReason')}
            </AlertDescription>
          </Alert>
          <div>
            <Button variant="outline" size="sm" shape="pill" asChild>
              <Link to={agentId ? agentEditPath(agentId) : '/settings/tools'}>
                {agentId
                  ? t('agents.schedules.testRun.editAgent')
                  : t('agents.schedules.testRun.editTools')}
              </Link>
            </Button>
          </div>
        </>
      )}
      {failed && cannotComplete === null && run?.error && (
        <p className="text-muted-foreground text-xs break-words">{run.error}</p>
      )}
    </div>
  );
}
