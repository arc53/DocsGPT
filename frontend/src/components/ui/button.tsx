import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';

import { Spinner } from '@/components/ui/spinner';
import { cn, focusRing, invalidState } from '@/lib/utils';

const buttonVariants = cva(
  `${focusRing} ${invalidState} inline-flex items-center justify-center gap-2 whitespace-nowrap text-sm font-medium transition-all disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg:not([class*='size-'])]:size-4 shrink-0 [&_svg]:shrink-0 outline-none focus-visible:border-ring`,
  // Icon padding (has-[>svg]) also matches an svg inside the invisible label
  // wrapper that `loading` adds, so a busy icon button keeps its width.
  {
    variants: {
      variant: {
        default: 'bg-primary text-primary-foreground hover:bg-primary/90',
        destructive:
          'bg-destructive text-destructive-foreground hover:bg-destructive/90 focus-visible:ring-destructive/20 dark:focus-visible:ring-destructive/40 dark:bg-destructive/60',
        'destructive-outline':
          'border border-destructive text-destructive bg-transparent hover:bg-destructive hover:text-destructive-foreground focus-visible:ring-destructive/20 dark:focus-visible:ring-destructive/40',
        outline:
          'border bg-background shadow-xs hover:bg-accent hover:text-accent-foreground dark:bg-input/30 dark:border-input dark:hover:bg-input/50',
        'outline-primary':
          'border border-primary text-primary bg-transparent hover:bg-primary hover:text-primary-foreground',
        secondary:
          'bg-secondary text-secondary-foreground hover:bg-secondary/80',
        ghost:
          'hover:bg-accent hover:text-accent-foreground dark:hover:bg-accent/50',
        'ghost-muted':
          'text-muted-foreground hover:bg-accent hover:text-foreground dark:hover:bg-accent/50',
        // Icon actions that remove something: muted at rest, red on hover.
        'ghost-destructive':
          'text-muted-foreground hover:bg-accent hover:text-destructive dark:hover:bg-accent/50',
        // The same two on a row that is already bg-accent or
        // bg-sidebar-accent (a highlighted Command item, a hovered card or
        // sidebar row), where an accent hover would be invisible.
        'ghost-on-accent':
          'text-muted-foreground hover:bg-foreground/15 hover:text-foreground dark:hover:bg-foreground/20',
        'ghost-destructive-on-accent':
          'text-muted-foreground hover:bg-destructive/15 hover:text-destructive dark:hover:bg-destructive/25',
        link: 'text-primary underline-offset-4 hover:underline',
        // Popover combobox triggers: mirrors SelectTrigger so the two sit
        // side by side. Set data-placeholder while empty to mute the text.
        // Rows in the navigation sidebar (Help, Settings, section links).
        // Pair with aria-current="page" for the active row; the compound
        // variant below sets the row's own padding and radius.
        'sidebar-item':
          'text-foreground hover:bg-sidebar-accent aria-[current=page]:bg-sidebar-accent',
        combobox:
          'border border-border bg-card font-normal shadow-xs hover:bg-accent data-placeholder:text-muted-foreground',
        // Underline tabs (FilePicker's drives, the agent page sub-nav). Mark the
        // current tab with data-active; the 2px border is always there so the
        // row height doesn't move. The compound variant squares the corners.
        tab: 'border-b-2 border-transparent text-muted-foreground hover:text-foreground hover:border-border data-[active=true]:border-primary data-[active=true]:text-foreground',
        // A section panel's disclosure header (NewAgent's Advanced,
        // Guardrails): a foreground title with a primary chevron and a primary
        // underline on hover. It draws no ring of its own; the panel around it
        // shows focus with has-[[data-variant=section-toggle]:focus-visible].
        'section-toggle':
          'text-foreground underline-offset-4 decoration-primary hover:underline focus-visible:ring-0 [&>svg]:text-primary',
      },
      size: {
        default: 'h-9 px-4 py-2 has-[>svg,>[data-slot=button-label]>svg]:px-3',
        xs: "h-7 gap-1 px-2 text-xs has-[>svg,>[data-slot=button-label]>svg]:px-1.5 [&_svg:not([class*='size-'])]:size-3.5",
        sm: 'h-8 gap-1.5 px-3 has-[>svg,>[data-slot=button-label]>svg]:px-2.5',
        lg: 'h-10 px-6 has-[>svg,>[data-slot=button-label]>svg]:px-4',
        // The form-row height (42px), shared with Input default and
        // SelectTrigger lg, for pickers and buttons that sit among fields.
        field: 'h-10.5 px-4 has-[>svg,>[data-slot=button-label]>svg]:px-3',
        icon: 'size-9',
        'icon-xs': 'size-7',
        'icon-sm': 'size-8',
        'icon-lg': 'size-10',
        // A link mid-sentence: no height or padding, so it wraps with the text.
        inline: 'h-auto p-0',
      },
      shape: {
        default: 'rounded-md',
        pill: 'rounded-full',
      },
    },
    compoundVariants: [
      // Pills read as cramped at the rectangular paddings, so widen them.
      {
        shape: 'pill',
        size: 'default',
        class: 'px-5 has-[>svg,>[data-slot=button-label]>svg]:px-4',
      },
      {
        shape: 'pill',
        size: 'lg',
        class: 'px-6 has-[>svg,>[data-slot=button-label]>svg]:px-5',
      },
      // Text starts 21px in, like the Input and SelectTrigger pills beside it.
      {
        shape: 'pill',
        size: 'field',
        class: 'px-5 has-[>svg,>[data-slot=button-label]>svg]:px-4',
      },
      // Tabs sit on a baseline rule, so they never round off.
      { variant: 'tab', class: 'rounded-none' },
      // A padding-free tab (the agent sub-nav) keeps 4px above its underline.
      { variant: 'tab', size: 'inline', class: 'pb-1' },
      // Nav rows line their icons up on the left edge at every size/shape.
      {
        variant: 'sidebar-item',
        class:
          'justify-start gap-2.5 rounded-full pr-0 pl-3 font-normal has-[>svg,>[data-slot=button-label]>svg]:pr-0 has-[>svg,>[data-slot=button-label]>svg]:pl-3',
      },
    ],
    defaultVariants: {
      variant: 'default',
      size: 'default',
      shape: 'default',
    },
  },
);

function Button({
  className,
  variant = 'default',
  size = 'default',
  shape = 'default',
  asChild = false,
  loading = false,
  disabled,
  children,
  ...props
}: React.ComponentProps<'button'> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
    /**
     * Disables the button and draws a 16px spinner over its label. The label
     * stays in the layout (invisible), so the width doesn't jump.
     */
    loading?: boolean;
  }) {
  const Comp = asChild ? Slot : 'button';

  return (
    <Comp
      data-slot="button"
      data-variant={variant}
      data-size={size}
      data-shape={shape}
      data-loading={loading ? '' : undefined}
      aria-busy={loading || undefined}
      disabled={disabled || loading}
      className={cn(
        buttonVariants({ variant, size, shape }),
        loading && 'relative',
        className,
      )}
      {...props}
    >
      {loading && !asChild ? (
        <>
          <span data-slot="button-label" className="invisible contents">
            {children}
          </span>
          <span className="absolute inset-0 flex items-center justify-center">
            <Spinner size="sm" className="size-4" />
          </span>
        </>
      ) : (
        children
      )}
    </Comp>
  );
}

export { Button, buttonVariants };
