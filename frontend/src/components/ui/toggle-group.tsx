import * as React from 'react';
import { ToggleGroup as ToggleGroupPrimitive } from 'radix-ui';

import { buttonVariants } from '@/components/ui/button';
import { cn } from '@/lib/utils';

type ToggleSize = 'xs' | 'sm';

const ToggleGroupSizeContext = React.createContext<ToggleSize>('sm');

/**
 * The segmented "one of N" (or "any of N") control: pill items, the on item
 * drawn as `outline` (bg-background, border, shadow-xs) and the rest as
 * `ghost-muted`. Radix makes a `type="single"` group a radiogroup with one
 * Tab stop and arrow keys. A single group sends "" when the on item is
 * clicked again; ignore it in `onValueChange` to keep one value selected.
 */
function ToggleGroup({
  className,
  size = 'sm',
  ...props
}: React.ComponentProps<typeof ToggleGroupPrimitive.Root> & {
  size?: ToggleSize;
}) {
  return (
    <ToggleGroupSizeContext.Provider value={size}>
      <ToggleGroupPrimitive.Root
        data-slot="toggle-group"
        className={cn('flex flex-wrap items-center gap-1', className)}
        {...props}
      />
    </ToggleGroupSizeContext.Provider>
  );
}

function ToggleGroupItem({
  className,
  ...props
}: React.ComponentProps<typeof ToggleGroupPrimitive.Item>) {
  const size = React.useContext(ToggleGroupSizeContext);
  return (
    <ToggleGroupPrimitive.Item
      data-slot="toggle-group-item"
      className={cn(
        buttonVariants({ variant: 'ghost-muted', size, shape: 'pill' }),
        'data-[state=on]:border-border data-[state=on]:bg-background data-[state=on]:text-foreground data-[state=on]:dark:border-input data-[state=on]:dark:bg-input/30 data-[state=on]:dark:hover:bg-input/50 border border-transparent data-[state=on]:shadow-xs',
        className,
      )}
      {...props}
    />
  );
}

export { ToggleGroup, ToggleGroupItem };
