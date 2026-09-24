import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { Progress as ProgressPrimitive } from 'radix-ui';

import { cn } from '@/lib/utils';

const progressVariants = cva(
  'bg-muted relative w-full overflow-hidden rounded-full',
  {
    variants: {
      size: {
        sm: 'h-1.5',
        default: 'h-2',
        lg: 'h-3',
      },
    },
    defaultVariants: { size: 'default' },
  },
);

const indicatorVariants = cva(
  'h-full w-(--progress) rounded-full transition-[width] duration-300',
  {
    variants: {
      variant: {
        default: 'bg-primary',
        success: 'bg-success',
        warning: 'bg-warning',
        destructive: 'bg-destructive',
        info: 'bg-info',
      },
    },
    defaultVariants: { variant: 'default' },
  },
);

type ProgressProps = React.ComponentProps<typeof ProgressPrimitive.Root> &
  VariantProps<typeof progressVariants> &
  VariantProps<typeof indicatorVariants> & {
    /** 0 to 100. */
    value?: number;
  };

/** Determinate bar for quotas, indexing and run progress. */
function Progress({
  className,
  value = 0,
  size = 'default',
  variant = 'default',
  ...props
}: ProgressProps) {
  const clamped = Math.max(0, Math.min(100, value));
  return (
    <ProgressPrimitive.Root
      data-slot="progress"
      data-variant={variant}
      value={clamped}
      className={cn(progressVariants({ size }), className)}
      {...props}
    >
      <ProgressPrimitive.Indicator
        data-slot="progress-indicator"
        className={indicatorVariants({ variant })}
        // The only dynamic value; exposed as a custom property so the width
        // itself stays a class (w-(--progress)), which the lint accepts.
        style={{ '--progress': `${clamped}%` } as React.CSSProperties}
      />
    </ProgressPrimitive.Root>
  );
}

export { Progress, progressVariants };
export type { ProgressProps };
