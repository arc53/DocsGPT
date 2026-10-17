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
   * The row whose detail is open beside the list (the team page's shared
   * resources drawer): the `bg-secondary` brand tint, kept on hover, and
   * `aria-current`, like a selected TableRow.
   */
  selected?: boolean;
  /**
   * `sm` is the dense row of a narrow side panel (the graph node panel's
   * relationships): 6px / 8px padding, rounded, top-aligned so a small
   * leading mark sits on the title line. Use it in a plain list, not in
   * `ListRows` (no divide rules).
   */
  size?: 'default' | 'sm';
  /**
   * Render the row's content into its single child (a `<Link>` or
   * `<button>`), wrapped in the `<li>`.
   */
  asChild?: boolean;
};

/** The full text of a plain-text title or meta, for `title=` on its truncating line. */
function plainText(node: React.ReactNode): string | undefined {
  return typeof node === 'string' || typeof node === 'number'
    ? String(node)
    : undefined;
}

/**
 * An identity row: leading art, a truncating title and meta, a trailing control.
 * A string `title` / `description` shows its full value on hover; for a node,
 * put the `title` on the node itself.
 */
function ListRow({
  leading,
  title,
  description,
  trailing,
  interactive = false,
  selected = false,
  size = 'default',
  asChild = false,
  className,
  children,
  ...props
}: ListRowProps) {
  const rowClass = cn(
    'flex',
    size === 'sm'
      ? 'items-start gap-2.5 rounded-md px-2 py-1.5'
      : 'items-center gap-3 px-4 py-3',
    // Inset, because a row list usually sits in an overflow-hidden rounded
    // box that would clip an outer ring.
    interactive &&
      'focus-visible:ring-ring/50 w-full text-left transition-colors outline-none focus-visible:ring-3 focus-visible:ring-inset',
    interactive && !selected && 'hover:bg-accent',
    selected && 'bg-secondary hover:bg-secondary',
    !asChild && className,
  );
  const content = (
    <>
      {leading}
      <div className="min-w-0 flex-1">
        <p
          className="text-foreground truncate text-sm font-medium"
          title={plainText(title)}
        >
          {title}
        </p>
        {description ? (
          <p
            className="text-muted-foreground truncate text-xs"
            title={plainText(description)}
          >
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
        <Slot.Root
          className={rowClass}
          aria-current={selected ? 'true' : undefined}
        >
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
    <li
      data-slot="list-row"
      className={rowClass}
      aria-current={selected ? 'true' : undefined}
      {...props}
    >
      {content}
    </li>
  );
}

export { ListRow, ListRows };
export type { ListRowProps };
