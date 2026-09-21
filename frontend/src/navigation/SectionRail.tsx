import { ArrowLeft } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

import { getSectionItems, type Section } from './sections';

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
  const items = getSectionItems(section, { isAdmin });

  return (
    <>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        onClick={onBack}
        aria-label={backLabel}
        title={backLabel}
        className="text-muted-foreground hover:text-foreground"
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
    </>
  );
}
