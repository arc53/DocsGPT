import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { Check, CircleAlert, Info, TriangleAlert } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { Spinner } from '@/components/ui/spinner';
import {
  ToastAvoidContext,
  toastStackLayout,
  type ToastStackLayout,
} from '@/components/ui/toast-layout';
import { cn } from '@/lib/utils';

/**
 * Bottom-right message card: the app's messaging surface for uploads, tool
 * approvals and team notifications. Compose:
 * ToastViewport > Toast > ToastHeader(variant) [ToastTitle, ToastActions]
 *                       > ToastContent > ToastItem(s) / ToastMessage
 */

/** Below `sm`: the stack spans the screen and folds to its newest card. */
const SMALL_SCREEN_QUERY = '(max-width: 639.98px)';

function useSmallScreen(): boolean {
  const [small, setSmall] = React.useState(false);
  React.useEffect(() => {
    if (typeof window.matchMedia !== 'function') return;
    const media = window.matchMedia(SMALL_SCREEN_QUERY);
    setSmall(media.matches);
    const onChange = (event: MediaQueryListEvent) => setSmall(event.matches);
    media.addEventListener('change', onChange);
    return () => media.removeEventListener('change', onChange);
  }, []);
  return small;
}

const cornerLayout = (): ToastStackLayout =>
  toastStackLayout(
    { left: 0, right: 0 },
    [],
    typeof window === 'undefined' ? 0 : window.innerHeight,
  );

/**
 * Fixed stack in the bottom-right corner. One per app, mounted in App.tsx;
 * every toast renders only its `Toast` cards into it. It is the single live
 * region (`role="status"`, `aria-live="polite"`), so cards carry no role.
 *
 * It keeps clear of the composer: when a composer registered with
 * `useAvoidToasts` reaches under the stack's column, the stack sits just
 * above it. It never grows past the header (it scrolls once its cards would),
 * and below `sm` it spans the screen and shows only its newest card, the rest
 * behind an "N more" button.
 */
function ToastViewport({
  className,
  children,
  style,
  ...props
}: React.ComponentProps<'div'>) {
  const { t } = useTranslation();
  const registry = React.useContext(ToastAvoidContext);
  const ref = React.useRef<HTMLDivElement>(null);
  const [layout, setLayout] = React.useState(cornerLayout);
  const [overflowing, setOverflowing] = React.useState(false);
  const [cardCount, setCardCount] = React.useState(0);
  const [expanded, setExpanded] = React.useState(false);
  const small = useSmallScreen();
  const collapsed = small && !expanded;
  const collapsedRef = React.useRef(collapsed);
  collapsedRef.current = collapsed;
  // Arrival order of the cards on screen, to tell which one is newest.
  const arrival = React.useRef(new WeakMap<Element, number>());
  const arrived = React.useRef(0);

  const measure = React.useCallback(() => {
    const viewport = ref.current;
    if (!viewport) return;
    const next = toastStackLayout(
      viewport.getBoundingClientRect(),
      (registry?.elements() ?? []).map((element) =>
        element.getBoundingClientRect(),
      ),
      window.innerHeight,
    );
    setLayout((prev) =>
      prev.bottom === next.bottom && prev.maxHeight === next.maxHeight
        ? prev
        : next,
    );
    setOverflowing(viewport.scrollHeight > viewport.clientHeight + 1);
  }, [registry]);

  const syncCards = React.useCallback(() => {
    const viewport = ref.current;
    if (!viewport) return;
    const cards = Array.from(viewport.children).filter(
      (child): child is HTMLElement =>
        child instanceof HTMLElement && child.dataset.slot === 'toast',
    );
    let newest: HTMLElement | null = null;
    let newestAt = -1;
    for (const card of cards) {
      if (!arrival.current.has(card)) {
        arrived.current += 1;
        arrival.current.set(card, arrived.current);
      }
      const at = arrival.current.get(card) ?? 0;
      if (at > newestAt) {
        newestAt = at;
        newest = card;
      }
    }
    for (const card of cards) {
      card.hidden = collapsedRef.current && card !== newest;
    }
    setCardCount(cards.length);
  }, []);

  React.useLayoutEffect(() => {
    const viewport = ref.current;
    if (!viewport) return;
    const update = () => {
      syncCards();
      measure();
    };
    const resize =
      typeof ResizeObserver === 'undefined'
        ? null
        : new ResizeObserver(() => measure());
    const observe = () => {
      if (resize) {
        resize.disconnect();
        resize.observe(viewport);
        registry?.elements().forEach((element) => resize.observe(element));
      }
      measure();
    };
    // Cards come and go, and grow (an upload adds rows), without a resize
    // of anything the ResizeObserver watches once the stack is capped.
    const mutations = new MutationObserver(update);
    mutations.observe(viewport, {
      childList: true,
      subtree: true,
      characterData: true,
    });
    const unsubscribe = registry?.subscribe(observe);
    window.addEventListener('resize', measure);
    syncCards();
    observe();
    return () => {
      mutations.disconnect();
      resize?.disconnect();
      unsubscribe?.();
      window.removeEventListener('resize', measure);
    };
  }, [registry, measure, syncCards]);

  // Moving sides (an agent preview opened) or folding changes the geometry.
  React.useLayoutEffect(() => {
    syncCards();
    measure();
  }, [className, collapsed, syncCards, measure]);

  React.useEffect(() => {
    if (cardCount <= 1) setExpanded(false);
  }, [cardCount]);

  const folded = small && cardCount > 1;

  return (
    <div
      role="status"
      aria-live="polite"
      data-slot="toast-viewport"
      ref={ref}
      className={cn(
        'pointer-events-none fixed right-2 bottom-(--toast-bottom) z-50 flex max-h-(--toast-max-h) w-72 flex-col gap-2 p-2 *:pointer-events-auto max-sm:inset-x-1 max-sm:w-auto max-sm:*:w-full',
        overflowing && 'overflow-y-auto overscroll-contain',
        className,
      )}
      style={
        {
          ...style,
          '--toast-bottom': `${layout.bottom}px`,
          '--toast-max-h': `${layout.maxHeight}px`,
        } as React.CSSProperties
      }
      {...props}
    >
      {children}
      {folded && (
        <div data-slot="toast-more" className="flex justify-end">
          <Button
            type="button"
            variant="secondary"
            size="xs"
            shape="pill"
            onClick={() => setExpanded((open) => !open)}
          >
            {expanded
              ? t('notifications.fewerToasts')
              : t('notifications.moreToasts', { count: cardCount - 1 })}
          </Button>
        </div>
      )}
    </div>
  );
}

function Toast({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="toast"
      className={cn(
        'border-border bg-card text-card-foreground shadow-toast w-68 shrink-0 overflow-hidden rounded-2xl border',
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
        default: 'bg-muted',
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
  destructive: <CircleAlert strokeWidth={3} />,
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
        destructive: 'text-destructive',
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
