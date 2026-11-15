import { useCallback, useEffect, useRef, useState } from 'react';

import workspacesService, {
  type MoveErrorBody,
  type MovePlan,
  type MoveRequest,
  type MoveResult,
} from '../../api/services/workspacesService';

/** A refused plan or move: its code and the whole response body. */
export type MoveFailure = { error: string; body: MoveErrorBody };

export type UseMovePlan = {
  /** The plan for the current request; null while it loads or failed. */
  plan: MovePlan | null;
  planning: boolean;
  /** Why the plan couldn't be made (a target folder too deep, a lost role). */
  planError: MoveFailure | null;
  /** The plan was swapped for a fresh one when a move found it changed. */
  changed: boolean;
  /** Plan again (after a failed plan). */
  retry: () => void;
  /**
   * Applies the move with the plan's fingerprint. A changed plan swaps in
   * the fresh one and answers `move_plan_changed`; null when there is no
   * plan to apply or the request changed meanwhile.
   */
  apply: () => Promise<MoveResult | null>;
};

const failed = (): MoveResult => ({
  ok: false,
  status: 0,
  error: 'move_failed',
  message: '',
  body: {},
});

/**
 * Plans a move whenever its request changes, and applies it with the
 * fingerprint of the plan on screen. An answer to an older request is
 * dropped.
 *
 * Args:
 *   request: The target and items, or null when there is no target yet.
 *   token: The session token.
 *
 * Returns:
 *   The plan, its load state, and `apply`.
 */
export function useMovePlan(
  request: MoveRequest | null,
  token: string | null,
): UseMovePlan {
  const [plan, setPlan] = useState<MovePlan | null>(null);
  const [planning, setPlanning] = useState(false);
  const [planError, setPlanError] = useState<MoveFailure | null>(null);
  const [changed, setChanged] = useState(false);
  const [attempt, setAttempt] = useState(0);
  // Counts requests, so only the latest plan's answer lands.
  const generation = useRef(0);
  const key = request ? JSON.stringify(request) : null;

  useEffect(() => {
    generation.current += 1;
    const issued = generation.current;
    setPlan(null);
    setPlanError(null);
    setChanged(false);
    if (!request) {
      setPlanning(false);
      return;
    }
    setPlanning(true);
    workspacesService
      .planMove(request, { token })
      .catch(failed)
      .then((result) => {
        if (issued !== generation.current) return;
        setPlanning(false);
        if (result.ok && result.plan) setPlan(result.plan);
        else
          setPlanError({
            error: result.ok ? 'move_failed' : result.error,
            body: result.ok ? {} : result.body,
          });
      });
    // The request is compared by value: a new object with the same target
    // must not plan again.
  }, [key, token, attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  const apply = useCallback(async (): Promise<MoveResult | null> => {
    if (!request || !plan) return null;
    const issued = generation.current;
    const result = await workspacesService
      .applyMove({ ...request, fingerprint: plan.fingerprint }, { token })
      .catch(failed);
    if (issued !== generation.current) return null;
    if (
      !result.ok &&
      result.error === 'move_plan_changed' &&
      result.body?.plan
    ) {
      setPlan(result.body.plan);
      setChanged(true);
    }
    return result;
  }, [key, plan, token]);

  return { plan, planning, planError, changed, retry, apply };
}

export default useMovePlan;
