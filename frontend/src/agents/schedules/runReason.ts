import type { ScheduleRun } from '../types/schedule';

// A run skipped while the agent's owner (or the schedule's user) is
// deactivated carries this in `error`: no error_type value names it
// (docsgpt/api/owner_pause.py).
export const OWNER_INACTIVE = 'owner_inactive';

/** Why a run failed or was skipped: a key under `activity.now.errorType`, or null. */
export function runReason(
  run: Pick<ScheduleRun, 'status' | 'error' | 'error_type'>,
): string | null {
  if (run.error_type) return run.error_type;
  return run.status === 'skipped' && run.error === OWNER_INACTIVE
    ? OWNER_INACTIVE
    : null;
}
