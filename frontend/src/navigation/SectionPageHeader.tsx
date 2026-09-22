import { ArrowLeft } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link, useLocation } from 'react-router-dom';

import { useMediaQuery } from '@/hooks';
import { cn } from '@/lib/utils';

import { getSectionForPath, type Section, type SectionItem } from './sections';
import { useSectionContext } from './useSectionContext';

/**
 * Back to the section's index. Only rendered below ``lg``, where the sidebar
 * is an overlay and the section nav would otherwise sit behind the hamburger.
 * On desktop the sidebar itself is the way back, so this stays out of the way.
 */
export function SectionBackLink({
  section,
  className,
}: {
  section: Section;
  className?: string;
}) {
  const { t } = useTranslation();
  const { pathname } = useLocation();
  const { isMobile, isTablet } = useMediaQuery();

  if (!(isMobile || isTablet)) return null;

  // Up one level, matching the sidebar's back button: out of an agent lands
  // on the agent list, out of a settings page on the settings index. A
  // section whose destinations are views of one page has no level above
  // unless it declares a parent — its pill row does the moving around.
  const to =
    section.parentPath ??
    (section.pageTitle === 'section' ? null : section.rootPath);
  if (!to || to === pathname) return null;

  const parent = section.parentPath
    ? getSectionForPath(section.parentPath)
    : null;
  return (
    <Link
      to={to}
      className={cn(
        'text-muted-foreground hover:text-foreground mb-4 inline-flex items-center gap-2 text-sm',
        className,
      )}
    >
      <ArrowLeft className="size-4 shrink-0" strokeWidth={1.75} aria-hidden />
      {parent ? t(parent.titleKey) : (section.title ?? t(section.titleKey))}
    </Link>
  );
}

/**
 * Title block for a section page: the active item's name, preceded on small
 * screens by a link back to the section index.
 */
export default function SectionPageHeader({
  section,
  item,
  className,
}: {
  section: Section;
  item: SectionItem | null;
  className?: string;
}) {
  const { t } = useTranslation();

  return (
    <div className={cn('flex flex-col', className)}>
      <SectionBackLink section={section} />
      <h1 className="text-foreground dark:text-foreground text-2xl font-bold">
        {item && section.pageTitle !== 'section'
          ? t(item.labelKey)
          : (section.title ?? t(section.titleKey))}
      </h1>
    </div>
  );
}

/**
 * The title block for whichever section page is on screen. Saves every page
 * from resolving its own section, and keeps the heading identical across
 * settings, admin and agents.
 */
export function CurrentSectionHeader({ className }: { className?: string }) {
  const { section, item } = useSectionContext();

  if (!section) return null;
  return (
    <SectionPageHeader section={section} item={item} className={className} />
  );
}
