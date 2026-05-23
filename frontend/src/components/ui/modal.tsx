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
import { cn } from '@/lib/utils';
import * as DialogPrimitive from '@radix-ui/react-dialog';

type ModalSize = 'sm' | 'md' | 'lg' | 'xl' | 'full';

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
  },
  ref,
) {
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

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogPortal>
        <DialogOverlay className="bg-black/25 backdrop-blur-xs dark:bg-black/50" />
        <DialogPrimitive.Content
          ref={ref}
          data-slot="modal-content"
          onPointerDownOutside={blockOutsideInteractions}
          onInteractOutside={blockOutsideInteractions}
          className={cn(
            'bg-card text-foreground data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 fixed top-[50%] left-[50%] z-50 grid w-full max-w-[calc(100%-2rem)] translate-x-[-50%] translate-y-[-50%] gap-4 rounded-2xl p-8 shadow-[0px_4px_40px_-3px_#0000001A] duration-200 outline-none',
            SIZE_CLASSES[size],
            className,
          )}
        >
          {titleNode}
          {description ? (
            <DialogDescription>{description}</DialogDescription>
          ) : null}
          <div
            className={cn(
              'no-scrollbar text-foreground overflow-y-auto',
              contentClassName,
            )}
          >
            {children}
          </div>
          {footer ? (
            <div className="flex justify-end gap-2">{footer}</div>
          ) : null}
          {shouldShowCloseButton && (
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
