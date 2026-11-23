import {
  selectCanCreateInWorkspace,
  selectIsTeamWorkspace,
  type WorkspaceState,
} from '../workspace/workspaceSlice';

// Settings pages also render in tests whose store has no workspace slice;
// such a store reads as Personal.
type RootLike = { workspace?: WorkspaceState };

/** The current workspace is a team. */
export const selectInTeam = (state: RootLike): boolean =>
  state.workspace
    ? selectIsTeamWorkspace(state as { workspace: WorkspaceState })
    : false;

/**
 * Add, New folder and the other create controls show: Personal, or Editor
 * and up in a team.
 */
export const selectCanCreateHere = (state: RootLike): boolean =>
  state.workspace
    ? selectCanCreateInWorkspace(state as { workspace: WorkspaceState })
    : true;
