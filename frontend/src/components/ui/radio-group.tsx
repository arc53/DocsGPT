import { cva, type VariantProps } from 'class-variance-authority';
import { RadioGroup as RadioGroupPrimitive } from 'radix-ui';
import * as React from 'react';

import { cn, focusRing, invalidState } from '@/lib/utils';

// The empty ring is muted-foreground, not shadcn's border-input: input is
// about 1.3:1 on a filled card (bg-muted) and the radio disappears;
// muted-foreground is 4.67:1 or more on background, card and muted in both
// themes. Checked uses secondary-foreground, the lighter primary in dark:
// primary itself is 2.65:1 on bg-muted in dark, this is 5.25:1 (and equals
// primary in light, 4.79:1). `after:-inset-1` makes a 24px hit area.
const radioGroupItemVariants = cva(
  `${focusRing} ${invalidState} border-muted-foreground data-[state=checked]:border-secondary-foreground focus-visible:border-ring relative inline-flex shrink-0 items-center justify-center rounded-full border bg-transparent transition-shadow outline-none after:absolute after:-inset-1 after:rounded-full disabled:cursor-not-allowed disabled:opacity-50`,
  {
    variants: {
      size: {
        // 16px, like Checkbox: cards and option rows.
        default: 'size-4',
        // 14px, like Checkbox sm: dense table cells.
        sm: 'size-3.5',
      },
    },
    defaultVariants: { size: 'default' },
  },
);

/** The checked dot per size: 8px in a 16px ring, 6px in a 14px one. */
const dotSize = { default: 'size-2', sm: 'size-1.5' } as const;

type RadioGroupProps = React.ComponentProps<typeof RadioGroupPrimitive.Root>;

/**
 * One-of-N where each option is a card or row carrying its own content (the
 * chat prompt on the Prompts cards). Radix gives it one Tab stop (the checked
 * item) and arrow keys, even when the items sit in different cards. Name it
 * with `aria-label` or `aria-labelledby`. A plain segmented one-of-N is a
 * ToggleGroup.
 *
 * The group owns its spacing (`grid gap-3`, a list of rows). For cards in a
 * grid or in sections, put the layout element inside the group; the radios
 * in it still form one group.
 *
 * Args:
 *   className: Layout only (no gap), such as `flex` or a margin.
 */
function RadioGroup({ className, ...props }: RadioGroupProps) {
  return (
    <RadioGroupPrimitive.Root
      data-slot="radio-group"
      className={cn('grid gap-3', className)}
      {...props}
    />
  );
}

type RadioGroupItemProps = React.ComponentProps<
  typeof RadioGroupPrimitive.Item
> &
  VariantProps<typeof radioGroupItemVariants>;

/**
 * One radio of a RadioGroup. Name it with a `Label htmlFor` or `aria-label`.
 * On a card that is itself a target (`Card interactive="within"`), put it in
 * a `relative z-10` element so it sits above the card's stretched button.
 *
 * Args:
 *   size: `default` (16px) or `sm` (14px), the Checkbox sizes.
 */
function RadioGroupItem({
  className,
  size = 'default',
  ...props
}: RadioGroupItemProps) {
  const key = size ?? 'default';
  return (
    <RadioGroupPrimitive.Item
      data-slot="radio-group-item"
      data-size={key}
      className={cn(radioGroupItemVariants({ size: key }), className)}
      {...props}
    >
      <RadioGroupPrimitive.Indicator
        data-slot="radio-group-indicator"
        className="flex items-center justify-center"
      >
        <span
          className={cn('bg-secondary-foreground rounded-full', dotSize[key])}
        />
      </RadioGroupPrimitive.Indicator>
    </RadioGroupPrimitive.Item>
  );
}

export { RadioGroup, RadioGroupItem, radioGroupItemVariants };
export type { RadioGroupItemProps, RadioGroupProps };
