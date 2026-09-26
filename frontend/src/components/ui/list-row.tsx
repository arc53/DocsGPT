import * as React from 'react';
import { Slot } from 'radix-ui';

import { cn } from '@/lib/utils';

/** A list of rows split by 1px rules. Draws no box; wrap it in a Card for one. */
function ListRows({ className, ...props }: React.ComponentProps<'ul'>) {
  return (
    <ul
      data-slot="list-rows"
      className={cn('divide-border divide-y', className)}
      {...props}
    />
  );
}

type ListRowProps = Omit<React.ComponentProps<'li'>, 'title'> & {
  /** An Avatar, an icon or an icon square. */
  leading?: React.ReactNode;
  title: React.ReactNode;
  /** One muted line under the title. */
  description?: React.ReactNode;
  /** A control, badge or chevron at the end of the row. */
  trailing?: React.ReactNode;
  /** The whole row is a target: hover fill and an inset focus ring. */
  interactive?: boolean;
  /**
   * Render the row's content into its single child (a `<Link>` or
   * `<button>`), wrapped in the `<li>`.
   */
  asChild?: boolean;
};

/** An identity row: leading art, a truncating title and meta, a trailing control. */
function ListRow({
  leading,
  title,
  description,
  trailing,
  interactive = false,
  asChild = false,
  className,
  children,
  ...props
}: ListRowProps) {
  const rowClass = cn(
    'flex items-center gap-3 px-4 py-3',
    // Inset, because a row list usually sits in an overflow-hidden rounded
    // box that would clip an outer ring.
    interactive &&
      'hover:bg-accent focus-visible:ring-ring/50 w-full text-left transition-colors outline-none focus-visible:ring-3 focus-visible:ring-inset',
    !asChild && className,
  );
  const content = (
    <>
      {leading}
      <div className="min-w-0 flex-1">
        <p className="text-foreground truncate text-sm font-medium">{title}</p>
        {description ? (
          <p className="text-muted-foreground truncate text-xs">
            {description}
          </p>
        ) : null}
      </div>
      {trailing}
    </>
  );

  if (asChild) {
    return (
      <li data-slot="list-row" className={className} {...props}>
        <Slot.Root className={rowClass}>
          {React.isValidElement(children)
            ? React.cloneElement(
                children as React.ReactElement<{ children?: React.ReactNode }>,
                undefined,
                content,
              )
            : content}
        </Slot.Root>
      </li>
    );
  }

  return (
    <li data-slot="list-row" className={rowClass} {...props}>
      {content}
    </li>
  );
}

export { ListRow, ListRows };
export type { ListRowProps };
