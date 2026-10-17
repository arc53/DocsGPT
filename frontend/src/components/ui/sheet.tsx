import * as React from 'react';
import { Dialog as SheetPrimitive } from 'radix-ui';
import { cva } from 'class-variance-authority';

import { BottomTintReset } from '@/components/ui/bar-tint-reset';
import { cn, overlayScrim } from '@/lib/utils';
import { useFocusReturn } from '@/components/ui/use-focus-return';

function Sheet({ ...props }: React.ComponentProps<typeof SheetPrimitive.Root>) {
  return <SheetPrimitive.Root data-slot="sheet" {...props} />;
}

function SheetTrigger({
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Trigger>) {
  return <SheetPrimitive.Trigger data-slot="sheet-trigger" {...props} />;
}

function SheetPortal({
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Portal>) {
  return <SheetPrimitive.Portal data-slot="sheet-portal" {...props} />;
}

function SheetOverlay({
  className,
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Overlay>) {
  return (
    <SheetPrimitive.Overlay
      data-slot="sheet-overlay"
      className={cn(
        `data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 fixed inset-0 z-50 ${overlayScrim}`,
        className,
      )}
      {...props}
    />
  );
}

/**
 * The phone bottom-sheet shape: card fill, 18px top corners, capped by
 * `max-h-sheet` so the scrim above it stays tappable. Shared with Modal's `mobileVariant="sheet"` so every bottom
 * sheet looks the same; the caller adds its own bottom padding (`pb-safe` or
 * `pb-safe-0`).
 */
const sheetBottomShape =
  'data-[state=closed]:slide-out-to-bottom data-[state=open]:slide-in-from-bottom inset-x-0 bottom-0 h-auto max-h-sheet rounded-t-2xl bg-card';

/** The grab bar at the top of a bottom sheet, 8px below its edge. */
function SheetHandle({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="sheet-handle"
      aria-hidden="true"
      className={cn(
        'bg-border mx-auto mt-2 h-1.5 w-12 shrink-0 rounded-full',
        className,
      )}
      {...props}
    />
  );
}

const sheetContentVariants = cva(
  'bg-background data-[state=open]:animate-in data-[state=closed]:animate-out fixed z-50 flex flex-col gap-4 shadow-lg outline-none transition ease-in-out data-[state=closed]:duration-300 data-[state=open]:duration-500',
  {
    variants: {
      side: {
        right:
          'data-[state=closed]:slide-out-to-right data-[state=open]:slide-in-from-right inset-y-0 right-0 h-full border-l',
        // A bottom sheet stacks its handle and parts flush; its content
        // brings its own padding.
        bottom: `${sheetBottomShape} pb-safe-0 gap-0`,
      },
      // A right drawer's width by role (DESIGN.md "Side panels"): default
      // (480px) for every panel; wide (600 / 700 / 800px) only for a working
      // surface: a trace, an agent preview, the source editor. Both are full
      // width on a phone.
      size: {
        default: '',
        wide: '',
      },
    },
    compoundVariants: [
      { side: 'right', size: 'default', class: 'w-full sm:max-w-120' },
      {
        side: 'right',
        size: 'wide',
        class: 'w-full sm:max-w-[600px] md:max-w-[700px] lg:max-w-[800px]',
      },
    ],
    defaultVariants: { side: 'right', size: 'default' },
  },
);

function SheetContent({
  className,
  children,
  side = 'right',
  size = 'default',
  handle = false,
  title,
  onOpenAutoFocus,
  onCloseAutoFocus,
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Content> & {
  /**
   * `right`: SidePanel's drawer. `bottom`: a phone sheet. It draws no X: a
   * SidePanel's PanelHeader brings the close, and a bottom sheet closes by
   * its scrim (the handle is only a cue; it doesn't drag).
   */
  side?: 'right' | 'bottom';
  /** Width of a right drawer: default (480px) or wide (800px). */
  size?: 'default' | 'wide';
  /** Draw the grab bar first (bottom sheets). */
  handle?: boolean;
  // Accessible name for the dialog. Radix warns when a Dialog has no Title;
  // pass this to render a visually-hidden one when the panel has no visible
  // heading of its own (omit it if the children already render a SheetTitle).
  title?: string;
}) {
  const focusReturn = useFocusReturn(onOpenAutoFocus, onCloseAutoFocus);
  return (
    <SheetPortal>
      <SheetOverlay />
      <SheetPrimitive.Content
        data-slot="sheet-content"
        data-side={side}
        className={cn(sheetContentVariants({ side, size }), className)}
        {...props}
        {...focusReturn}
      >
        {title ? <SheetTitle className="sr-only">{title}</SheetTitle> : null}
        {side === 'bottom' && <BottomTintReset />}
        {handle && <SheetHandle />}
        {children}
      </SheetPrimitive.Content>
    </SheetPortal>
  );
}

function SheetTitle({
  className,
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Title>) {
  return (
    <SheetPrimitive.Title
      data-slot="sheet-title"
      className={cn(
        'text-foreground text-xl leading-tight font-semibold',
        className,
      )}
      {...props}
    />
  );
}

export {
  sheetBottomShape,
  Sheet,
  SheetTrigger,
  SheetContent,
  SheetHandle,
  SheetTitle,
};
