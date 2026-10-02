import type React from 'react';
import { ArrowLeft } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link, useLocation } from 'react-router-dom';

import { useMediaQuery } from '@/hooks';
import { cn, focusRing } from '@/lib/utils';

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
  const { isMobile } = useMediaQuery();

  if (!isMobile) return null;

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
        focusRing,
        'text-muted-foreground hover:text-foreground mb-4 inline-flex items-center gap-2 rounded-sm text-sm outline-none',
        className,
      )}
    >
      <ArrowLeft className="size-4 shrink-0" aria-hidden />
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
  title,
  titleAction,
  className,
}: {
  section: Section;
  item: SectionItem | null;
  /** Replaces the resolved title. */
  title?: React.ReactNode;
  /** A control at the end of the title row. */
  titleAction?: React.ReactNode;
  className?: string;
}) {
  const { t } = useTranslation();
  const heading = (
    <h1 className="text-foreground text-2xl font-bold">
      {title ??
        (item && section.pageTitle !== 'section'
          ? t(item.labelKey)
          : (section.title ?? t(section.titleKey)))}
    </h1>
  );

  return (
    <div className={cn('flex flex-col', className)}>
      <SectionBackLink section={section} />
      {titleAction ? (
        <div className="flex items-center justify-between gap-3">
          {heading}
          {titleAction}
        </div>
      ) : (
        heading
      )}
    </div>
  );
}

/**
 * The title block for whichever section page is on screen. Saves every page
 * from resolving its own section, and keeps the heading identical across
 * settings, admin and agents.
 */
export function CurrentSectionHeader({
  title,
  titleAction,
  className,
}: {
  title?: React.ReactNode;
  titleAction?: React.ReactNode;
  className?: string;
}) {
  const { section, item } = useSectionContext();

  if (!section) return null;
  return (
    <SectionPageHeader
      section={section}
      item={item}
      title={title}
      titleAction={titleAction}
      className={className}
    />
  );
}
