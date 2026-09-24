import { ArrowLeft } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

import { getSectionItems, type Section } from './sections';
import { useSidebarLevel } from './SidebarLevelProvider';

type SectionRailProps = {
  section: Section;
  activeItemKey?: string;
  isAdmin: boolean;
  onBack: () => void;
  backLabel: string;
};

/**
 * Collapsed-sidebar counterpart to ``SectionNav``: the same destinations as
 * icons, so collapsing the sidebar inside a section still leaves the section
 * navigable instead of stranding the user on one page.
 */
export default function SectionRail({
  section,
  activeItemKey,
  isAdmin,
  onBack,
  backLabel,
}: SectionRailProps) {
  const { t } = useTranslation();
  const { goToLevel } = useSidebarLevel();
  const items = getSectionItems(section, { isAdmin });

  return (
    // Keyed on the section so switching level replays the fade: the rail is
    // too narrow to slide panels through, but it should not swap in place
    // with no acknowledgement either.
    <div
      key={section.key}
      className="animate-in fade-in flex flex-col items-center gap-2 duration-200 motion-reduce:animate-none"
    >
      <Button
        type="button"
        variant="ghost-muted"
        size="icon"
        onClick={onBack}
        aria-label={backLabel}
        title={backLabel}
      >
        <ArrowLeft className="size-5" strokeWidth={1.75} />
      </Button>
      <div className="bg-border my-1 h-px w-6 shrink-0" aria-hidden />
      {items.map((item) => {
        const label = t(item.labelKey);
        const isActive = item.key === activeItemKey;
        const Icon = item.icon;
        return (
          <Link
            key={item.key}
            to={item.path}
            onClick={(event) => {
              if (event.metaKey || event.ctrlKey || event.shiftKey) return;
              event.preventDefault();
              goToLevel(item.path);
            }}
            aria-label={label}
            aria-current={isActive ? 'page' : undefined}
            title={label}
            className={cn(
              'hover:bg-sidebar-accent text-muted-foreground hover:text-foreground flex size-9 items-center justify-center rounded-full',
              isActive && 'bg-sidebar-accent text-foreground',
            )}
          >
            <Icon className="size-5" strokeWidth={1.75} aria-hidden />
          </Link>
        );
      })}
    </div>
  );
}
