import { ChevronRight } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { Link } from 'react-router-dom';

import { ListRow, ListRows } from '@/components/ui/list-row';
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
    <div className="flex flex-col gap-8">
      <h1 className="text-foreground text-2xl font-bold">
        {section.title ?? t(section.titleKey)}
      </h1>
      <div className="flex flex-col gap-6">
        {groups.map((group) => (
          <div key={group.key} className="flex flex-col gap-1">
            {group.labelKey && (
              <p className="text-muted-foreground mb-1 text-xs font-medium">
                {t(group.labelKey)}
              </p>
            )}
            <div className="border-border overflow-hidden rounded-2xl border">
              <ListRows>
                {group.items.map((item) => {
                  const Icon = item.icon;
                  return (
                    <ListRow
                      key={item.key}
                      interactive
                      asChild
                      leading={
                        <Icon
                          className="text-muted-foreground size-5 shrink-0"
                          aria-hidden
                        />
                      }
                      title={t(item.labelKey)}
                      trailing={
                        <ChevronRight
                          className="text-muted-foreground size-4 shrink-0"
                          aria-hidden
                        />
                      }
                    >
                      <Link to={item.path} />
                    </ListRow>
                  );
                })}
              </ListRows>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
