import * as React from 'react';

import { cn } from '@/lib/utils';

type CollapsibleProps = React.ComponentProps<'div'> & {
  /** Shown at its content height when true, collapsed to nothing when false. */
  open: boolean;
};

/**
 * The height-animated disclosure body: a grid that goes from `0fr` to `1fr`
 * rows (and fades) over 300ms, with the content clipped in one track. The
 * content stays mounted while closed but is `inert`, so its fields leave the
 * tab order and the accessibility tree. The trigger is the caller's: a
 * `<button aria-expanded aria-controls={id}>`, so pass `id` here.
 */
function Collapsible({
  open,
  className,
  children,
  ...props
}: CollapsibleProps) {
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
      {...props}
    >
      <div className="min-h-0 overflow-hidden">{children}</div>
    </div>
  );
}

export { Collapsible };
export type { CollapsibleProps };
