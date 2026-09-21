import { ArrowLeft } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import { cn } from '@/lib/utils';

import { getVisibleGroups, type Section, type SectionItem } from './sections';

type SectionNavProps = {
  section: Section;
  /** Key of the item matching the current route, from ``getActiveItem``. */
  activeItemKey?: string;
  isAdmin: boolean;
  /** Leaves the section — always "exit", never "up one level". */
  onBack: () => void;
  backLabel: string;
  onNavigate?: () => void;
};

/**
 * Vertical nav that replaces the chat list while the user is inside a section.
 *
 * The only back affordance at this level is ``onBack``, which exits the
 * section; anything deeper (a tool's config, a team's detail) keeps its own
 * breadcrumb in the content column so the two never compete.
 */
export default function SectionNav({
  section,
  activeItemKey,
  isAdmin,
  onBack,
  backLabel,
  onNavigate,
}: SectionNavProps) {
  const { t } = useTranslation();
  const groups = getVisibleGroups(section, { isAdmin });
  const sectionTitle = section.title ?? t(section.titleKey);

  const renderItem = (item: SectionItem) => {
    const isActive = item.key === activeItemKey;
    const Icon = item.icon;
    return (
      <Link
        key={item.key}
        to={item.path}
        onClick={onNavigate}
        aria-current={isActive ? 'page' : undefined}
        className={cn(
          'hover:bg-sidebar-accent mx-4 my-1 flex h-9 cursor-pointer items-center gap-2.5 rounded-3xl pl-3',
          isActive && 'bg-sidebar-accent',
        )}
      >
        <Icon
          className="text-muted-foreground size-5 shrink-0"
          strokeWidth={1.75}
          aria-hidden
        />
        <p className="text-foreground dark:text-foreground overflow-hidden text-sm leading-6 text-ellipsis whitespace-nowrap">
          {t(item.labelKey)}
        </p>
      </Link>
    );
  };

  return (
    <div className="flex h-full flex-col">
      <button
        type="button"
        onClick={onBack}
        className="group border-sidebar-border hover:border-sidebar-border mx-4 mt-4 flex shrink-0 cursor-pointer items-center gap-2.5 rounded-3xl border p-3 text-left"
      >
        <ArrowLeft
          className="text-muted-foreground group-hover:text-foreground size-5 shrink-0"
          strokeWidth={1.75}
          aria-hidden
        />
        <p className="text-muted-foreground group-hover:text-foreground text-sm">
          {backLabel}
        </p>
      </button>
      <p
        className="text-foreground mt-6 ml-8 shrink-0 truncate pr-4 text-sm font-semibold dark:text-white"
        title={sectionTitle}
      >
        {sectionTitle}
      </p>
      <nav
        aria-label={sectionTitle}
        className="scrollbar-overlay mt-3 flex-1 overflow-x-hidden overflow-y-auto pb-4"
      >
        {groups.map((group) => (
          <div key={group.key} className="mt-5 first:mt-0">
            {group.labelKey && (
              <p className="text-muted-foreground mb-1 ml-8 text-xs font-medium">
                {t(group.labelKey)}
              </p>
            )}
            {group.items.map(renderItem)}
          </div>
        ))}
      </nav>
    </div>
  );
}
