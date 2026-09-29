import * as React from 'react';
import { ArrowLeft, Maximize2, Minimize2, XIcon } from 'lucide-react';
import { Dialog as SheetPrimitive } from 'radix-ui';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { IconButton } from '@/components/ui/icon-button';
import { Separator } from '@/components/ui/separator';
import { Sheet, SheetContent } from '@/components/ui/sheet';
import { useMediaQuery } from '@/hooks';
import { cn } from '@/lib/utils';

type SidePanelSize = 'default' | 'wide';
/** A docked panel's width: its `size`, half of the host, or all of it. */
type SidePanelWidth = 'compact' | 'half' | 'full';

const NEXT_WIDTH: Record<SidePanelWidth, SidePanelWidth> = {
  compact: 'half',
  half: 'full',
  full: 'compact',
};

// The compact width of a docked panel, the same 480 / 800px roles as a modal
// SheetContent `size`.
const DOCKED_SIZE: Record<SidePanelSize, string> = {
  default: 'w-120',
  wide: 'w-[800px]',
};

// Half of the host, never narrower than the compact size on a small screen.
const DOCKED_HALF: Record<SidePanelSize, string> = {
  default: 'w-1/2 min-w-120',
  wide: 'w-1/2 min-w-[800px]',
};

// Slides in like the modal Sheet; it closes at once (an exit slide would
// snap back for a frame before the panel unmounts).
const DOCKED_ENTER =
  'animate-in slide-in-from-right motion-reduce:animate-none';

// The host is `relative`; the panel covers it and the page keeps its scroll
// position underneath.
const DOCKED_FULL = 'absolute inset-0 z-20 w-auto border-l-0';

const storageKey = (surface: string) => `docsgpt-side-panel:${surface}`;

function readWidth(surface?: string): SidePanelWidth {
  if (!surface) return 'compact';
  try {
    const value = localStorage.getItem(storageKey(surface));
    return value === 'half' || value === 'full' ? value : 'compact';
  } catch {
    return 'compact';
  }
}

function writeWidth(surface: string, width: SidePanelWidth) {
  try {
    localStorage.setItem(storageKey(surface), width);
  } catch {
    // A blocked store only loses the remembered width.
  }
}

type SidePanelContextValue = {
  /** Inside a Radix Dialog (modal, or docked on a phone). */
  inDialog: boolean;
  close: () => void;
  titleId: string;
  expand: { width: SidePanelWidth; next: () => void } | null;
};

const SidePanelContext = React.createContext<SidePanelContextValue | null>(
  null,
);

function useSidePanel() {
  const context = React.useContext(SidePanelContext);
  if (!context) {
    throw new Error('PanelHeader must be used inside a SidePanel');
  }
  return context;
}

type SidePanelProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /**
   * `modal`: over the blurred scrim, for a form, one record, editing or a
   * preview. `docked`: beside the page, which stays live, for what you read
   * or tweak alongside it (an artifact, sources, a node's settings).
   */
  variant?: 'modal' | 'docked';
  /**
   * The width by role: default (480px) for every panel, wide (800px) only for
   * a working surface (a trace, an agent preview, the source editor).
   */
  size?: SidePanelSize;
  /**
   * Docked only: a key naming the surface ("artifact"). Adds the header's
   * Expand button, which steps size, half and full, and remembers the last
   * width per surface.
   */
  expandable?: string;
  /** Layout only. */
  className?: string;
  children: React.ReactNode;
} & Pick<
  React.ComponentProps<typeof SheetContent>,
  'onOpenAutoFocus' | 'aria-describedby'
>;

/**
 * The one right-side panel (DESIGN.md "Side panels"). Compose a PanelHeader,
 * one PanelBody and an optional PanelFooter inside it. A docked panel is a
 * flex item: its host is a `relative flex` row with the page as a `min-w-0
 * flex-1` sibling. On a phone both variants are a full-width right sheet.
 */
function SidePanel({
  open,
  onOpenChange,
  variant = 'modal',
  size = 'default',
  expandable,
  className,
  children,
  onOpenAutoFocus,
  ...contentProps
}: SidePanelProps) {
  const { isMobile } = useMediaQuery();
  const titleId = React.useId();
  // One slot can swap surfaces (sources, then an artifact): each brings back
  // its own remembered width.
  const [state, setState] = React.useState(() => ({
    surface: expandable,
    width: readWidth(expandable),
  }));
  if (state.surface !== expandable) {
    setState({ surface: expandable, width: readWidth(expandable) });
  }
  const width = state.width;
  const close = React.useCallback(() => onOpenChange(false), [onOpenChange]);
  const next = React.useCallback(() => {
    setState((current) => {
      const nextWidth = NEXT_WIDTH[current.width];
      if (current.surface) writeWidth(current.surface, nextWidth);
      return { ...current, width: nextWidth };
    });
  }, []);

  const dialog = variant === 'modal' || isMobile;
  const context = React.useMemo<SidePanelContextValue>(
    () => ({
      inDialog: dialog,
      close,
      titleId,
      expand: !dialog && expandable ? { width, next } : null,
    }),
    [dialog, close, titleId, expandable, width, next],
  );

  if (dialog) {
    return (
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent
          side="right"
          size={size}
          showCloseButton={false}
          className={cn('gap-0 p-0', variant === 'modal' && className)}
          // A docked panel's phone sheet opens on the panel, not with a ring
          // on its first control (DESIGN.md "Focus").
          onOpenAutoFocus={
            onOpenAutoFocus ??
            (variant === 'docked'
              ? (event: Event) => event.preventDefault()
              : undefined)
          }
          {...contentProps}
        >
          <SidePanelContext.Provider value={context}>
            {children}
          </SidePanelContext.Provider>
        </SheetContent>
      </Sheet>
    );
  }

  if (!open) return null;
  const current = expandable ? width : 'compact';
  return (
    <SidePanelContext.Provider value={context}>
      <aside
        data-slot="side-panel"
        data-width={current}
        aria-labelledby={titleId}
        className={cn(
          // z-20: above the app's floating top actions (Share, account, z-10),
          // which the open panel covers.
          'bg-background border-border relative z-20 flex max-w-full shrink-0 flex-col border-l transition-[width] duration-300 ease-in-out',
          DOCKED_ENTER,
          current === 'full'
            ? DOCKED_FULL
            : current === 'half'
              ? DOCKED_HALF[size]
              : DOCKED_SIZE[size],
          className,
        )}
      >
        {children}
      </aside>
    </SidePanelContext.Provider>
  );
}

const titleClass =
  'text-foreground text-xl leading-tight font-semibold wrap-break-word';
const descriptionClass = 'text-muted-foreground text-sm';

type PanelHeaderProps = {
  title: React.ReactNode;
  /**
   * One muted line under the title (a type, a path, a count). Wrap it in a
   * span for its own typography (`font-mono text-xs` for a path).
   */
  description?: React.ReactNode;
  /** Before the title: a node tile or a connector icon. */
  leading?: React.ReactNode;
  /** Before Expand and the X: a badge, a ⋯ menu, a download. */
  actions?: React.ReactNode;
  /** Adds a Back arrow first, for a second level inside the panel. */
  onBack?: () => void;
  backLabel?: string;
  /** Under the title row, still fixed (a team's tabs). */
  children?: React.ReactNode;
};

/**
 * The fixed top of every side panel: title and description, then actions,
 * Expand and the X in the same row, and a Separator under it. It never
 * scrolls.
 */
function PanelHeader({
  title,
  description,
  leading,
  actions,
  onBack,
  backLabel,
  children,
}: PanelHeaderProps) {
  const { t } = useTranslation();
  const { inDialog, close, titleId, expand } = useSidePanel();
  const full = expand?.width === 'full';

  return (
    <>
      <div
        data-slot="panel-header"
        className="flex shrink-0 flex-col gap-4 px-6 pt-6 pb-4"
      >
        <div className="flex items-start gap-3">
          {onBack ? (
            <IconButton
              variant="ghost-muted"
              size="icon-sm"
              side="bottom"
              className="-mt-1 -ml-2"
              label={backLabel ?? t('sidePanel.back')}
              icon={ArrowLeft}
              onClick={onBack}
            />
          ) : null}
          {leading}
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            {inDialog ? (
              <SheetPrimitive.Title
                data-slot="sheet-title"
                className={titleClass}
              >
                {title}
              </SheetPrimitive.Title>
            ) : (
              <h2 id={titleId} className={titleClass}>
                {title}
              </h2>
            )}
            {description ? (
              inDialog ? (
                <SheetPrimitive.Description
                  data-slot="sheet-description"
                  className={descriptionClass}
                >
                  {description}
                </SheetPrimitive.Description>
              ) : (
                <p className={descriptionClass}>{description}</p>
              )
            ) : null}
          </div>
          <div className="-mt-1 -mr-2 flex shrink-0 items-center gap-1">
            {actions}
            {expand ? (
              <IconButton
                variant="ghost-muted"
                size="icon-sm"
                side="bottom"
                label={full ? t('sidePanel.collapse') : t('sidePanel.expand')}
                icon={full ? Minimize2 : Maximize2}
                onClick={expand.next}
              />
            ) : null}
            <Button
              variant="ghost-muted"
              size="icon-sm"
              aria-label={t('sidePanel.close')}
              onClick={close}
            >
              <XIcon />
            </Button>
          </div>
        </div>
        {children}
      </div>
      <Separator />
    </>
  );
}

/**
 * The one scroller of a side panel: its sections stacked 24px apart
 * (`gap-6`, DESIGN.md "Rhythm") at `px-6 py-6`. `scroll={false}` for content
 * that owns its scroller (an artifact's iframe or code view).
 */
function PanelBody({
  scroll = true,
  className,
  ...props
}: React.ComponentProps<'div'> & { scroll?: boolean }) {
  return (
    <div
      data-slot="panel-body"
      className={cn(
        'flex min-h-0 flex-1 flex-col gap-6 px-6 py-6',
        scroll ? 'scrollbar-overlay overflow-y-auto' : 'overflow-hidden',
        className,
      )}
      {...props}
    />
  );
}

/** The action row under the body: a Separator, then buttons at the right. */
function PanelFooter({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <>
      <Separator />
      <div
        data-slot="panel-footer"
        className={cn('flex shrink-0 justify-end gap-3 px-6 py-4', className)}
        {...props}
      />
    </>
  );
}

export { SidePanel, PanelHeader, PanelBody, PanelFooter };
export type { SidePanelProps, SidePanelSize, SidePanelWidth };
