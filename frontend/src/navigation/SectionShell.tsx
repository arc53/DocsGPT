import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';

import { CurrentSectionHeader } from './SectionPageHeader';

const WIDTH_CLASSES = {
  default: 'max-w-6xl',
  // Admin: wide tables.
  wide: 'max-w-7xl',
  narrow: 'max-w-5xl',
} as const;

/**
 * The frame of every section page (settings, admin, agents, teams): the
 * scroll container, the centred column and the section title. Content starts
 * 32px under the title.
 */
export default function SectionShell({
  width = 'default',
  header = true,
  title,
  titleAction,
  children,
}: {
  width?: keyof typeof WIDTH_CLASSES;
  /** False for the phone section index, which draws its own title. */
  header?: boolean;
  /** Replaces the section's own title (the new-agent form, which has no nav item). */
  title?: ReactNode;
  /** A page-level control at the title row's end (the agent Overview's ⋯). */
  titleAction?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="h-full overflow-auto p-4 md:p-12">
      <div className={cn('mx-auto w-full', WIDTH_CLASSES[width])}>
        {header ? (
          <>
            <CurrentSectionHeader title={title} titleAction={titleAction} />
            <div className="mt-8">{children}</div>
          </>
        ) : (
          children
        )}
      </div>
    </div>
  );
}
