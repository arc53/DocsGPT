import { useEffect, useRef } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useLocation, useNavigate } from 'react-router-dom';

import { switchRequested, workspaceLandingPath } from './landing';
import {
  selectWorkspaceId,
  switchWorkspace,
  type WorkspaceState,
} from './workspaceSlice';

/**
 * Takes the app off a page of the old workspace after a switch it didn't ask
 * for (the team is gone). The switcher lands the page itself; a switch that
 * follows an opened link stays on that item. Also makes the switch a
 * navigation asked for (`switchOnArrival`) once its page has rendered.
 */
export default function useWorkspaceLanding(): void {
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const location = useLocation();
  const current = useSelector(selectWorkspaceId);
  const epoch = useSelector(
    (state: { workspace: WorkspaceState }) => state.workspace.epoch,
  );
  const reason = useSelector(
    (state: { workspace: WorkspaceState }) => state.workspace.lastReason,
  );
  const seen = useRef(epoch);

  const requested = switchRequested(location.state);
  useEffect(() => {
    if (!requested) return;
    // Forget the request first, so Back, Forward or a reload of this entry
    // doesn't switch again.
    navigate(`${location.pathname}${location.search}${location.hash}`, {
      replace: true,
      state: null,
    });
    if (requested.id !== current)
      dispatch(switchWorkspace(requested.id, { reason: requested.reason }));
    // Once per navigation that asked for it.
  }, [location.key]);

  useEffect(() => {
    if (epoch === seen.current) return;
    seen.current = epoch;
    if (reason === 'link') return;
    const here = `${location.pathname}${location.search}`;
    const target = workspaceLandingPath(location.pathname, location.search);
    if (target !== here) navigate(target, { replace: true });
    // Only a new switch moves the page; navigating within the new workspace
    // must not, so the location is read, not watched.
  }, [epoch]);
}
