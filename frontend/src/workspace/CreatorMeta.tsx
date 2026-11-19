import { UserRound } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import { MetaItem } from '../components/ui/meta-line';
import { selectToken } from '../preferences/preferenceSlice';
import { personLabel, readerIdFromToken } from '../utils/personLabel';
import type { WorkspaceItemFields } from './itemOrigin';

/**
 * Whether a tile names who added the item: a team item (who added it) or
 * one shared with the caller (its owner). Callers test this before putting
 * `CreatorMeta` in a `MetaLine`, so no stray dot is left.
 */
export function showsCreator(item: WorkspaceItemFields): boolean {
  return (
    (item.origin === 'team' || item.origin === 'shared') &&
    !!(item.created_by?.user_id || item.created_by?.label)
  );
}

/**
 * Who added a team item, or owns one shared with the caller, as an item in
 * the tile's meta line: "Dana", or "You" for the reader. Nothing on the
 * caller's own items.
 */
export default function CreatorMeta({ item }: { item: WorkspaceItemFields }) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  if (!showsCreator(item)) return null;
  const label = personLabel(item.created_by, {
    readerId: readerIdFromToken(token),
    you: t('workspace.common.you'),
  });
  if (!label) return null;
  return (
    <MetaItem icon={<UserRound />} data-testid="creator-meta" title={label}>
      {label}
    </MetaItem>
  );
}
