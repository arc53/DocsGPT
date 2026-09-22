import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { Link } from 'react-router-dom';

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
          <Link
            key={entry.key}
            to={entry.path}
            aria-current={isActive ? 'page' : undefined}
            className={cn(
              'rounded-full px-4 py-2 text-sm whitespace-nowrap transition-colors',
              isActive
                ? 'bg-border text-foreground dark:bg-accent dark:text-white'
                : 'text-muted-foreground hover:bg-accent/50 dark:text-gray',
            )}
          >
            {t(entry.labelKey)}
          </Link>
        );
      })}
    </div>
  );
}
