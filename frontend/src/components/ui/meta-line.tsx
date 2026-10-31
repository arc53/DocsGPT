import * as React from 'react';

import { cn } from '@/lib/utils';

/**
 * A tile's bottom line: the facts about the item (tokens, agents, account,
 * capabilities, role), joined by a dot and wrapping as a row. It sits in a
 * `CardFooter`, which gives it the muted 12px type. Empty children (null,
 * false) are dropped, and with none left nothing is drawn. An element that
 * renders nothing (RoleMeta for the owner) still counts, so callers test
 * first (`isOwner`, `agentUseCount`) rather than leave a stray dot. A status that may
 * need the reader (Reconnect, Indexing failed) is a Badge, never an item here.
 */
function MetaLine({
  className,
  children,
  ...props
}: React.ComponentProps<'span'>) {
  const items = React.Children.toArray(children).filter(Boolean);
  if (items.length === 0) return null;
  return (
    <span
      data-slot="meta-line"
      className={cn(
        'flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1',
        className,
      )}
      {...props}
    >
      {items.map((item, index) => (
        <React.Fragment key={index}>
          {index > 0 && <span aria-hidden="true">·</span>}
          {item}
        </React.Fragment>
      ))}
    </span>
  );
}

type MetaItemProps = React.ComponentProps<'span'> & {
  /** A lucide icon, drawn at 14px and hidden from screen readers. */
  icon?: React.ReactElement<{ className?: string; 'aria-hidden'?: boolean }>;
};

/** One fact in a `MetaLine`: a 14px icon and a short text that truncates. */
function MetaItem({ icon, className, children, ...props }: MetaItemProps) {
  return (
    <span
      data-slot="meta-item"
      className={cn(
        'inline-flex max-w-full min-w-0 items-center gap-1.5',
        className,
      )}
      {...props}
    >
      {icon
        ? React.cloneElement(icon, {
            className: cn('size-3.5 shrink-0', icon.props.className),
            'aria-hidden': true,
          })
        : null}
      <span className="min-w-0 truncate">{children}</span>
    </span>
  );
}

export { MetaItem, MetaLine };
