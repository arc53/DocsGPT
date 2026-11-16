import type { Action } from '@reduxjs/toolkit';
import i18n from 'i18next';
import { useSelector } from 'react-redux';

import { showActionToast } from '../notifications/actionToastSlice';
import { PERSONAL_WORKSPACE } from '../workspace/requestWorkspace';
import type { ItemWorkspace } from '../workspace/useFollowItemWorkspace';
import {
  switchWorkspace,
  type WorkspaceState,
} from '../workspace/workspaceSlice';

/**
 * What following an item into its workspace takes: nothing (it is in the
 * current one, or in a team the caller isn't in), waiting for the caller's
 * workspace list, or a switch.
 */
export type FollowStep =
  | { kind: 'none' }
  | { kind: 'wait' }
  | { kind: 'switch'; target: string; name: string };

/**
 * How long a chat opened by its link waits for the workspace list before it
 * opens where the app is.
 */
export const FOLLOW_WAIT_MS = 10_000;

/**
 * The step that takes the app to an item's workspace, from the workspace
 * slice: Personal at once, a team only once the list says the caller is in
 * it. While the list hasn't answered (its first load is still to come or is
 * out) the step is to wait; after a failed load nothing follows.
 *
 * Args:
 *   item: The item's `workspace`; nothing while it loads.
 *   state: The `workspace` slice.
 */
export function followStep(
  item: ItemWorkspace | null | undefined,
  state: WorkspaceState,
): FollowStep {
  if (!item) return { kind: 'none' };
  const target =
    item.kind === 'personal' ? PERSONAL_WORKSPACE : (item.team_id ?? null);
  if (!target || target === state.current) return { kind: 'none' };
  if (target === PERSONAL_WORKSPACE)
    return {
      kind: 'switch',
      target,
      name: i18n.t('workspace.switcher.personal'),
    };
  if (!state.loaded)
    return state.loading || state.latestRequestId === null
      ? { kind: 'wait' }
      : { kind: 'none' };
  const row = state.workspaces.find((w) => w.id === target);
  return row ? { kind: 'switch', target, name: row.name } : { kind: 'none' };
}

type GetState = () => unknown;

const workspaceOf = (getState: GetState) =>
  (getState() as { workspace: WorkspaceState }).workspace;

/** How often a follow that waits for the workspace list looks again. */
const WAIT_STEP_MS = 50;

/** Resolves once `ready()` holds, or with false after `timeoutMs`. */
async function waitFor(
  ready: () => boolean,
  timeoutMs: number,
): Promise<boolean> {
  for (let waited = 0; !ready(); waited += WAIT_STEP_MS) {
    if (waited >= timeoutMs) return false;
    await new Promise((done) => setTimeout(done, WAIT_STEP_MS));
  }
  return true;
}

/**
 * Takes the app to the workspace an item or chat opened by its link lives
 * in, before it is shown: the switch closes the open chat and reloads the
 * page area, so a chat applied after it stays, and nothing of the old
 * workspace is drawn first. Says "Switched to <name>". A switch the user
 * makes while it waits for the list wins: it then does nothing.
 *
 * Args:
 *   item: The item's `workspace`.
 *   options.timeoutMs: How long to wait for the workspace list.
 *
 * Returns:
 *   A thunk resolving to whether the app switched.
 */
export const followItemWorkspace =
  (
    item: ItemWorkspace | null | undefined,
    { timeoutMs = FOLLOW_WAIT_MS }: { timeoutMs?: number } = {},
  ) =>
  async (
    dispatch: (action: Action) => unknown,
    getState: GetState,
  ): Promise<boolean> => {
    const { epoch } = workspaceOf(getState);
    if (followStep(item, workspaceOf(getState)).kind === 'wait')
      await waitFor(
        () => followStep(item, workspaceOf(getState)).kind !== 'wait',
        timeoutMs,
      );
    // The user switched while it waited: their pick stands.
    if (workspaceOf(getState).epoch !== epoch) return false;
    const step = followStep(item, workspaceOf(getState));
    if (step.kind !== 'switch') return false;
    dispatch(switchWorkspace(step.target, { reason: 'link' }));
    dispatch(
      showActionToast({
        variant: 'info',
        message: i18n.t('workspace.notices.switched', {
          name: step.name,
          interpolation: { escapeValue: false },
        }),
      }),
    );
    return true;
  };

/**
 * Whether a page must hold off drawing an item while the app follows it
 * into its workspace (the switch is due, or waits for the workspace list).
 *
 * Args:
 *   item: The loaded item's `workspace`; nothing while it loads.
 */
export function useFollowPending(
  item: ItemWorkspace | null | undefined,
): boolean {
  return useSelector(
    (state: { workspace: WorkspaceState }) =>
      followStep(item, state.workspace).kind !== 'none',
  );
}
