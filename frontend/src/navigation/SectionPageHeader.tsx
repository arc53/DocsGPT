import { ArrowLeft } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import { useMediaQuery } from '@/hooks';
import { cn } from '@/lib/utils';

import type { Section, SectionItem } from './sections';

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
  const { isMobile, isTablet } = useMediaQuery();

  if (!(isMobile || isTablet)) return null;
  return (
    <Link
      to={section.rootPath}
      className={cn(
        'text-muted-foreground hover:text-foreground mb-4 inline-flex items-center gap-2 text-sm',
        className,
      )}
    >
      <ArrowLeft className="size-4 shrink-0" strokeWidth={1.75} aria-hidden />
      {t(section.titleKey)}
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
        {t(item?.labelKey ?? section.titleKey)}
      </h1>
    </div>
  );
}
