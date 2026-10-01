import * as React from 'react';
import { X } from 'lucide-react';
import { Slot } from 'radix-ui';
import { cva, type VariantProps } from 'class-variance-authority';

import { cn, focusRing } from '@/lib/utils';

// Hoisted so the /design gallery can list the keys cva uses.
const badgeVariantOptions = {
  variant: {
    default: 'bg-secondary text-secondary-foreground',
    // Foreground text: muted text is under 4.5:1 on the grey tint.
    neutral: 'bg-muted-foreground/15 text-foreground',
    success: 'bg-success/10 text-success',
    warning: 'bg-warning/10 text-warning',
    destructive: 'bg-destructive/10 text-destructive',
    info: 'bg-info/10 text-info',
    outline: 'border-border text-foreground',
  },
};

const badgeVariants = cva(
  'inline-flex w-fit shrink-0 items-center justify-center gap-1 rounded-full border border-transparent px-2 py-0.5 text-xs font-medium whitespace-nowrap [&>svg]:pointer-events-none [&>svg]:size-3',
  {
    variants: badgeVariantOptions,
    defaultVariants: {
      variant: 'default',
    },
  },
);

type BadgeRemoveProps =
  | { onRemove?: undefined; removeLabel?: undefined }
  | {
      /**
       * Draws a trailing X button that removes the chip (a filter chip).
       * Not for a Badge inside another button (a MultiSelect trigger).
       */
      onRemove: () => void;
      /** The X's accessible name, e.g. "Show all connectors". */
      removeLabel: string;
    };

/**
 * Small status or category pill. Use the `variant` for meaning (success,
 * warning, destructive, info, neutral) instead of raw palette classes.
 * `onRemove` + `removeLabel` make it a removable chip: a 12px X in a 16px
 * round hover well, with a 24px hit area.
 */
function Badge({
  className,
  variant = 'default',
  asChild = false,
  onRemove,
  removeLabel,
  children,
  ...props
}: React.ComponentProps<'span'> &
  VariantProps<typeof badgeVariants> & {
    asChild?: boolean;
  } & BadgeRemoveProps) {
  const Comp = asChild ? Slot.Root : 'span';

  return (
    <Comp
      data-slot="badge"
      data-variant={variant}
      className={cn(
        badgeVariants({ variant }),
        onRemove && 'pr-1.5',
        className,
      )}
      {...props}
    >
      {children}
      {onRemove && (
        <button
          type="button"
          data-slot="badge-remove"
          aria-label={removeLabel}
          onClick={onRemove}
          className={`${focusRing} hover:bg-primary/15 relative inline-flex size-4 shrink-0 cursor-pointer items-center justify-center rounded-full outline-none after:absolute after:-inset-1`}
        >
          <X className="size-3" aria-hidden="true" />
        </button>
      )}
    </Comp>
  );
}

/** Every `variant` key, in declaration order. */
const badgeVariantNames = Object.keys(
  badgeVariantOptions.variant,
) as (keyof typeof badgeVariantOptions.variant)[];

export { Badge, badgeVariantNames, badgeVariants };
