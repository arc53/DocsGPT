import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';

import { CurrentSectionHeader } from './SectionPageHeader';
import SectionPills from './SectionPills';

const WIDTH_CLASSES = {
  default: 'max-w-6xl',
  // Admin: wide tables.
  wide: 'max-w-7xl',
  narrow: 'max-w-5xl',
} as const;

/**
 * The frame of every section page (settings, admin, agents, teams): the
 * scroll container, the centred column, the section title and, with `pills`,
 * the phone/tablet destination pills. Content starts 32px under the title.
 */
export default function SectionShell({
  width = 'default',
  pills = false,
  header = true,
  children,
}: {
  width?: keyof typeof WIDTH_CLASSES;
  pills?: boolean;
  /** False for the phone section index, which draws its own title. */
  header?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="h-full overflow-auto p-4 md:p-12">
      <div className={cn('mx-auto w-full', WIDTH_CLASSES[width])}>
        {header ? (
          <>
            <CurrentSectionHeader />
            {pills ? <SectionPills className="mt-4" /> : null}
            <div className="mt-8">{children}</div>
          </>
        ) : (
          children
        )}
      </div>
    </div>
  );
}
