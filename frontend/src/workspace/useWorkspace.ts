import { useCallback } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useLocation, useNavigate } from 'react-router-dom';

import { workspaceLandingPath } from './landing';
import {
  selectCanCreateInWorkspace,
  selectCurrentWorkspace,
  selectIsTeamWorkspace,
  selectWorkspaceId,
  selectWorkspaceRole,
  switchWorkspace,
  type WorkspaceRole,
  type WorkspaceRow,
} from './workspaceSlice';

export type UseWorkspace = {
  /** `personal` or a team id. */
  id: string;
  workspace: WorkspaceRow;
  role: WorkspaceRole;
  isTeam: boolean;
  /** Personal, or Editor and up in a team. */
  canCreate: boolean;
  /**
   * Switches to another workspace the way the switcher does: an item's page
   * goes to its list first, a list page stays. Nothing for the current one.
   */
  switchTo: (id: string) => void;
};

/** The current workspace, the caller's role there, and a way to switch. */
export default function useWorkspace(): UseWorkspace {
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const location = useLocation();
  const id = useSelector(selectWorkspaceId);
  const workspace = useSelector(selectCurrentWorkspace);
  const role = useSelector(selectWorkspaceRole);
  const isTeam = useSelector(selectIsTeamWorkspace);
  const canCreate = useSelector(selectCanCreateInWorkspace);

  const switchTo = useCallback(
    (next: string) => {
      if (next === id) return;
      // Leave the old workspace's page in the same render as the switch, so
      // the page that remounts is the list, not the item.
      const target = workspaceLandingPath(location.pathname, location.search);
      if (target !== `${location.pathname}${location.search}`)
        navigate(target, { replace: true });
      dispatch(switchWorkspace(next));
    },
    [dispatch, navigate, id, location.pathname, location.search],
  );

  return { id, workspace, role, isTeam, canCreate, switchTo };
}

export { useWorkspace };
