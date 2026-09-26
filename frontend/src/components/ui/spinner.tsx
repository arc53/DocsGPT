import * as React from 'react';

import { cn } from '@/lib/utils';

type SpinnerProps = React.ComponentProps<'div'> & {
  size?: 'xs' | 'sm' | 'default' | 'lg';
  /** Announced to screen readers. */
  label?: string;
};

const SIZE_CLASSES: Record<NonNullable<SpinnerProps['size']>, string> = {
  // Icon-sized spots: a busy Button, a step's status in a 12-16px row.
  xs: 'size-4',
  sm: 'size-5',
  default: 'size-7',
  lg: 'size-10',
};

/**
 * Ring spinner drawn in `currentColor`, so it takes the text colour of its
 * parent (or a `text-*` class). The ring itself is the `spinner-ring`
 * utility in src/index.css.
 */
function Spinner({
  className,
  size = 'default',
  label = 'Loading',
  ...props
}: SpinnerProps) {
  return (
    <div
      role="status"
      aria-label={label}
      data-slot="spinner"
      data-size={size}
      className={cn('spinner-ring shrink-0', SIZE_CLASSES[size], className)}
      {...props}
    />
  );
}

export { Spinner };
export type { SpinnerProps };
