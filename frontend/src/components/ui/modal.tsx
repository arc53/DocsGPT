import { XIcon } from 'lucide-react';
import { Dialog as DialogPrimitive, VisuallyHidden } from 'radix-ui';
import * as React from 'react';

import { BottomTintReset } from '@/components/ui/bar-tint-reset';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogClose,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogTitle,
} from '@/components/ui/dialog';
import { SheetHandle, sheetBottomShape } from '@/components/ui/sheet';
import { useFocusReturn } from '@/components/ui/use-focus-return';
import { useMediaQuery } from '@/hooks';
import { cn } from '@/lib/utils';

type ModalSize = 'sm' | 'md' | 'lg' | 'xl' | 'full';
type ModalMobileVariant = 'dialog' | 'sheet';

const SIZE_CLASSES: Record<ModalSize, string> = {
  sm: 'sm:max-w-sm',
  md: 'sm:max-w-lg',
  lg: 'sm:max-w-2xl',
  xl: 'sm:max-w-4xl',
  full: 'sm:max-w-[calc(100vw-2rem)]',
};

export type ModalProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title?: React.ReactNode;
  description?: React.ReactNode;
  /** Before the title and description: a connector icon tile. */
  leading?: React.ReactNode;
  hideTitle?: boolean;
  children: React.ReactNode;
  footer?: React.ReactNode;
  className?: string;
  contentClassName?: string;
  showCloseButton?: boolean;
  isPerformingTask?: boolean;
  size?: ModalSize;
  /**
   * The surface on phones (below lg): a bottom `sheet` (the default, for
   * every form, picker and viewer) or a centred `dialog`, only for a yes/no
   * confirmation. Desktop is always the centred dialog.
   */
  mobileVariant?: ModalMobileVariant;
};

const Modal = React.forwardRef<HTMLDivElement, ModalProps>(function Modal(
  {
    open,
    onOpenChange,
    title,
    description,
    leading,
    hideTitle = false,
    children,
    footer,
    className,
    contentClassName,
    showCloseButton = true,
    isPerformingTask = false,
    size = 'md',
    mobileVariant = 'sheet',
  },
  ref,
) {
  const { isMobile } = useMediaQuery();
  const isMobileSheet = mobileVariant === 'sheet' && isMobile;
  const shouldShowCloseButton = showCloseButton && !isPerformingTask;
  // The phone sheet opens without autofocus so the keyboard stays down.
  const focusReturn = useFocusReturn(
    isMobileSheet ? (event) => event.preventDefault() : undefined,
  );

  // When a task is performing, block click-outside / pointer-outside to
  // mirror the legacy WrapperModal lock. Esc remains enabled (Radix default).
  const blockOutsideInteractions = isPerformingTask
    ? (event: Event) => event.preventDefault()
    : undefined;

  // Radix requires a DialogTitle in the a11y tree. If the consumer wants the
  // title hidden visually, wrap it in VisuallyHidden so screen readers still
  // announce it. If no title was supplied at all, provide a sensible default
  // ("Dialog") behind VisuallyHidden so Radix never warns.
  const resolvedTitle = title ?? 'Dialog';
  const showTitle = Boolean(title) && !hideTitle;

  const descriptionNode = description ? (
    <DialogDescription className={showTitle ? 'mt-2' : undefined}>
      {description}
    </DialogDescription>
  ) : (
    <VisuallyHidden.Root>
      <DialogDescription>{resolvedTitle}</DialogDescription>
    </VisuallyHidden.Root>
  );

  // A visible title and its description share one flex item, so the
  // description sits 8px under the title rather than the column's 16px.
  // A `leading` tile sits beside that pair, as in PanelHeader.
  const headerNode = showTitle ? (
    leading ? (
      <div data-slot="modal-header" className="flex shrink-0 items-start gap-3">
        {leading}
        <div className="min-w-0 flex-1">
          <DialogTitle>{title}</DialogTitle>
          {descriptionNode}
        </div>
      </div>
    ) : (
      <div data-slot="modal-header" className="shrink-0">
        <DialogTitle>{title}</DialogTitle>
        {descriptionNode}
      </div>
    )
  ) : (
    <>
      <VisuallyHidden.Root>
        <DialogTitle>{resolvedTitle}</DialogTitle>
      </VisuallyHidden.Root>
      {descriptionNode}
    </>
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogPortal>
        <DialogOverlay />
        <DialogPrimitive.Content
          ref={ref}
          data-slot="modal-content"
          data-mobile-sheet={isMobileSheet ? '' : undefined}
          onPointerDownOutside={blockOutsideInteractions}
          onInteractOutside={blockOutsideInteractions}
          {...focusReturn}
          // Radix portals this to <body> in the DOM, but React still bubbles
          // synthetic events through the JSX tree. Stop the bubble at the
          // modal boundary so consumers mounted inside clickable cards (e.g.
          // MoveToFolderModal inside AgentCard) don't trigger the card's
          // onClick when the user interacts inside the modal.
          onClick={(event) => event.stopPropagation()}
          className={cn(
            'bg-card text-foreground data-[state=open]:animate-in data-[state=closed]:animate-out fixed z-50 duration-200 outline-none',
            isMobileSheet
              ? // The shared bottom-sheet shape and the sheet elevation;
                // pb-safe clears the iPhone home indicator and keeps 1rem
                // under the footer elsewhere.
                `${sheetBottomShape} pb-safe flex w-full flex-col gap-3 px-4 shadow-lg`
              : cn(
                  'shadow-modal',
                  'data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 top-1/2 left-1/2 flex max-h-[85dvh] w-full max-w-[calc(100%-2rem)] -translate-x-1/2 -translate-y-1/2 flex-col gap-4 rounded-2xl p-8',
                  SIZE_CLASSES[size],
                  className,
                ),
          )}
        >
          {isMobileSheet && <BottomTintReset />}
          {isMobileSheet && <SheetHandle />}
          {headerNode}
          <div
            className={cn(
              // overflow-y-auto forces overflow-x:auto and establishes a clip
              // box. pt-3 reserves room so a floating Input label (which sits
              // ~10px above its field) at the top of the scroll area isn't
              'no-scrollbar text-foreground overflow-y-auto px-1 pt-3 pb-0.5',
              // The body is the one scroller; header and footer stay put.
              'min-h-0 grow',
              contentClassName,
            )}
          >
            {children}
          </div>
          {footer ? (
            // Phones stack the buttons full width, primary on top; from sm
            // up they sit in one right-aligned row.
            <div
              data-slot="modal-footer"
              className="flex shrink-0 flex-col-reverse gap-3 sm:flex-row sm:justify-end"
            >
              {footer}
            </div>
          ) : null}
          {shouldShowCloseButton && !isMobileSheet && (
            <DialogClose asChild>
              <Button
                variant="ghost-muted"
                size="icon-sm"
                aria-label="Close"
                className="absolute top-2 right-2"
              >
                <XIcon />
              </Button>
            </DialogClose>
          )}
        </DialogPrimitive.Content>
      </DialogPortal>
    </Dialog>
  );
});

type ModalActionsProps = {
  cancelLabel: React.ReactNode;
  onCancel: () => void;
  /** Leave out for a footer with only the cancel button (a read-only view). */
  submitLabel?: React.ReactNode;
  onSubmit?: () => void;
  /** Spinner on the submit button (it is also disabled). */
  pending?: boolean;
  /** Disables submit without a spinner (the form isn't valid yet). */
  disabled?: boolean;
  /** A red submit, for deletes. */
  destructive?: boolean;
  /** A button pinned to the footer's left edge from sm up (Test connection). */
  footerStart?: React.ReactNode;
  /** Extra props for the submit (type="submit", form, data-testid). */
  submitProps?: Omit<React.ComponentProps<typeof Button>, 'children'>;
  /** Extra props for Cancel. */
  cancelProps?: Omit<React.ComponentProps<typeof Button>, 'children'>;
};

/**
 * The standard modal footer: a ghost Cancel and a primary (or destructive)
 * submit, both large pills. Pass it as Modal's `footer`. Without
 * `submitLabel` only Cancel renders.
 */
function ModalActions({
  cancelLabel,
  onCancel,
  submitLabel,
  onSubmit,
  pending = false,
  disabled = false,
  destructive = false,
  footerStart,
  submitProps,
  cancelProps,
}: ModalActionsProps) {
  return (
    <>
      {footerStart ? (
        <div
          data-slot="modal-footer-start"
          className="flex flex-col sm:mr-auto"
        >
          {footerStart}
        </div>
      ) : null}
      <Button
        type="button"
        variant="ghost"
        size="lg"
        shape="pill"
        onClick={onCancel}
        {...cancelProps}
      >
        {cancelLabel}
      </Button>
      {submitLabel ? (
        <Button
          type="button"
          variant={destructive ? 'destructive' : 'default'}
          size="lg"
          shape="pill"
          onClick={onSubmit}
          disabled={disabled}
          loading={pending}
          {...submitProps}
        >
          {submitLabel}
        </Button>
      ) : null}
    </>
  );
}

export { Modal, ModalActions };
export type { ModalActionsProps };
