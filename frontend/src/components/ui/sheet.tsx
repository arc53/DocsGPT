import * as React from 'react';
import { Dialog as SheetPrimitive } from 'radix-ui';
import { XIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

function Sheet({ ...props }: React.ComponentProps<typeof SheetPrimitive.Root>) {
  return <SheetPrimitive.Root data-slot="sheet" {...props} />;
}

function SheetTrigger({
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Trigger>) {
  return <SheetPrimitive.Trigger data-slot="sheet-trigger" {...props} />;
}

function SheetClose({
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Close>) {
  return <SheetPrimitive.Close data-slot="sheet-close" {...props} />;
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
        'data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 fixed inset-0 z-50 bg-black/50',
        className,
      )}
      {...props}
    />
  );
}

/**
 * The phone bottom-sheet shape: card fill, 16px top corners, capped at 90% of
 * the viewport. Shared with Modal's `mobileVariant="sheet"` so every bottom
 * sheet looks the same; the caller adds its own bottom padding (`pb-safe` or
 * `pb-safe-0`).
 */
const sheetBottomShape =
  'data-[state=closed]:slide-out-to-bottom data-[state=open]:slide-in-from-bottom inset-x-0 bottom-0 h-auto max-h-[90vh] rounded-t-2xl bg-card';

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

function SheetContent({
  className,
  children,
  side = 'right',
  showCloseButton = true,
  handle = false,
  title,
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Content> & {
  side?: 'top' | 'right' | 'bottom' | 'left';
  showCloseButton?: boolean;
  /** Draw the grab bar first (bottom sheets). */
  handle?: boolean;
  // Accessible name for the dialog. Radix warns when a Dialog has no Title;
  // pass this to render a visually-hidden one when the panel has no visible
  // heading of its own (omit it if the children already render a SheetTitle).
  title?: string;
}) {
  return (
    <SheetPortal>
      <SheetOverlay />
      <SheetPrimitive.Content
        data-slot="sheet-content"
        data-side={side}
        className={cn(
          'bg-background data-[state=open]:animate-in data-[state=closed]:animate-out fixed z-50 flex flex-col gap-4 shadow-lg transition ease-in-out data-[state=closed]:duration-300 data-[state=open]:duration-500',
          side === 'right' &&
            'data-[state=closed]:slide-out-to-right data-[state=open]:slide-in-from-right inset-y-0 right-0 h-full w-3/4 border-l sm:max-w-sm',
          side === 'left' &&
            'data-[state=closed]:slide-out-to-left data-[state=open]:slide-in-from-left inset-y-0 left-0 h-full w-3/4 border-r sm:max-w-sm',
          side === 'top' &&
            'data-[state=closed]:slide-out-to-top data-[state=open]:slide-in-from-top inset-x-0 top-0 h-auto border-b',
          // A bottom sheet stacks its handle and parts flush; SheetHeader and
          // SheetFooter bring their own padding.
          side === 'bottom' && `${sheetBottomShape} pb-safe-0 gap-0`,
          className,
        )}
        {...props}
      >
        {title ? <SheetTitle className="sr-only">{title}</SheetTitle> : null}
        {handle && <SheetHandle />}
        {children}
        {showCloseButton && (
          <SheetPrimitive.Close asChild>
            <Button
              variant="ghost-muted"
              size="icon-sm"
              aria-label="Close"
              className="absolute top-2 right-2"
            >
              <XIcon />
            </Button>
          </SheetPrimitive.Close>
        )}
      </SheetPrimitive.Content>
    </SheetPortal>
  );
}

function SheetHeader({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="sheet-header"
      className={cn('flex flex-col gap-1.5 p-4', className)}
      {...props}
    />
  );
}

function SheetFooter({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="sheet-footer"
      className={cn('mt-auto flex flex-col gap-2 p-4', className)}
      {...props}
    />
  );
}

function SheetTitle({
  className,
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Title>) {
  return (
    <SheetPrimitive.Title
      data-slot="sheet-title"
      className={cn('text-foreground font-semibold', className)}
      {...props}
    />
  );
}

function SheetDescription({
  className,
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Description>) {
  return (
    <SheetPrimitive.Description
      data-slot="sheet-description"
      className={cn('text-muted-foreground text-sm', className)}
      {...props}
    />
  );
}

export {
  sheetBottomShape,
  Sheet,
  SheetTrigger,
  SheetClose,
  SheetContent,
  SheetHandle,
  SheetHeader,
  SheetFooter,
  SheetTitle,
  SheetDescription,
};
