import * as React from 'react';
import { cva } from 'class-variance-authority';

import { cn, focusRing } from '@/lib/utils';
import { Slot, Tabs as TabsPrimitive } from 'radix-ui';

function Tabs({
  className,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.Root>) {
  return (
    <TabsPrimitive.Root
      data-slot="tabs"
      className={cn('flex flex-col', className)}
      {...props}
    />
  );
}

function TabsList({
  className,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.List>) {
  return (
    <TabsPrimitive.List
      data-slot="tabs-list"
      // Tabs sit on a 1px baseline. No scroll container, which would clip
      // the triggers' focus ring.
      className={cn('border-border flex flex-nowrap border-b', className)}
      {...props}
    />
  );
}

/**
 * The one tab look: muted text on a transparent 2px bottom border (so the
 * row height never moves), foreground and a primary underline when active.
 * Radix triggers are active on data-state; route tabs (NavTab) on
 * aria-current="page".
 */
const tabsTriggerVariants = cva(
  `${focusRing} focus-visible:border-ring text-muted-foreground hover:text-foreground hover:border-border inline-flex items-center justify-center gap-2 rounded-none border-b-2 border-transparent text-sm font-medium whitespace-nowrap transition-colors outline-none disabled:pointer-events-none disabled:opacity-50 data-[state=active]:border-primary data-[state=active]:text-foreground aria-[current=page]:border-primary aria-[current=page]:text-foreground`,
  {
    variants: {
      size: {
        default: 'h-9 px-4 py-2',
      },
    },
    defaultVariants: { size: 'default' },
  },
);

function TabsTrigger({
  className,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      data-slot="tabs-trigger"
      className={cn(tabsTriggerVariants(), className)}
      {...props}
    />
  );
}

/**
 * A route tab: the tab look on its only child (a router `<Link>`, or a
 * `<span>` for the current page), inside a `<nav>`. Not a Radix tab: route
 * links get no `role="tab"` and no arrow-key roving. `current` sets
 * `aria-current="page"`, which draws the active underline.
 */
function NavTab({
  className,
  current = false,
  ...props
}: React.ComponentProps<typeof Slot.Root> & {
  /** The tab for the page on screen. */
  current?: boolean;
}) {
  return (
    <Slot.Root
      data-slot="nav-tab"
      aria-current={current ? 'page' : undefined}
      className={cn(tabsTriggerVariants(), className)}
      {...props}
    />
  );
}

function TabsContent({
  className,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.Content>) {
  return (
    <TabsPrimitive.Content
      data-slot="tabs-content"
      className={cn('flex-1 outline-none', className)}
      {...props}
    />
  );
}

export {
  NavTab,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  tabsTriggerVariants,
};
