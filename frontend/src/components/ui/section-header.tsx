import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';

import { cn } from '@/lib/utils';

const sectionTitleVariants = cva('', {
  variants: {
    size: {
      // A section title on a page or panel.
      default: 'text-foreground text-lg font-semibold',
      // An eyebrow: a label set in caps above a group.
      sm: 'text-muted-foreground text-xs font-semibold tracking-wider uppercase',
      // A sub-heading inside a panel, drawer or modal.
      xs: 'text-foreground text-sm font-semibold',
    },
    tone: {
      default: '',
      // Danger zones only.
      destructive: 'text-destructive',
    },
  },
  defaultVariants: { size: 'default', tone: 'default' },
});

type SectionHeaderProps = Omit<React.ComponentProps<'div'>, 'title'> &
  VariantProps<typeof sectionTitleVariants> & {
    title: React.ReactNode;
    /** One muted paragraph under the title. */
    description?: React.ReactNode;
    /** Buttons at the end of the title row. */
    actions?: React.ReactNode;
    /** The heading level in the page outline. */
    as?: 'h2' | 'h3' | 'h4';
  };

/** A section title with an optional description and trailing actions. */
function SectionHeader({
  title,
  description,
  actions,
  as: Heading = 'h2',
  size,
  tone,
  className,
  ...props
}: SectionHeaderProps) {
  const heading = (
    <Heading className={cn(sectionTitleVariants({ size, tone }))}>
      {title}
    </Heading>
  );
  const text = description ? (
    <div className="flex min-w-0 flex-col gap-1">
      {heading}
      <p className="text-muted-foreground text-sm">{description}</p>
    </div>
  ) : (
    heading
  );

  return (
    <div
      data-slot="section-header"
      className={cn(
        actions &&
          'flex flex-wrap items-center justify-between gap-x-4 gap-y-2',
        className,
      )}
      {...props}
    >
      {text}
      {actions ? (
        <div className="flex shrink-0 items-center gap-2">{actions}</div>
      ) : null}
    </div>
  );
}

export { SectionHeader, sectionTitleVariants };
export type { SectionHeaderProps };
