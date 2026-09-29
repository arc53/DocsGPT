import { Users } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { roleOf, type AccessFields } from '../utils/accessUtils';
import { Badge } from './ui/badge';

/**
 * The caller's role on a team-shared asset tile (agent, source, tool): a
 * neutral Badge with the Users icon and Editor or Viewer. Nothing for the
 * caller's own items.
 */
export default function RoleBadge({
  item,
  className,
}: {
  item: AccessFields;
  /** Placement only (a tile pins it beside its menu). */
  className?: string;
}) {
  const { t } = useTranslation();
  const role = roleOf(item);
  if (role === 'owner') return null;
  return (
    <Badge variant="neutral" className={className} data-testid="role-badge">
      <Users aria-hidden="true" />
      {role === 'editor' ? t('teamAccess.editor') : t('teamAccess.viewer')}
    </Badge>
  );
}
