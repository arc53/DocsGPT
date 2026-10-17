import * as React from 'react';
import { useTranslation } from 'react-i18next';

import { cn } from '@/lib/utils';

import { Spinner, type SpinnerProps } from './spinner';

// `parent` needs a parent with a height (a panel, a drawer body); a page
// section with none takes `block`.
const FILL_CLASSES = {
  parent: 'h-full',
  screen: 'h-dvh',
  block: 'py-10',
} as const;

type LoadingStateProps = React.ComponentProps<'div'> & {
  fill?: keyof typeof FILL_CLASSES;
  size?: SpinnerProps['size'];
  /** A caption under the ring; also the ring's accessible name. */
  label?: string;
};

/** The centred spinner for a page, panel or dialog that is still loading. */
function LoadingState({
  fill = 'parent',
  size = 'default',
  label,
  className,
  ...props
}: LoadingStateProps) {
  const { t } = useTranslation();

  return (
    <div
      data-slot="loading-state"
      data-fill={fill}
      className={cn(
        'flex w-full items-center justify-center',
        FILL_CLASSES[fill],
        label && 'flex-col gap-3',
        className,
      )}
      {...props}
    >
      <Spinner size={size} label={label ?? t('loading')} />
      {label ? (
        // The ring already announces the label; don't read it twice.
        <p aria-hidden="true" className="text-muted-foreground text-sm">
          {label}
        </p>
      ) : null}
    </div>
  );
}

export { LoadingState };
export type { LoadingStateProps };
