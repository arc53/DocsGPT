import { createListenerMiddleware } from '@reduxjs/toolkit';
import i18n from 'i18next';

import { showActionToast } from '../notifications/actionToastSlice';
import { createTeam, deleteTeam } from '../teams/teamsSlice';
import {
  onWorkspaceLost,
  onWorkspaceRoleRefused,
  PERSONAL_WORKSPACE,
  setRequestWorkspace,
} from './requestWorkspace';
import {
  loadWorkspaces,
  storeWorkspace,
  switchWorkspace,
  type WorkspaceState,
} from './workspaceSlice';

type ListenerState = {
  workspace: WorkspaceState;
  preference?: { token: string | null };
};

type Dispatch = (action: unknown) => unknown;

const tokenOf = (state: ListenerState) => state.preference?.token ?? null;

/**
 * Keeps requests and the stored choice in step with the `workspace` slice,
 * and drops a team the caller is no longer in back to Personal.
 */
export const workspaceListenerMiddleware = createListenerMiddleware();

// Synchronous, before anything rendered after the switch can fetch.
workspaceListenerMiddleware.startListening({
  actionCreator: switchWorkspace,
  effect: (_action, api) => {
    const { current, epoch } = (api.getState() as ListenerState).workspace;
    setRequestWorkspace(current, epoch);
    storeWorkspace(current);
  },
});

// A stored or current team missing from the list: the caller left, was
// removed, or the team was deleted.
workspaceListenerMiddleware.startListening({
  actionCreator: loadWorkspaces.fulfilled,
  effect: (_action, api) => {
    const { current, workspaces, loaded } = (api.getState() as ListenerState)
      .workspace;
    if (!loaded || current === PERSONAL_WORKSPACE) return;
    if (workspaces.some((row) => row.id === current)) return;
    const known = (api.getOriginalState() as ListenerState).workspace
      .workspaces;
    const name = known.find((row) => row.id === current)?.name;
    api.dispatch(switchWorkspace(PERSONAL_WORKSPACE, { reason: 'lost' }));
    api.dispatch(
      showActionToast({
        variant: 'info',
        message: name
          ? i18n.t('workspace.notices.lost', {
              name,
              interpolation: { escapeValue: false },
            })
          : i18n.t('workspace.notices.lostUnnamed'),
      }),
    );
  },
});

// A new team shows in the switcher at once.
workspaceListenerMiddleware.startListening({
  actionCreator: createTeam.fulfilled,
  effect: (action, api) => {
    api.dispatch(loadWorkspaces({ token: action.meta.arg.token }));
  },
});

// Deleting the team you're in takes you to Personal, without the "no longer
// in" notice: you did it.
workspaceListenerMiddleware.startListening({
  actionCreator: deleteTeam.fulfilled,
  effect: (action, api) => {
    const { current } = (api.getState() as ListenerState).workspace;
    if (current === action.payload)
      api.dispatch(switchWorkspace(PERSONAL_WORKSPACE));
    api.dispatch(loadWorkspaces({ token: action.meta.arg.token }));
  },
});

/**
 * Connects the API client's refusals to the store: a 404
 * `workspace_not_found` for the current team checks the list again (which
 * switches to Personal when the team is gone), and a 403
 * `workspace_role_required` says the role changed and reloads it.
 *
 * Args:
 *   store: The app's store.
 *
 * Returns:
 *   A function that disconnects them.
 */
export function connectWorkspaceClient(store: {
  dispatch: Dispatch;
  getState: () => unknown;
}): () => void {
  const isCurrentTeam = (workspace: string) => {
    const { current } = (store.getState() as ListenerState).workspace;
    return current !== PERSONAL_WORKSPACE && current === workspace;
  };
  const reload = () =>
    store.dispatch(
      loadWorkspaces({ token: tokenOf(store.getState() as ListenerState) }),
    );
  const offLost = onWorkspaceLost((workspace) => {
    if (isCurrentTeam(workspace)) reload();
  });
  const offRefused = onWorkspaceRoleRefused((workspace) => {
    if (!isCurrentTeam(workspace)) return;
    const state = store.getState() as ListenerState;
    const name = state.workspace.workspaces.find(
      (row) => row.id === workspace,
    )?.name;
    store.dispatch(
      showActionToast({
        variant: 'warning',
        message: i18n.t('workspace.notices.roleChanged', {
          name: name ?? '',
          interpolation: { escapeValue: false },
        }),
      }),
    );
    reload();
  });
  return () => {
    offLost();
    offRefused();
  };
}
