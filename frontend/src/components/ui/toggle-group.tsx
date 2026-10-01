import * as React from 'react';
import { ToggleGroup as ToggleGroupPrimitive } from 'radix-ui';

import { buttonVariants } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { formatCount } from '@/utils/dateTimeUtils';

type ToggleSize = 'xs' | 'sm';

const ToggleGroupContext = React.createContext<{
  size: ToggleSize;
  fill: boolean;
}>({ size: 'sm', fill: false });

/** The track's padding per size: sm 32px items in a 38px track, xs 28px in 36px. */
const trackPadding: Record<ToggleSize, string> = {
  sm: 'p-0.75',
  xs: 'p-1',
};

/**
 * The segmented "one of N" (or "any of N") control: pill items in a muted
 * pill track, the on item drawn as `outline` (bg-background, shadow-xs)
 * with a `muted-foreground` border, so it stands out from the track at 3:1
 * in both themes, and the rest as `ghost-muted`. `size="sm"` (38px) sits level
 * with `field` controls in forms and page toolbars; `xs` (36px) is for dense
 * panels. The track hugs its items (scrolling sideways, never wrapping, when
 * they outgrow the row) unless `fill` is set, which spans the row with even
 * items: use it when the group is the only control on its row.
 * Radix makes a `type="single"` group a radiogroup with one Tab stop and
 * arrow keys. A single group sends "" when the on item is clicked again;
 * ignore it in `onValueChange` to keep one value selected.
 *
 * Args:
 *   size: Item and track height, `sm` (default) or `xs`.
 *   fill: Span the row (`w-full`) and share it evenly between the items.
 */
function ToggleGroup({
  className,
  size = 'sm',
  fill = false,
  ...props
}: React.ComponentProps<typeof ToggleGroupPrimitive.Root> & {
  size?: ToggleSize;
  fill?: boolean;
}) {
  const context = React.useMemo(() => ({ size, fill }), [size, fill]);
  return (
    <ToggleGroupContext.Provider value={context}>
      <ToggleGroupPrimitive.Root
        data-slot="toggle-group"
        className={cn(
          'bg-muted flex flex-nowrap items-center gap-1 rounded-full',
          trackPadding[size],
          fill ? 'w-full' : 'no-scrollbar w-fit max-w-full overflow-x-auto',
          className,
        )}
        {...props}
      />
    </ToggleGroupContext.Provider>
  );
}

/**
 * One item of a ToggleGroup.
 *
 * Args:
 *   count: A tally after the label ("All 12", "2 of 5 allowed"): muted,
 *     normal weight and tabular, on the on item too. A number is formatted
 *     with the UI language's digit grouping; a node is drawn as given.
 */
function ToggleGroupItem({
  className,
  count,
  children,
  ...props
}: React.ComponentProps<typeof ToggleGroupPrimitive.Item> & {
  count?: React.ReactNode;
}) {
  const { size, fill } = React.useContext(ToggleGroupContext);
  return (
    <ToggleGroupPrimitive.Item
      data-slot="toggle-group-item"
      className={cn(
        buttonVariants({ variant: 'ghost-muted', size, shape: 'pill' }),
        'data-[state=on]:border-muted-foreground data-[state=on]:bg-background data-[state=on]:text-foreground data-[state=on]:dark:bg-input/30 data-[state=on]:dark:hover:bg-input/50 border border-transparent data-[state=on]:shadow-xs',
        fill && 'min-w-0 flex-1 px-1',
        className,
      )}
      {...props}
    >
      {children}
      {count != null && count !== false ? (
        <span
          data-slot="count"
          className="text-muted-foreground font-normal tabular-nums"
        >
          {typeof count === 'number' ? formatCount(count) : count}
        </span>
      ) : null}
    </ToggleGroupPrimitive.Item>
  );
}

export { ToggleGroup, ToggleGroupItem };
