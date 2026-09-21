import { ChevronRight } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { Link } from 'react-router-dom';

import { selectIsAdmin } from '@/preferences/preferenceSlice';

import { getVisibleGroups, type Section } from './sections';

/**
 * Small-screen landing page for a section: the same destinations as the
 * sidebar nav, rendered as page content so they stay reachable while the
 * sidebar is an overlay. Tapping a row pushes its page, which carries a back
 * link to here.
 */
export default function SectionIndexPage({ section }: { section: Section }) {
  const { t } = useTranslation();
  const isAdmin = useSelector(selectIsAdmin);
  const groups = getVisibleGroups(section, { isAdmin });

  return (
    <div className="flex flex-col">
      <h1 className="text-foreground dark:text-foreground text-2xl font-bold">
        {section.title ?? t(section.titleKey)}
      </h1>
      <div className="mt-6 flex flex-col gap-6">
        {groups.map((group) => (
          <div key={group.key} className="flex flex-col gap-1">
            {group.labelKey && (
              <p className="text-muted-foreground mb-1 text-xs font-medium">
                {t(group.labelKey)}
              </p>
            )}
            <div className="border-border divide-border divide-y overflow-hidden rounded-2xl border">
              {group.items.map((item) => {
                const Icon = item.icon;
                return (
                  <Link
                    key={item.key}
                    to={item.path}
                    className="hover:bg-muted dark:hover:bg-accent flex items-center gap-3 px-4 py-3.5"
                  >
                    <Icon
                      className="text-muted-foreground size-5 shrink-0"
                      strokeWidth={1.75}
                      aria-hidden
                    />
                    <span className="text-foreground dark:text-foreground flex-1 text-sm">
                      {t(item.labelKey)}
                    </span>
                    <ChevronRight
                      className="text-muted-foreground size-4 shrink-0"
                      strokeWidth={1.75}
                      aria-hidden
                    />
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
