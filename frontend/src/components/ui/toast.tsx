import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { AlertCircle, Check, Info, TriangleAlert } from 'lucide-react';

import { Spinner } from '@/components/ui/spinner';
import { cn } from '@/lib/utils';

/**
 * Bottom-right message card: the app's messaging surface for uploads, tool
 * approvals and team notifications. Compose:
 * ToastViewport > Toast > ToastHeader(variant) [ToastTitle, ToastActions]
 *                       > ToastContent > ToastItem(s) / ToastMessage
 */

/**
 * Fixed stack in the bottom-right corner. One per app, mounted in App.tsx;
 * every toast renders only its `Toast` cards into it. It is the single live
 * region (`role="status"`, `aria-live="polite"`), so cards carry no role.
 */
function ToastViewport({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      role="status"
      aria-live="polite"
      data-slot="toast-viewport"
      className={cn(
        'fixed right-4 bottom-6 z-50 flex max-w-md flex-col gap-2',
        className,
      )}
      {...props}
    />
  );
}

function Toast({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="toast"
      className={cn(
        'border-border bg-card text-card-foreground shadow-toast w-68 overflow-hidden rounded-2xl border',
        className,
      )}
      {...props}
    />
  );
}

const toastHeaderVariants = cva(
  'flex items-center justify-between gap-2 px-4 py-3',
  {
    variants: {
      variant: {
        default: 'bg-accent/50 dark:bg-muted',
        success: 'bg-success/10',
        warning: 'bg-warning/10',
        destructive: 'bg-destructive/10',
        info: 'bg-info/10',
      },
    },
    defaultVariants: { variant: 'default' },
  },
);

function ToastHeader({
  className,
  variant = 'default',
  ...props
}: React.ComponentProps<'div'> & VariantProps<typeof toastHeaderVariants>) {
  return (
    <div
      data-slot="toast-header"
      data-variant={variant}
      className={cn(toastHeaderVariants({ variant }), className)}
      {...props}
    />
  );
}

/** One line with an ellipsis by default; `wrap` lets a long title wrap. */
function ToastTitle({
  className,
  wrap = false,
  ...props
}: React.ComponentProps<'h3'> & { wrap?: boolean }) {
  return (
    <h3
      data-slot="toast-title"
      className={cn(
        'text-foreground text-sm font-medium',
        wrap ? 'min-w-0 break-words' : 'truncate',
        className,
      )}
      {...props}
    />
  );
}

/** Collapse and close buttons; use `Button variant="ghost-muted" size="icon-sm"`. */
function ToastActions({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="toast-actions"
      className={cn('flex shrink-0 items-center gap-1', className)}
      {...props}
    />
  );
}

/**
 * Rows and messages. Pass `scrollable` only for long lists (uploads); a
 * plain block sizes reliably in every engine, a max-height scroll box does
 * not always inside a flex item in WebKit.
 */
function ToastContent({
  className,
  scrollable = false,
  ...props
}: React.ComponentProps<'div'> & { scrollable?: boolean }) {
  return (
    <div
      data-slot="toast-content"
      className={cn(scrollable && 'max-h-72 overflow-y-auto', className)}
      {...props}
    />
  );
}

/** Action buttons under the rows, right-aligned. */
function ToastFooter({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="toast-footer"
      className={cn('flex justify-end gap-2 px-5 pt-1 pb-3', className)}
      {...props}
    />
  );
}

/**
 * One row: optional icon, label and optional meta on the left, status or
 * actions on the right. A `ToastMessage` right after it belongs to the row,
 * so the divider moves below the message.
 */
function ToastItem({
  className,
  label,
  meta,
  icon,
  children,
  ...props
}: React.ComponentProps<'div'> & {
  label: React.ReactNode;
  meta?: React.ReactNode;
  icon?: React.ReactNode;
}) {
  return (
    <div
      data-slot="toast-item"
      className={cn(
        'border-border/50 flex items-center justify-between gap-3 border-b px-5 py-3 last:border-b-0 [&:has(+[data-slot=toast-message])]:border-b-0',
        className,
      )}
      {...props}
    >
      <div className="flex min-w-0 items-center gap-2">
        {icon}
        <div className="flex min-w-0 flex-col">
          <span className="text-foreground truncate text-sm">{label}</span>
          {meta ? (
            <span className="text-muted-foreground mt-0.5 text-xs">{meta}</span>
          ) : null}
        </div>
      </div>
      {children ? (
        <div className="flex shrink-0 items-center gap-2">{children}</div>
      ) : null}
    </div>
  );
}

const toastStatusVariants = cva(
  'flex size-6 shrink-0 items-center justify-center rounded-full [&>svg]:size-3.5',
  {
    variants: {
      status: {
        pending: 'text-primary',
        success: 'bg-success text-success-foreground',
        warning: 'bg-warning text-warning-foreground',
        destructive: 'bg-destructive text-destructive-foreground',
        info: 'bg-info text-info-foreground',
      },
    },
    defaultVariants: { status: 'pending' },
  },
);

const STATUS_ICON = {
  pending: <Spinner size="sm" />,
  success: <Check strokeWidth={3} />,
  warning: <TriangleAlert strokeWidth={3} />,
  destructive: <AlertCircle strokeWidth={3} />,
  info: <Info strokeWidth={3} />,
} as const;

/** Filled status circle for a ToastItem. */
function ToastStatus({
  className,
  status = 'pending',
  label,
  ...props
}: React.ComponentProps<'span'> &
  VariantProps<typeof toastStatusVariants> & { label?: string }) {
  return (
    <span
      data-slot="toast-status"
      data-status={status}
      role="img"
      aria-label={label ?? status ?? undefined}
      className={cn(toastStatusVariants({ status }), className)}
      {...props}
    >
      {STATUS_ICON[status ?? 'pending']}
    </span>
  );
}

// `first:pt-3` pads a message that is the only content under the header;
// under a ToastItem the row's own padding already spaces it.
const toastMessageVariants = cva(
  'border-border/50 block border-b px-5 pb-3 last:border-b-0 first:pt-3',
  {
    variants: {
      variant: {
        default: 'text-muted-foreground',
        success: 'text-success',
        warning: 'text-warning',
        destructive: 'text-destructive',
        info: 'text-info',
      },
      size: {
        xs: 'text-xs',
        sm: 'text-sm leading-4.5',
      },
    },
    defaultVariants: { variant: 'default', size: 'xs' },
  },
);

/**
 * Explanation under a row (why a file failed), or the whole body of a
 * notice when it is the only content (`size="sm"`).
 */
function ToastMessage({
  className,
  variant = 'default',
  size = 'xs',
  ...props
}: React.ComponentProps<'span'> & VariantProps<typeof toastMessageVariants>) {
  return (
    <span
      data-slot="toast-message"
      data-variant={variant}
      data-size={size}
      className={cn(toastMessageVariants({ variant, size }), className)}
      {...props}
    />
  );
}

export {
  ToastViewport,
  Toast,
  ToastHeader,
  ToastTitle,
  ToastActions,
  ToastContent,
  ToastFooter,
  ToastItem,
  ToastStatus,
  ToastMessage,
  toastHeaderVariants,
};
