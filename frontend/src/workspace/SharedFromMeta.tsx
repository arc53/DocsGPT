import { Users } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { MetaItem } from '../components/ui/meta-line';
import type { WorkspaceItemFields } from './itemOrigin';

/**
 * Whether a tile names the team an item comes from: another team's item
 * shared with this team (`origin: "team_shared"`) whose team has a name.
 * Callers test this before putting `SharedFromMeta` in a `MetaLine`, so no
 * stray dot is left.
 */
export function showsSharedFrom(item: WorkspaceItemFields): boolean {
  return item.origin === 'team_shared' && !!item.shared_from?.name;
}

/**
 * The team another team's item comes from, as an item in the tile's meta
 * line: "From Operations". Nothing on any other item.
 */
export default function SharedFromMeta({
  item,
}: {
  item: WorkspaceItemFields;
}) {
  const { t } = useTranslation();
  if (!showsSharedFrom(item)) return null;
  const label = t('workspace.page.sharedFromTeams.from', {
    team: item.shared_from?.name,
    interpolation: { escapeValue: false },
  });
  return (
    <MetaItem icon={<Users />} data-testid="shared-from-meta" title={label}>
      {label}
    </MetaItem>
  );
}
