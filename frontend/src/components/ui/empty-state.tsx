import * as React from 'react';
import { CircleAlert } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import NoFilesDark from '@/assets/no-files-dark.svg?react';
import NoFiles from '@/assets/no-files.svg?react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

type EmptyStateSize = 'default' | 'sm' | 'xs';

// Art, title size and padding per size: 128px on a page, 96px inside a
// panel, 64px in a popover or picker.
const SIZE_CLASSES: Record<
  EmptyStateSize,
  { root: string; art: string; title: string }
> = {
  default: { root: 'py-12', art: 'mb-6 size-32', title: 'text-lg' },
  sm: { root: 'py-8', art: 'mb-4 size-24', title: 'text-base' },
  xs: { root: 'py-8', art: 'mb-3 size-16', title: 'text-sm' },
};

type EmptyStateProps = Omit<React.ComponentProps<'div'>, 'title'> & {
  title: React.ReactNode;
  description?: React.ReactNode;
  /** A button under the text: create the first item. */
  action?: React.ReactNode;
  /**
   * Retry a failed load: draws the standard outline sm pill "Retry" in the
   * action slot (after `action`, when both are set).
   */
  onRetry?: () => void;
  size?: EmptyStateSize;
  /** The "no files" drawing, or text only. */
  illustration?: 'no-files' | 'none';
  /**
   * `neutral` for "nothing here yet"; `destructive` for a failed page or
   * panel load: a red icon replaces the art, the title turns red and the
   * block is announced as an alert.
   */
  tone?: 'neutral' | 'destructive';
};

/** The one "nothing to show" block: empty lists, no search results, load errors. */
function EmptyState({
  title,
  description,
  action,
  onRetry,
  size = 'default',
  illustration = 'no-files',
  tone = 'neutral',
  className,
  ...props
}: EmptyStateProps) {
  const { t } = useTranslation();
  const sizes = SIZE_CLASSES[size];
  const retry = onRetry ? (
    <Button
      type="button"
      variant="outline"
      size="sm"
      shape="pill"
      onClick={onRetry}
    >
      {t('retry')}
    </Button>
  ) : null;
  const destructive = tone === 'destructive';

  return (
    <div
      data-slot="empty-state"
      data-size={size}
      data-tone={tone}
      role={destructive ? 'alert' : undefined}
      className={cn(
        'flex flex-col items-center justify-center text-center',
        sizes.root,
        className,
      )}
      {...props}
    >
      {destructive ? (
        <CircleAlert aria-hidden className="text-destructive mb-3 size-8" />
      ) : illustration === 'no-files' ? (
        <>
          <NoFiles
            aria-hidden
            className={cn('mx-auto dark:hidden', sizes.art)}
          />
          <NoFilesDark
            aria-hidden
            className={cn('mx-auto hidden dark:block', sizes.art)}
          />
        </>
      ) : null}
      <p
        className={cn(
          destructive ? 'text-destructive' : 'text-muted-foreground',
          sizes.title,
        )}
      >
        {title}
      </p>
      {description ? (
        <p className="text-muted-foreground mt-1 max-w-sm text-sm">
          {description}
        </p>
      ) : null}
      {action && retry ? (
        <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
          {action}
          {retry}
        </div>
      ) : action || retry ? (
        <div className="mt-4">{action || retry}</div>
      ) : null}
    </div>
  );
}

export { EmptyState };
export type { EmptyStateProps };
