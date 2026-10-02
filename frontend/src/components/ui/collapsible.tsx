import * as React from 'react';
import { ChevronRight } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

// Just past the 300ms transition: settles the body when no transitionend
// comes (reduced motion, a tab in the background).
const SETTLE_FALLBACK_MS = 350;

type CollapsibleProps = React.ComponentProps<'div'> & {
  /** Shown at its content height when true, collapsed to nothing when false. */
  open: boolean;
};

/**
 * The height-animated disclosure body: a grid that goes from `0fr` to `1fr`
 * rows (and fades) over 300ms, with the content clipped in one track. The
 * content stays mounted while closed but is `inert`, so its fields leave the
 * tab order and the accessibility tree. It clips only while closed or
 * moving; once open it stops, so a field's focus ring isn't cut off. The
 * trigger is a CollapsibleTrigger (or, for a framed row, a `<button
 * aria-expanded aria-controls={id}>`), so pass `id` here.
 */
function Collapsible({
  open,
  className,
  children,
  onTransitionEnd,
  ...props
}: CollapsibleProps) {
  const [settled, setSettled] = React.useState(open);
  const [prevOpen, setPrevOpen] = React.useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    setSettled(false);
  }

  React.useEffect(() => {
    if (!open || settled) return;
    const timer = window.setTimeout(() => setSettled(true), SETTLE_FALLBACK_MS);
    return () => window.clearTimeout(timer);
  }, [open, settled]);

  const clipped = !open || !settled;

  return (
    <div
      data-slot="collapsible"
      data-state={open ? 'open' : 'closed'}
      inert={!open}
      className={cn(
        'grid transition-[grid-template-rows,opacity] duration-300 ease-out motion-reduce:transition-none',
        open ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0',
        className,
      )}
      onTransitionEnd={(event) => {
        if (
          open &&
          event.target === event.currentTarget &&
          event.propertyName === 'grid-template-rows'
        ) {
          setSettled(true);
        }
        onTransitionEnd?.(event);
      }}
      {...props}
    >
      <div className={cn('min-h-0 min-w-0', clipped && 'overflow-hidden')}>
        {children}
      </div>
    </div>
  );
}

type CollapsibleTriggerProps = Omit<
  React.ComponentProps<typeof Button>,
  'variant' | 'size' | 'shape' | 'tone' | 'onClick' | 'asChild'
> & {
  /** Whether the Collapsible it controls is open. */
  open: boolean;
  /** Called with the next state on click. */
  onOpenChange?: (open: boolean) => void;
  /** The Collapsible's `id`, for `aria-controls`. */
  controls: string;
  /**
   * `inline` (default): the `link sm` toggle for a group in a form, modal or
   * drawer. `section`: a section panel's header (NewAgent's Advanced,
   * Guardrails) with an 18px semibold title; only inside a Card, which
   * draws its focus ring.
   */
  look?: 'inline' | 'section';
  /** `sm` draws a 12px chevron instead of 16px. */
  chevron?: 'default' | 'sm';
};

/**
 * The disclosure toggle over a Collapsible: a lucide ChevronRight that
 * turns while open, then the label, pulled `-ml-3` so the chevron lines up
 * with the text above. Sets `aria-expanded` and `aria-controls`. Layout
 * classes only.
 */
function CollapsibleTrigger({
  open,
  onOpenChange,
  controls,
  look = 'inline',
  chevron = 'default',
  className,
  children,
  ...props
}: CollapsibleTriggerProps) {
  const section = look === 'section';
  return (
    <Button
      type="button"
      variant={section ? 'section-toggle' : 'link'}
      size="sm"
      aria-expanded={open}
      aria-controls={controls}
      className={cn('-ml-3 w-fit justify-start', className)}
      onClick={() => onOpenChange?.(!open)}
      {...props}
    >
      <ChevronRight
        aria-hidden="true"
        className={cn(
          'transition-transform duration-200 motion-reduce:transition-none',
          chevron === 'sm' && 'size-3',
          open && 'rotate-90',
        )}
      />
      {section ? (
        <span className="text-lg font-semibold">{children}</span>
      ) : (
        children
      )}
    </Button>
  );
}

export { Collapsible, CollapsibleTrigger };
export type { CollapsibleProps, CollapsibleTriggerProps };
