import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';

import { cn, focusRing } from '@/lib/utils';
import * as TabsPrimitive from '@radix-ui/react-tabs';

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

const tabsListVariants = cva('flex flex-nowrap', {
  variants: {
    variant: {
      // Pill tabs that scroll sideways on narrow screens.
      default: 'no-scrollbar snap-x overflow-x-auto scroll-smooth md:space-x-4',
      // Underline tabs sit on a 1px baseline. No scroll container, which
      // would clip the triggers' focus ring.
      underline: 'border-border border-b',
    },
  },
  defaultVariants: { variant: 'default' },
});

function TabsList({
  className,
  variant = 'default',
  ...props
}: React.ComponentProps<typeof TabsPrimitive.List> &
  VariantProps<typeof tabsListVariants>) {
  return (
    <TabsPrimitive.List
      data-slot="tabs-list"
      data-variant={variant}
      className={cn(tabsListVariants({ variant }), className)}
      {...props}
    />
  );
}

const tabsTriggerVariants = cva(
  `${focusRing} text-muted-foreground hover:text-foreground text-sm whitespace-nowrap outline-none disabled:pointer-events-none disabled:opacity-50`,
  {
    variants: {
      variant: {
        default:
          'data-[state=active]:bg-muted data-[state=active]:text-foreground dark:data-[state=active]:bg-accent snap-start rounded-3xl px-4 py-2 font-bold transition-colors',
        // The same pixels as Button variant="tab": muted text on a
        // transparent 2px bottom border, foreground and a primary underline
        // when active.
        underline:
          'focus-visible:border-ring inline-flex h-9 items-center justify-center gap-2 rounded-none border-b-2 border-transparent px-4 py-2 font-medium transition-all hover:border-border data-[state=active]:border-primary data-[state=active]:text-foreground',
      },
    },
    defaultVariants: { variant: 'default' },
  },
);

function TabsTrigger({
  className,
  variant = 'default',
  ...props
}: React.ComponentProps<typeof TabsPrimitive.Trigger> &
  VariantProps<typeof tabsTriggerVariants>) {
  return (
    <TabsPrimitive.Trigger
      data-slot="tabs-trigger"
      data-variant={variant}
      className={cn(tabsTriggerVariants({ variant }), className)}
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

export { Tabs, TabsList, TabsTrigger, TabsContent };
