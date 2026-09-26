import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { Link } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { selectIsAdmin } from '@/preferences/preferenceSlice';

import { getVisibleGroups } from './sections';
import { useSectionContext } from './useSectionContext';

/**
 * The current section's destinations as a pill row, shown only below `lg`
 * where the sidebar is an overlay.
 *
 * Sections whose destinations are separate pages (settings, admin) use
 * `SectionIndexPage` instead. This is for sections whose destinations are
 * views of the page you are already on — the agent list's filters, an
 * agent's own pages — where bouncing out to a menu to switch would be worse
 * than a row of pills.
 */
export default function SectionPills({ className }: { className?: string }) {
  const { t } = useTranslation();
  const { section, item } = useSectionContext();
  const isAdmin = useSelector(selectIsAdmin);

  if (!section) return null;
  const items = getVisibleGroups(section, { isAdmin }).flatMap(
    (group) => group.items,
  );
  if (items.length < 2) return null;

  return (
    <div
      className={cn(
        'no-scrollbar flex gap-2 overflow-x-auto lg:hidden',
        className,
      )}
    >
      {items.map((entry) => {
        const isActive = entry.key === item?.key;
        return (
          <Button
            key={entry.key}
            asChild
            variant={isActive ? 'outline' : 'ghost-muted'}
            size="sm"
            shape="pill"
          >
            <Link to={entry.path} aria-current={isActive ? 'page' : undefined}>
              {t(entry.labelKey)}
            </Link>
          </Button>
        );
      })}
    </div>
  );
}
