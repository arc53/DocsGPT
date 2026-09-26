import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';

import { cn } from '@/lib/utils';

const alertVariants = cva(
  // The icon has its own 16px column and sits centred on the text block
  // (spanning a title and its description); everything else goes in the
  // text column. The icon takes the text colour, so the two always match.
  'relative grid w-full grid-cols-[0_1fr] gap-y-1 rounded-xl border px-4 py-3 text-sm has-[>svg]:grid-cols-[calc(var(--spacing)*4)_1fr] has-[>svg]:gap-x-3 [&>svg]:size-4 [&>svg]:self-center [&>svg]:text-current has-[>[data-slot=alert-title]]:[&>svg]:row-span-2 [&>:not(svg)]:col-start-2',
  {
    variants: {
      variant: {
        default: 'bg-background text-foreground',
        // The grey box, by name (a guardrail "not evaluated" outcome); the
        // same classes as default, which is the component's own base tone.
        neutral: 'bg-background text-foreground',
        destructive: 'border-destructive/50 bg-destructive/10 text-destructive',
        success: 'border-success/50 bg-success/10 text-success',
        warning: 'border-warning/50 bg-warning/10 text-warning',
        info: 'border-info/50 bg-info/10 text-info',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  },
);

function Alert({
  className,
  variant = 'default',
  ...props
}: React.ComponentProps<'div'> & VariantProps<typeof alertVariants>) {
  return (
    <div
      data-slot="alert"
      data-variant={variant}
      // A success notice confirms rather than interrupts, so it is polite.
      role={variant === 'success' ? 'status' : 'alert'}
      className={cn(alertVariants({ variant }), className)}
      {...props}
    />
  );
}

function AlertTitle({ className, ...props }: React.ComponentProps<'h5'>) {
  return (
    <h5
      data-slot="alert-title"
      className={cn('leading-none font-medium tracking-tight', className)}
      {...props}
    />
  );
}

function AlertDescription({
  className,
  ...props
}: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="alert-description"
      className={cn('text-sm [&_p]:leading-relaxed', className)}
      {...props}
    />
  );
}

export { Alert, AlertTitle, AlertDescription };
