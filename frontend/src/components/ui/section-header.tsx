import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';

import { cn } from '@/lib/utils';
import { formatCount } from '@/utils/dateTimeUtils';

const sectionTitleVariants = cva('', {
  variants: {
    size: {
      // The title of a detail page or panel (a device, a team): the Modal and
      // PanelHeader title role.
      title: 'text-foreground text-xl leading-tight font-semibold',
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
    /**
     * A tally after the title ("Members 7", "2 of 5 allowed"): muted,
     * normal weight, tabular and never set in caps, at every size. A number
     * is formatted with the UI language's digit grouping.
     */
    count?: React.ReactNode;
    /** One muted paragraph under the title. */
    description?: React.ReactNode;
    /** Buttons at the end of the title row. */
    actions?: React.ReactNode;
    /** The heading level in the page outline. */
    as?: 'h2' | 'h3' | 'h4' | 'h5' | 'h6';
  };

/** A section title with an optional description and trailing actions. */
function SectionHeader({
  title,
  count,
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
      {count != null && count !== false ? (
        <span
          data-slot="count"
          className="text-muted-foreground ms-1.5 font-normal tracking-normal normal-case tabular-nums"
        >
          {typeof count === 'number' ? formatCount(count) : count}
        </span>
      ) : null}
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
