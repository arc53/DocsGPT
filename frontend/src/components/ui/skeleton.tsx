import * as React from 'react';

import { cn } from '@/lib/utils';

/** Placeholder block; size it with width/height classes, round it as needed. */
function Skeleton({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="skeleton"
      aria-hidden="true"
      className={cn('bg-muted animate-pulse rounded-md', className)}
      {...props}
    />
  );
}

export { Skeleton };
