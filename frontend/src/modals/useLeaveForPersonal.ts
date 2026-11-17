import { useCallback } from 'react';
import { useDispatch } from 'react-redux';
import { useNavigate } from 'react-router-dom';

import { type LeaveTo, leaveNow } from '../hooks/useLeaveGuard';
import { PERSONAL_WORKSPACE } from '../workspace/requestWorkspace';
import { switchWorkspace } from '../workspace/workspaceSlice';

/**
 * Leaves a team for a page in Personal: where a person connects their own
 * account (a team tool on each person's account needs the adder's own
 * sign-in first). The switch happens only once leaving is allowed, so a
 * builder that asks first and is told to stay keeps its workspace.
 *
 * Args:
 *   onNavigate: The opener's guarded exit; the router's navigate otherwise.
 *
 * Returns:
 *   `(path, state?)`, which switches to Personal and opens `path` there.
 */
export default function useLeaveForPersonal(onNavigate?: LeaveTo) {
  const dispatch = useDispatch();
  const navigate = useNavigate();
  return useCallback(
    (path: string, state?: unknown) => {
      const leave: LeaveTo =
        onNavigate ?? ((to, options) => leaveNow(navigate, to, options));
      leave(path, {
        state,
        // `link` keeps the page that was asked for rather than the new
        // workspace's landing page.
        beforeLeave: () =>
          dispatch(switchWorkspace(PERSONAL_WORKSPACE, { reason: 'link' })),
      });
    },
    [dispatch, navigate, onNavigate],
  );
}
