import { Check, ChevronDown } from 'lucide-react';
import * as React from 'react';

import { Button } from '@/components/ui/button';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command';
import { useFormFieldControl } from '@/components/ui/form-field';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { SectionHeader } from '@/components/ui/section-header';
import {
  Sheet,
  SheetContent,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet';
import { useMediaQuery } from '@/hooks';
import { cn } from '@/lib/utils';

export interface ComboboxOption {
  /** Returned to `onValueChange`; unique within the list. */
  value: string;
  /** The row and trigger text, and what the built-in filter matches. */
  label: string;
  /**
   * A muted line under the label in the row only (a preset's purpose, the
   * start of a prompt), searched like the label. A list with lines marks
   * the picked row with a trailing Check as well as its tint.
   */
  description?: string;
  /** Extra words the built-in filter matches. */
  keywords?: string[];
  /** Muted trailing text in the row and the trigger (a UTC offset). */
  hint?: React.ReactNode;
  /** Before the label in the row (an Avatar). */
  leading?: React.ReactNode;
}

export interface ComboboxGroup {
  heading: React.ReactNode;
  options: ComboboxOption[];
}

type ComboboxProps = {
  /** A flat list; pass `groups` instead for headed sections. */
  options?: ComboboxOption[];
  groups?: ComboboxGroup[];
  /** The picked option's value. Ignored in `add` mode. */
  value?: string | null;
  /**
   * The picked option for the trigger when it isn't in the current list
   * (a server-searched or filtered list, a stored selection not listed).
   */
  valueOption?: ComboboxOption;
  onValueChange: (value: string, option: ComboboxOption) => void;
  /**
   * `select` (default) marks the picked row and shows it on the trigger.
   * `add` picks to add something (a share row): the trigger always shows
   * the placeholder and no row is marked.
   */
  mode?: 'select' | 'add';
  placeholder: string;
  searchPlaceholder?: string;
  emptyText?: React.ReactNode;
  /** false when the caller searches (the server, its own matcher). */
  shouldFilter?: boolean;
  /** The search text, when the caller owns it. */
  search?: string;
  onSearchChange?: (search: string) => void;
  /** Replaces a row's body (row actions); `leading`/`hint` are then yours. */
  renderItem?: (
    option: ComboboxOption,
    state: { checked: boolean },
  ) => React.ReactNode;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /**
   * On by default: a non-modal popover inside a Modal can't scroll or
   * close on an outside click (see multi-select.tsx).
   */
  modal?: boolean;
  align?: 'start' | 'center' | 'end';
  shape?: 'default' | 'pill';
  /** The trigger's id; inside a FormField it defaults to the field's. */
  id?: string;
  disabled?: boolean;
  'aria-label'?: string;
  /** Layout only (width, flex). The trigger is full width by default. */
  className?: string;
  /**
   * A row pinned under the list (a `PickerFooter`: "Go to Prompts" + "Add
   * prompt"). It doesn't scroll with the rows and sits outside cmdk, so Tab
   * reaches its controls and Enter presses them. Pass a function to get
   * `close`, and call it when a control navigates or opens something else.
   */
  footer?:
    React.ReactNode | ((helpers: { close: () => void }) => React.ReactNode);
  /**
   * The picker's title over the search (the multi-pick pickers' chrome:
   * "Tools", "Prompt"). With one the list grows to 600px, as theirs does.
   */
  title?: string;
  /**
   * Controls drawn under the search (a `usePickerKindFilter` track),
   * outside cmdk's key handling, so Enter and the arrows work them rather
   * than the list.
   */
  filters?: React.ReactNode;
  /**
   * On a phone, open as a bottom Sheet with a handle (and the `title`)
   * instead of a popover, like the multi-pick pickers.
   */
  mobileSheet?: boolean;
};

/**
 * A searchable single-select picker: a combobox Button (SelectTrigger's
 * rotating chevron) opening a Command list in a popover at least the
 * trigger's width (18rem by default). The picked row is `checked`. An
 * optional `footer` is pinned under the list; `title`, `filters` and
 * `mobileSheet` opt into the multi-pick pickers' chrome.
 */
function Combobox({
  options,
  groups,
  value,
  valueOption,
  onValueChange,
  mode = 'select',
  placeholder,
  searchPlaceholder,
  emptyText,
  shouldFilter = true,
  search,
  onSearchChange,
  renderItem,
  open: openProp,
  onOpenChange,
  modal = true,
  align = 'start',
  shape = 'default',
  id,
  disabled,
  'aria-label': ariaLabel,
  className,
  footer,
  title,
  filters,
  mobileSheet = false,
}: ComboboxProps) {
  const { isMobile } = useMediaQuery();
  const asSheet = mobileSheet && isMobile;
  // A titled picker or a sheet takes the multi-pick pickers' height.
  const tall = Boolean(title) || asSheet;
  const [openState, setOpenState] = React.useState(false);
  const open = openProp ?? openState;
  const setOpen = (next: boolean) => {
    if (openProp === undefined) setOpenState(next);
    onOpenChange?.(next);
  };
  const control = useFormFieldControl<{
    id?: string;
    disabled?: boolean;
    'aria-invalid'?: React.AriaAttributes['aria-invalid'];
    'aria-describedby'?: string;
    'aria-required'?: React.AriaAttributes['aria-required'];
  }>({ id, disabled });

  const sections: ComboboxGroup[] =
    groups ?? (options ? [{ heading: undefined, options }] : []);
  const picked =
    mode === 'add' || value == null
      ? undefined
      : (sections
          .flatMap((section) => section.options)
          .find((option) => option.value === value) ?? valueOption);
  const shownLabel = picked?.label;
  // One row layout for the whole list, so a row without a line matches.
  const withLines = sections.some((section) =>
    section.options.some((option) => option.description),
  );

  const select = (option: ComboboxOption) => {
    onValueChange(option.value, option);
    setOpen(false);
    onSearchChange?.('');
  };

  const footerNode =
    typeof footer === 'function'
      ? footer({ close: () => setOpen(false) })
      : footer;

  const triggerButton = (
    <Button
      type="button"
      variant="combobox"
      size="field"
      shape={shape}
      role="combobox"
      aria-label={ariaLabel}
      data-slot="combobox-trigger"
      data-placeholder={shownLabel ? undefined : ''}
      {...control}
      // `group` turns the chevron while open, like SelectTrigger's.
      className={cn('group w-full justify-between', className)}
    >
      {shownLabel ? (
        <span className="flex min-w-0 flex-1 items-center justify-between gap-3">
          <span className="truncate" title={shownLabel}>
            {shownLabel}
          </span>
          {picked?.hint && (
            <span className="text-muted-foreground shrink-0 text-xs">
              {picked.hint}
            </span>
          )}
        </span>
      ) : (
        <span className="truncate">{placeholder}</span>
      )}
      <ChevronDown className="size-4 shrink-0 opacity-50 transition-transform duration-200 group-data-[state=open]:rotate-180" />
    </Button>
  );

  const renderRow = (option: ComboboxOption, checked: boolean) => {
    if (renderItem) return renderItem(option, { checked });
    const hint = option.hint && (
      <span
        data-slot="combobox-hint"
        className="text-muted-foreground shrink-0 text-xs"
      >
        {option.hint}
      </span>
    );
    if (!withLines) {
      return (
        <>
          {option.leading}
          <span className="min-w-0 flex-1 truncate" title={option.label}>
            {option.label}
          </span>
          {hint}
        </>
      );
    }
    return (
      <>
        {option.leading}
        <span className="min-w-0 flex-1">
          <span className="block truncate font-medium" title={option.label}>
            {option.label}
          </span>
          {option.description ? (
            <span
              data-slot="combobox-description"
              className="text-muted-foreground block truncate text-xs"
              title={option.description}
            >
              {option.description}
            </span>
          ) : null}
        </span>
        {hint}
        {checked ? (
          <Check aria-hidden="true" className="size-4 text-current" />
        ) : null}
      </>
    );
  };

  const commandBody = (
    <Command
      shouldFilter={shouldFilter}
      className={tall ? 'min-h-0 flex-1' : undefined}
    >
      {title && (
        <div className="shrink-0 px-4 pt-4">
          <SectionHeader as="h3" size="xs" title={title} />
        </div>
      )}
      <div className={cn('shrink-0', title && 'mt-3')}>
        <CommandInput
          placeholder={searchPlaceholder}
          value={search}
          onValueChange={onSearchChange}
        />
      </div>
      {filters ? (
        // cmdk's root turns Enter into "pick the highlighted row" and takes
        // the arrows; a filter's keys stop here.
        <div
          data-slot="combobox-filters"
          className="shrink-0 px-3 pt-2 pb-1"
          onKeyDown={(event) => event.stopPropagation()}
        >
          {filters}
        </div>
      ) : null}
      <CommandList
        className={
          tall ? 'max-h-none min-h-0 flex-1 overflow-y-auto' : undefined
        }
      >
        <CommandEmpty>{emptyText}</CommandEmpty>
        {sections.map((section, index) =>
          section.options.length === 0 ? null : (
            <CommandGroup key={index} heading={section.heading}>
              {section.options.map((option) => {
                const checked =
                  mode === 'select' && value != null
                    ? option.value === value
                    : false;
                return (
                  <CommandItem
                    key={option.value}
                    value={option.value}
                    keywords={[
                      option.label,
                      ...(option.description ? [option.description] : []),
                      ...(option.keywords ?? []),
                    ]}
                    checked={checked}
                    onSelect={() => select(option)}
                  >
                    {renderRow(option, checked)}
                  </CommandItem>
                );
              })}
            </CommandGroup>
          ),
        )}
      </CommandList>
    </Command>
  );

  const body = (
    <>
      {commandBody}
      {footerNode ? (
        // Outside Command: cmdk's root turns Enter into "pick the
        // highlighted row", which would swallow a footer button's Enter.
        <div
          data-slot="combobox-footer"
          className="border-border shrink-0 border-t px-4 py-4"
        >
          {footerNode}
        </div>
      ) : null}
    </>
  );

  if (asSheet) {
    return (
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger asChild>{triggerButton}</SheetTrigger>
        <SheetContent
          side="bottom"
          handle
          // The phone keyboard stays down until the search is tapped.
          onOpenAutoFocus={(event) => event.preventDefault()}
          className="overflow-hidden"
        >
          <SheetTitle className="sr-only">{title || placeholder}</SheetTitle>
          {body}
        </SheetContent>
      </Sheet>
    );
  }

  return (
    <Popover open={open} onOpenChange={setOpen} modal={modal}>
      <PopoverTrigger asChild>{triggerButton}</PopoverTrigger>
      <PopoverContent
        className={cn(
          'w-72 max-w-[calc(100vw-2rem)] min-w-(--radix-popover-trigger-width) p-0',
          tall &&
            'flex max-h-[min(600px,var(--radix-popover-content-available-height))] flex-col overflow-hidden',
        )}
        align={align}
      >
        {body}
      </PopoverContent>
    </Popover>
  );
}

export { Combobox };
