import { PAUSE_REASONS, type PauseReason } from '../../payer/types';
import type { ScheduleRun } from '../types/schedule';

// A run skipped while the agent's owner (or the schedule's user) is
// deactivated carries this in `error`; rows written before it had an
// error_type value read through it.
export const OWNER_INACTIVE = 'owner_inactive';

type RunFields = Pick<ScheduleRun, 'status' | 'error' | 'error_type'>;

const isPauseReason = (value: unknown): value is PauseReason =>
  PAUSE_REASONS.includes(value as PauseReason);

/** Why a run failed or was skipped: a key under `activity.now.errorType`, or null. */
export function runReason(run: RunFields): string | null {
  if (run.error_type) return run.error_type;
  return run.status === 'skipped' && isPauseReason(run.error)
    ? run.error
    : null;
}

/**
 * Whether a run was skipped because its schedule is paused for its payer.
 * Such a row stands for the whole streak (later runs skipped for the same
 * reason aren't stored) and has no detail beyond its reason.
 */
export function isPauseSkip(run: RunFields): boolean {
  return run.status === 'skipped' && isPauseReason(runReason(run));
}
