import { useEffect, useRef } from 'react';
import { useSelector } from 'react-redux';
import { useLocation, useNavigate } from 'react-router-dom';

import { workspaceLandingPath } from './landing';
import type { WorkspaceState } from './workspaceSlice';

/**
 * Takes the app off a page of the old workspace after a switch it didn't ask
 * for (the team is gone). The switcher lands the page itself; a switch that
 * follows an opened link stays on that item.
 */
export default function useWorkspaceLanding(): void {
  const navigate = useNavigate();
  const location = useLocation();
  const epoch = useSelector(
    (state: { workspace: WorkspaceState }) => state.workspace.epoch,
  );
  const reason = useSelector(
    (state: { workspace: WorkspaceState }) => state.workspace.lastReason,
  );
  const seen = useRef(epoch);

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
