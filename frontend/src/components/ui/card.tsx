import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';

import { cn, focusRing } from '@/lib/utils';

const cardVariants = cva(
  'text-card-foreground flex flex-col gap-3 rounded-2xl text-sm transition-colors',
  {
    variants: {
      variant: {
        // Bordered surface: lists of entities, panels, headers.
        outline: 'border-border bg-card border',
        // Filled, no border: tiles on a card-coloured page (sources, tools).
        filled: 'bg-muted',
        // Bordered on a muted page background.
        subtle: 'border-border bg-background border',
      },
      padding: {
        none: 'p-0',
        sm: 'p-3',
        default: 'p-4',
        lg: 'p-6',
      },
      interactive: {
        false: '',
        // Whole card is a target: picker tiles, navigable list items.
        true: `${focusRing} hover:border-primary/40 hover:bg-accent focus-visible:border-ring cursor-pointer text-left outline-none data-[selected=true]:border-primary data-[selected=true]:bg-primary/5`,
      },
    },
    defaultVariants: {
      variant: 'outline',
      padding: 'default',
      interactive: false,
    },
  },
);

type CardProps = React.ComponentProps<'div'> &
  VariantProps<typeof cardVariants> & {
    /** Render the card as its child, e.g. a `<button>` or `<Link>`. */
    asChild?: boolean;
    /** Highlights an interactive card as the current choice. */
    selected?: boolean;
  };

function Card({
  className,
  variant = 'outline',
  padding = 'default',
  interactive = false,
  selected,
  asChild = false,
  ...props
}: CardProps) {
  const Comp = asChild ? Slot : 'div';
  return (
    <Comp
      data-slot="card"
      data-variant={variant}
      data-padding={padding}
      data-interactive={interactive || undefined}
      data-selected={selected || undefined}
      className={cn(cardVariants({ variant, padding, interactive }), className)}
      {...props}
    />
  );
}

/** Title row with an optional trailing action (menu, chevron, button). */
function CardHeader({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="card-header"
      className={cn(
        'grid auto-rows-min grid-cols-[1fr_auto] items-start gap-x-3 gap-y-1',
        className,
      )}
      {...props}
    />
  );
}

function CardTitle({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="card-title"
      className={cn('text-foreground leading-snug font-semibold', className)}
      {...props}
    />
  );
}

function CardDescription({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="card-description"
      className={cn('text-muted-foreground text-sm', className)}
      {...props}
    />
  );
}

/** Slot in the header's top-right corner. */
function CardAction({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="card-action"
      className={cn('col-start-2 row-span-2 row-start-1 self-start', className)}
      {...props}
    />
  );
}

function CardContent({ className, ...props }: React.ComponentProps<'div'>) {
  return <div data-slot="card-content" className={cn(className)} {...props} />;
}

/** Meta row or controls at the bottom; pushes to the end of tall cards. */
function CardFooter({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="card-footer"
      className={cn(
        'text-muted-foreground mt-auto flex items-center gap-2 text-xs',
        className,
      )}
      {...props}
    />
  );
}

export {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardAction,
  CardContent,
  CardFooter,
  cardVariants,
};
export type { CardProps };
