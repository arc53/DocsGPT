import * as React from 'react';
import { Slot } from 'radix-ui';
import { cva, type VariantProps } from 'class-variance-authority';

import { cn, focusRing } from '@/lib/utils';

// A card holding a section-toggle (a disclosure panel's header) draws the
// toggle's keyboard focus as a ring round the whole panel; the toggle itself
// has none. Inset, because a scrolling column clips an outset ring.
const sectionToggleRing =
  'has-[[data-variant=section-toggle]:focus-visible]:ring-3 has-[[data-variant=section-toggle]:focus-visible]:ring-ring/50 has-[[data-variant=section-toggle]:focus-visible]:ring-inset';

// Variants by role (DESIGN.md "Card surfaces"): a thing is `filled`, a place
// is `subtle` on the page or `outline` on a card-coloured surface.
const cardVariants = cva(
  `text-card-foreground flex flex-col gap-3 rounded-2xl text-sm transition-colors ${sectionToggleRing}`,
  {
    variants: {
      variant: {
        // A place on a card-coloured surface (a modal, a floating panel), and
        // picker choices, whose selection is the border.
        outline: 'border-border bg-card border',
        // A thing: a tile you open, move, share or delete as a whole
        // (agents, sources, tools, teams, chunks). Also a well (code,
        // output) inside a panel.
        filled: 'bg-muted',
        // A place on the page: form sections, charts, tables, logs.
        subtle: 'border-border bg-background border',
      },
      tone: {
        default: '',
        // Danger zones and a red stat tile: the status soft fill and border.
        // Listed after `variant` so twMerge lets it win on any surface. Muted
        // text fails AA on the red fill, so it reads as foreground inside.
        destructive:
          'border-destructive/50 bg-destructive/10 border [&_.text-muted-foreground]:text-foreground',
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
        // DESIGN "A clickable card that holds a link": a stretched child
        // <button> is the target; the card draws its hover and focus ring.
        within:
          'hover:bg-accent has-[>button:focus-visible]:ring-ring/50 relative has-[>button:focus-visible]:ring-3',
      },
    },
    defaultVariants: {
      variant: 'outline',
      tone: 'default',
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
  tone = 'default',
  padding = 'default',
  interactive = false,
  selected,
  asChild = false,
  ...props
}: CardProps) {
  const Comp = asChild ? Slot.Root : 'div';
  return (
    <Comp
      data-slot="card"
      data-variant={variant}
      data-tone={tone === 'default' ? undefined : tone}
      data-padding={padding}
      data-interactive={
        interactive === 'within' ? 'within' : interactive || undefined
      }
      data-selected={selected || undefined}
      className={cn(
        cardVariants({ variant, tone, padding, interactive }),
        className,
      )}
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

type CardTitleProps = React.ComponentProps<'div'> & {
  /** The heading level in the page outline; a plain `div` by default. */
  as?: 'div' | 'h2' | 'h3' | 'h4';
};

function CardTitle({ className, as: Comp = 'div', ...props }: CardTitleProps) {
  return (
    <Comp
      data-slot="card-title"
      className={cn('text-foreground leading-snug font-semibold', className)}
      {...props}
    />
  );
}

/** A muted line under a CardTitle; `size="xs"` for tiles (12px, relaxed). */
function CardDescription({
  className,
  size = 'default',
  ...props
}: React.ComponentProps<'div'> & { size?: 'default' | 'xs' }) {
  return (
    <div
      data-slot="card-description"
      className={cn(
        'text-muted-foreground',
        size === 'xs' ? 'text-xs leading-relaxed' : 'text-sm',
        className,
      )}
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
