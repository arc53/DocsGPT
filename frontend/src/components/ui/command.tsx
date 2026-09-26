import { Command as CommandPrimitive } from 'cmdk';
import { SearchIcon } from 'lucide-react';
import * as React from 'react';

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { cn } from '@/lib/utils';

// The search-palette spacing: a 48px input row and roomier rows. Shared by
// CommandDialog and any palette rendered elsewhere (e.g. in a bottom sheet),
// so both look the same.
const PALETTE_CLASSES =
  '**:[[cmdk-group-heading]]:text-muted-foreground **:data-[slot=command-input-wrapper]:h-12 [&_[cmdk-group]:not([hidden])_~[cmdk-group]]:pt-0 [&_[cmdk-input-wrapper]_svg]:h-5 [&_[cmdk-input-wrapper]_svg]:w-5 [&_[cmdk-item]_svg]:h-5 [&_[cmdk-item]_svg]:w-5 **:[[cmdk-group-heading]]:px-2 **:[[cmdk-group-heading]]:font-medium **:[[cmdk-group]]:px-2 **:[[cmdk-input]]:h-12 **:[[cmdk-item]]:px-2 **:[[cmdk-item]]:py-3';

type CommandProps = React.ComponentProps<typeof CommandPrimitive> & {
  /** `palette` is the search-palette spacing CommandDialog uses. */
  variant?: 'default' | 'palette';
};

function Command({ className, variant = 'default', ...props }: CommandProps) {
  return (
    <CommandPrimitive
      data-slot="command"
      data-variant={variant}
      className={cn(
        'bg-popover text-popover-foreground flex h-full w-full flex-col overflow-hidden rounded-xl',
        variant === 'palette' && PALETTE_CLASSES,
        className,
      )}
      {...props}
    />
  );
}

function CommandDialog({
  title = 'Command Palette',
  description = 'Search for a command to run...',
  children,
  className,
  showCloseButton = true,
  commandProps,
  ...props
}: React.ComponentProps<typeof Dialog> & {
  title?: string;
  description?: string;
  className?: string;
  showCloseButton?: boolean;
  /**
   * Props for the palette's Command, e.g. `shouldFilter={false}` when the
   * results come from a server search, or a controlled `value`.
   */
  commandProps?: Omit<CommandProps, 'variant' | 'children' | 'className'>;
}) {
  return (
    <Dialog {...props}>
      <DialogHeader className="sr-only">
        <DialogTitle>{title}</DialogTitle>
        <DialogDescription>{description}</DialogDescription>
      </DialogHeader>
      <DialogContent
        className={cn('overflow-hidden p-0', className)}
        showCloseButton={showCloseButton}
      >
        <Command variant="palette" {...commandProps}>
          {children}
        </Command>
      </DialogContent>
    </Dialog>
  );
}

function CommandInput({
  className,
  ...props
}: React.ComponentProps<typeof CommandPrimitive.Input>) {
  return (
    <div
      data-slot="command-input-wrapper"
      className="flex h-9 items-center gap-2 border-b px-3"
    >
      <SearchIcon className="size-4 shrink-0 opacity-50" />
      <CommandPrimitive.Input
        data-slot="command-input"
        className={cn(
          // 16px on phones like Input, so iOS doesn't zoom on focus.
          'placeholder:text-muted-foreground selection:bg-primary selection:text-primary-foreground flex h-full w-full rounded-md bg-transparent py-3 text-base outline-hidden disabled:cursor-not-allowed disabled:opacity-50 md:text-sm',
          className,
        )}
        {...props}
      />
    </div>
  );
}

function CommandList({
  className,
  ...props
}: React.ComponentProps<typeof CommandPrimitive.List>) {
  return (
    <CommandPrimitive.List
      data-slot="command-list"
      className={cn(
        'max-h-75 scroll-py-1 overflow-x-hidden overflow-y-auto',
        className,
      )}
      {...props}
    />
  );
}

function CommandEmpty({
  className,
  ...props
}: React.ComponentProps<typeof CommandPrimitive.Empty>) {
  return (
    <CommandPrimitive.Empty
      data-slot="command-empty"
      className={cn('py-6 text-center text-sm', className)}
      {...props}
    />
  );
}

function CommandGroup({
  className,
  ...props
}: React.ComponentProps<typeof CommandPrimitive.Group>) {
  return (
    <CommandPrimitive.Group
      data-slot="command-group"
      className={cn(
        'text-foreground **:[[cmdk-group-heading]]:text-muted-foreground overflow-hidden p-1 **:[[cmdk-group-heading]]:px-2 **:[[cmdk-group-heading]]:py-1.5 **:[[cmdk-group-heading]]:text-xs **:[[cmdk-group-heading]]:font-medium',
        className,
      )}
      {...props}
    />
  );
}

function CommandSeparator({
  className,
  ...props
}: React.ComponentProps<typeof CommandPrimitive.Separator>) {
  return (
    <CommandPrimitive.Separator
      data-slot="command-separator"
      className={cn('bg-border -mx-1 h-px', className)}
      {...props}
    />
  );
}

/**
 * A row in a Command list. `checked` marks the item that is currently chosen
 * (the active prompt in a picker) with a brand tint, apart from the
 * `data-selected` highlight cmdk moves with the pointer and arrow keys. A
 * checked row that is also highlighted keeps its tint and gains a 1px
 * primary ring (the stacked data attributes out-rank the plain accent).
 */
function CommandItem({
  className,
  checked,
  ...props
}: React.ComponentProps<typeof CommandPrimitive.Item> & {
  checked?: boolean;
}) {
  return (
    <CommandPrimitive.Item
      data-slot="command-item"
      data-checked={checked ? 'true' : undefined}
      className={cn(
        "data-[checked=true]:bg-secondary data-[checked=true]:text-secondary-foreground data-[selected=true]:bg-accent data-[selected=true]:text-accent-foreground data-[checked=true]:data-[selected=true]:bg-secondary data-[checked=true]:data-[selected=true]:text-secondary-foreground data-[checked=true]:data-[selected=true]:ring-primary [&_svg:not([class*='text-'])]:text-muted-foreground relative flex cursor-default items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-hidden select-none data-[disabled=true]:pointer-events-none data-[disabled=true]:opacity-50 data-[checked=true]:data-[selected=true]:ring-1 data-[checked=true]:data-[selected=true]:ring-inset [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        className,
      )}
      {...props}
    />
  );
}

function CommandShortcut({
  className,
  ...props
}: React.ComponentProps<'span'>) {
  return (
    <span
      data-slot="command-shortcut"
      className={cn(
        'text-muted-foreground ml-auto text-xs tracking-widest',
        className,
      )}
      {...props}
    />
  );
}

export {
  Command,
  CommandDialog,
  CommandInput,
  CommandList,
  CommandEmpty,
  CommandGroup,
  CommandItem,
  CommandShortcut,
  CommandSeparator,
};
