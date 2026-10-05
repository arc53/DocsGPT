import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';

import { cn } from '@/lib/utils';

const skeletonVariants = cva('animate-pulse rounded-sm', {
  variants: {
    surface: {
      // Bars on a card or background surface.
      default: 'bg-muted',
      // Bars inside a muted tile (a `Card variant="filled"` mirror), where
      // `bg-muted` would vanish.
      muted: 'bg-muted-foreground/20',
    },
  },
  defaultVariants: { surface: 'default' },
});

type SkeletonProps = React.ComponentProps<'div'> &
  VariantProps<typeof skeletonVariants>;

/** Placeholder block; size it with width/height classes. Bars keep the default radius. */
function Skeleton({ className, surface = 'default', ...props }: SkeletonProps) {
  return (
    <div
      data-slot="skeleton"
      data-surface={surface}
      aria-hidden="true"
      className={cn(skeletonVariants({ surface }), className)}
      {...props}
    />
  );
}

export { Skeleton, skeletonVariants };
