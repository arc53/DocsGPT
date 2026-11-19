import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import { showActionToast } from '../notifications/actionToastSlice';
import { PERSONAL_WORKSPACE } from './requestWorkspace';
import {
  selectWorkspaceId,
  selectWorkspaces,
  selectWorkspacesLoaded,
  switchWorkspace,
} from './workspaceSlice';

/** Where an item or chat lives, as its payload's `workspace` says. */
export type ItemWorkspace = {
  kind: 'personal' | 'team';
  team_id?: string | null;
};

/**
 * Follows an item or chat opened by its URL into its workspace: once it has
 * loaded and lives elsewhere than the current workspace, the app switches
 * there (a team the caller is in, or Personal for an own or shared personal
 * item) and says so. A team the caller isn't in is left alone; the page shows
 * what the server allowed.
 *
 * Args:
 *   itemWorkspace: The loaded item's `workspace`; nothing while it loads.
 */
export default function useFollowItemWorkspace(
  itemWorkspace?: ItemWorkspace | null,
): void {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const current = useSelector(selectWorkspaceId);
  const workspaces = useSelector(selectWorkspaces);
  const loaded = useSelector(selectWorkspacesLoaded);

  const target = !itemWorkspace
    ? null
    : itemWorkspace.kind === 'personal'
      ? PERSONAL_WORKSPACE
      : (itemWorkspace.team_id ?? null);

  useEffect(() => {
    if (!target || target === current) return;
    // A team needs the list to know the caller is in it, and its name.
    if (target !== PERSONAL_WORKSPACE && !loaded) return;
    const row = workspaces.find((w) => w.id === target);
    if (!row) return;
    const name =
      row.kind === 'personal' ? t('workspace.switcher.personal') : row.name;
    dispatch(switchWorkspace(target, { reason: 'link' }));
    dispatch(
      showActionToast({
        variant: 'info',
        message: t('workspace.notices.switched', {
          name,
          interpolation: { escapeValue: false },
        }),
      }),
    );
  }, [target, current, loaded, workspaces, dispatch, t]);
}

export { useFollowItemWorkspace };
