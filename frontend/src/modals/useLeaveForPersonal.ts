import { useCallback } from 'react';
import { useDispatch } from 'react-redux';
import { useLocation, useNavigate } from 'react-router-dom';

import { type LeaveTo, leaveNow } from '../hooks/useLeaveGuard';
import { switchOnArrival, workspaceLandingPath } from '../workspace/landing';
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
  const location = useLocation();
  return useCallback(
    (path: string, state?: Record<string, unknown>) => {
      const leave: LeaveTo =
        onNavigate ?? ((to, options) => leaveNow(navigate, to, options));
      const here = `${location.pathname}${location.search}`;
      if (workspaceLandingPath(location.pathname, location.search) !== here) {
        // A chat or an item's page: a switch first would remount it on its
        // own address in Personal, where it opens again and follows itself
        // back to the team. The switch waits for the new page instead.
        leave(path, {
          state: { ...state, ...switchOnArrival(PERSONAL_WORKSPACE, 'link') },
        });
        return;
      }
      leave(path, {
        state,
        // `link` keeps the page that was asked for rather than the new
        // workspace's landing page.
        beforeLeave: () =>
          dispatch(switchWorkspace(PERSONAL_WORKSPACE, { reason: 'link' })),
      });
    },
    [dispatch, navigate, onNavigate, location.pathname, location.search],
  );
}
