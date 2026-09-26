import { ArrowLeft } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import { Button } from '@/components/ui/button';

import { getVisibleGroups, type Section, type SectionItem } from './sections';
import { useSidebarLevel } from './SidebarLevelProvider';

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
  const { goToLevel } = useSidebarLevel();
  const groups = getVisibleGroups(section, { isAdmin });
  const sectionTitle = section.title ?? t(section.titleKey);

  const renderItem = (item: SectionItem) => {
    const isActive = item.key === activeItemKey;
    const Icon = item.icon;
    return (
      <Button
        key={item.key}
        variant="sidebar-item"
        asChild
        className="mx-4 my-1 flex"
      >
        <Link
          to={item.path}
          onClick={(event) => {
            // Same level, so nothing slides — but routing through the level
            // provider still renders the page at low priority, which keeps the
            // highlight moving under the cursor instead of after the mount.
            if (event.metaKey || event.ctrlKey || event.shiftKey) return;
            event.preventDefault();
            goToLevel(item.path);
            onNavigate?.();
          }}
          aria-current={isActive ? 'page' : undefined}
        >
          <Icon className="text-muted-foreground size-5 shrink-0" aria-hidden />
          <span className="truncate">{t(item.labelKey)}</span>
        </Link>
      </Button>
    );
  };

  return (
    <div className="flex h-full flex-col">
      <Button
        type="button"
        variant="sidebar-item"
        onClick={onBack}
        className="mx-4 mt-4 flex shrink-0"
      >
        <ArrowLeft
          className="text-muted-foreground size-5 shrink-0"
          aria-hidden
        />
        <span className="truncate">{backLabel}</span>
      </Button>
      <p
        className="text-foreground mt-6 ml-8 shrink-0 truncate pr-4 text-sm font-semibold"
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
