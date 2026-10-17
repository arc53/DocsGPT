import * as React from 'react';

import { cn } from '@/lib/utils';

type DescriptionListContextValue = { layout: 'columns' | 'justified' };

const DescriptionListContext = React.createContext<DescriptionListContextValue>(
  { layout: 'columns' },
);

type DescriptionListProps = React.ComponentProps<'dl'> & {
  /**
   * `columns`: an 8rem label column beside the values (drawers, detail
   * panels). `justified`: label left, value right-aligned (a phone card, a
   * stats dialog).
   */
  layout?: 'columns' | 'justified';
  size?: 'sm' | 'xs';
  /** `justified` only: two label/value pairs per line. */
  columns?: 1 | 2;
};

/** Key/value rows in a `<dl>`. */
function DescriptionList({
  layout = 'columns',
  size = 'sm',
  columns = 1,
  className,
  ...props
}: DescriptionListProps) {
  return (
    <DescriptionListContext.Provider value={{ layout }}>
      <dl
        data-slot="description-list"
        data-layout={layout}
        className={cn(
          size === 'xs' ? 'text-xs' : 'text-sm',
          layout === 'columns'
            ? 'grid grid-cols-[minmax(0,8rem)_minmax(0,1fr)] gap-x-3 gap-y-1'
            : columns === 2
              ? 'grid grid-cols-2 gap-x-6 gap-y-2'
              : 'flex flex-col gap-2',
          className,
        )}
        {...props}
      />
    </DescriptionListContext.Provider>
  );
}

type DescriptionItemProps = Omit<React.ComponentProps<'div'>, 'children'> & {
  label: React.ReactNode;
  children?: React.ReactNode;
  /** Monospace value: ids, URLs, hashes. */
  mono?: boolean;
};

/** One label/value pair. */
function DescriptionItem({
  label,
  mono = false,
  className,
  children,
  ...props
}: DescriptionItemProps) {
  const { layout } = React.useContext(DescriptionListContext);

  return (
    <div
      data-slot="description-item"
      className={cn(
        // `contents` keeps a valid <dl> group without breaking the grid.
        layout === 'columns'
          ? 'contents'
          : 'flex items-start justify-between gap-4',
        className,
      )}
      {...props}
    >
      <dt className="text-muted-foreground">{label}</dt>
      <dd
        className={cn(
          'text-foreground min-w-0 break-words',
          layout === 'justified' && 'text-right tabular-nums',
          mono && 'font-mono',
        )}
      >
        {children}
      </dd>
    </div>
  );
}

export { DescriptionItem, DescriptionList };
export type { DescriptionItemProps, DescriptionListProps };
