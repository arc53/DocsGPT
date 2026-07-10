'use client';

import { XIcon } from 'lucide-react';
import { VisuallyHidden } from 'radix-ui';
import * as React from 'react';

import {
  Dialog,
  DialogClose,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogTitle,
} from '@/components/ui/dialog';
import { useMediaQuery } from '../../hooks';
import { cn } from '@/lib/utils';
import * as DialogPrimitive from '@radix-ui/react-dialog';

type ModalSize = 'sm' | 'md' | 'lg' | 'xl' | 'full';
type ModalMobileVariant = 'modal' | 'sheet';

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
  hideTitle?: boolean;
  children: React.ReactNode;
  footer?: React.ReactNode;
  className?: string;
  contentClassName?: string;
  showCloseButton?: boolean;
  isPerformingTask?: boolean;
  size?: ModalSize;
  mobileVariant?: ModalMobileVariant;
};

const Modal = React.forwardRef<HTMLDivElement, ModalProps>(function Modal(
  {
    open,
    onOpenChange,
    title,
    description,
    hideTitle = false,
    children,
    footer,
    className,
    contentClassName,
    showCloseButton = true,
    isPerformingTask = false,
    size = 'md',
    mobileVariant = 'modal',
  },
  ref,
) {
  const { isMobile } = useMediaQuery();
  const isMobileSheet = mobileVariant === 'sheet' && isMobile;
  const shouldShowCloseButton = showCloseButton && !isPerformingTask;

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
  const titleNode =
    hideTitle || !title ? (
      <VisuallyHidden.Root>
        <DialogTitle>{resolvedTitle}</DialogTitle>
      </VisuallyHidden.Root>
    ) : (
      <DialogTitle>{title}</DialogTitle>
    );

  const descriptionNode = description ? (
    <DialogDescription>{description}</DialogDescription>
  ) : (
    <VisuallyHidden.Root>
      <DialogDescription>{resolvedTitle}</DialogDescription>
    </VisuallyHidden.Root>
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogPortal>
        <DialogOverlay className="bg-black/25 backdrop-blur-xs dark:bg-black/50" />
        <DialogPrimitive.Content
          ref={ref}
          data-slot="modal-content"
          data-mobile-sheet={isMobileSheet ? '' : undefined}
          onPointerDownOutside={blockOutsideInteractions}
          onInteractOutside={blockOutsideInteractions}
          onOpenAutoFocus={
            isMobileSheet ? (event) => event.preventDefault() : undefined
          }
          // Radix portals this to <body> in the DOM, but React still bubbles
          // synthetic events through the JSX tree. Stop the bubble at the
          // modal boundary so consumers mounted inside clickable cards (e.g.
          // MoveToFolderModal inside AgentCard) don't trigger the card's
          // onClick when the user interacts inside the modal.
          onClick={(event) => event.stopPropagation()}
          className={cn(
            'bg-card text-foreground data-[state=open]:animate-in data-[state=closed]:animate-out shadow-modal fixed z-50 duration-200 outline-none',
            isMobileSheet
              ? 'data-[state=closed]:slide-out-to-bottom data-[state=open]:slide-in-from-bottom inset-x-0 bottom-0 flex max-h-[90vh] w-full flex-col gap-3 rounded-t-2xl px-4 pt-2 pb-[max(env(safe-area-inset-bottom),1rem)]'
              : cn(
                  'data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 top-[50%] left-[50%] grid w-full max-w-[calc(100%-2rem)] translate-x-[-50%] translate-y-[-50%] gap-4 rounded-2xl p-8',
                  SIZE_CLASSES[size],
                  className,
                ),
          )}
        >
          {isMobileSheet && (
            <div
              className="mx-auto h-1.5 w-12 shrink-0 rounded-full bg-gray-300 dark:bg-gray-600"
              aria-hidden="true"
            />
          )}
          {titleNode}
          {descriptionNode}
          <div
            className={cn(
              // overflow-y-auto forces overflow-x:auto and establishes a clip
              // box. pt-3 reserves room so a floating Input label (which sits
              // ~10px above its field) at the top of the scroll area isn't
              'no-scrollbar text-foreground overflow-y-auto px-1 pt-3 pb-0.5',
              isMobileSheet && 'min-h-0 grow',
              contentClassName,
            )}
          >
            {children}
          </div>
          {footer ? (
            <div className="flex shrink-0 justify-end gap-2">{footer}</div>
          ) : null}
          {shouldShowCloseButton && !isMobileSheet && (
            <DialogClose
              className="ring-offset-background focus:ring-ring absolute top-3 right-4 rounded-xs opacity-70 transition-opacity hover:opacity-100 focus:ring-2 focus:ring-offset-2 focus:outline-hidden disabled:pointer-events-none"
              aria-label="Close"
            >
              <XIcon className="size-4" />
              <span className="sr-only">Close</span>
            </DialogClose>
          )}
        </DialogPrimitive.Content>
      </DialogPortal>
    </Dialog>
  );
});

export { Modal };
