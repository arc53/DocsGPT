import { PERSONAL_WORKSPACE } from '../../workspace/requestWorkspace';
import {
  selectCanCreateInWorkspace,
  selectIsTeamWorkspace,
  type WorkspaceState,
} from '../../workspace/workspaceSlice';

// Folder parts render inside pages whose tests build a store without the
// workspace slice; read such a store as Personal.
type RootLike = { workspace?: WorkspaceState };

/** The workspace whose tree the folders are: `personal` or a team id. */
export const selectFolderWorkspaceId = (state: RootLike): string =>
  state.workspace?.current ?? PERSONAL_WORKSPACE;

/** The folders are a team's. */
export const selectFoldersInTeam = (state: RootLike): boolean =>
  state.workspace
    ? selectIsTeamWorkspace(state as { workspace: WorkspaceState })
    : false;

/**
 * The caller may create, rename, move, file into and delete folders here:
 * Personal, or Editor and up in a team.
 */
export const selectCanEditFolders = (state: RootLike): boolean =>
  state.workspace
    ? selectCanCreateInWorkspace(state as { workspace: WorkspaceState })
    : true;
