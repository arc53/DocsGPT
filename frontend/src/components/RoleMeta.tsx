import { Users } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { roleOf, type AccessFields } from '../utils/accessUtils';
import { MetaItem } from './ui/meta-line';

/**
 * The caller's role on a team-shared item (agent, source, tool, prompt), as
 * an item in the tile's meta line: the Users icon and Editor or Viewer. A
 * role is a fact about the item, not a state, so it is never a Badge.
 * Nothing for the caller's own items.
 */
export default function RoleMeta({ item }: { item: AccessFields }) {
  const { t } = useTranslation();
  const role = roleOf(item);
  if (role === 'owner') return null;
  return (
    <MetaItem icon={<Users />} data-testid="role-meta">
      {role === 'editor' ? t('teamAccess.editor') : t('teamAccess.viewer')}
    </MetaItem>
  );
}
