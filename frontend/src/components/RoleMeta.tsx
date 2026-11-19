import { Users } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { roleOf, type AccessFields } from '../utils/accessUtils';
import { MetaItem } from './ui/meta-line';

/**
 * Whether a tile shows the caller's role: only on an item shared with them.
 * A team item's tile names who added it instead, and the caller's own item
 * has nothing to say. Callers test this before putting `RoleMeta` in a
 * `MetaLine`, so no stray dot is left.
 */
export function showsRole(item: AccessFields): boolean {
  if (item.origin) return item.origin === 'shared';
  return roleOf(item) !== 'owner';
}

/**
 * The caller's role on an item shared with them (agent, source, tool,
 * prompt), as an item in the tile's meta line: the Users icon and Editor or
 * Viewer. A role is a fact about the item, not a state, so it is never a
 * Badge. Nothing for the caller's own items or the team's.
 */
export default function RoleMeta({ item }: { item: AccessFields }) {
  const { t } = useTranslation();
  if (!showsRole(item)) return null;
  const role = roleOf(item);
  return (
    <MetaItem icon={<Users />} data-testid="role-meta">
      {role === 'admin'
        ? t('workspace.common.roles.admin')
        : role === 'editor'
          ? t('teamAccess.editor')
          : t('teamAccess.viewer')}
    </MetaItem>
  );
}
