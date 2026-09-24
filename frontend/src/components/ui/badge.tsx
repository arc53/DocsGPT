import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';

import { cn } from '@/lib/utils';

const badgeVariants = cva(
  'inline-flex w-fit shrink-0 items-center justify-center gap-1 rounded-full border border-transparent px-2 py-0.5 text-xs font-medium whitespace-nowrap [&>svg]:pointer-events-none [&>svg]:size-3',
  {
    variants: {
      variant: {
        default: 'bg-primary/10 text-primary dark:bg-primary/20',
        neutral: 'bg-muted-foreground/15 text-muted-foreground',
        success: 'bg-success/10 text-success dark:bg-success/15',
        warning: 'bg-warning/10 text-warning dark:bg-warning/15',
        destructive:
          'bg-destructive/10 text-destructive dark:bg-destructive/15',
        info: 'bg-info/10 text-info dark:bg-info/15',
        outline: 'border-border text-foreground',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  },
);

/**
 * Small status or category pill. Use the `variant` for meaning (success,
 * warning, destructive, info, neutral) instead of raw palette classes.
 */
function Badge({
  className,
  variant = 'default',
  asChild = false,
  ...props
}: React.ComponentProps<'span'> &
  VariantProps<typeof badgeVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot : 'span';

  return (
    <Comp
      data-slot="badge"
      data-variant={variant}
      className={cn(badgeVariants({ variant }), className)}
      {...props}
    />
  );
}

export { Badge, badgeVariants };
