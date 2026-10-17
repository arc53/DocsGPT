import { ChevronDown } from 'lucide-react';
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
import { cn } from '@/lib/utils';

export interface ComboboxOption {
  /** Returned to `onValueChange`; unique within the list. */
  value: string;
  /** The row and trigger text, and what the built-in filter matches. */
  label: string;
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
};

/**
 * A searchable single-select picker: a combobox Button (SelectTrigger's
 * rotating chevron) opening a Command list in a popover at least the
 * trigger's width (18rem by default). The picked row is `checked`.
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
}: ComboboxProps) {
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

  const select = (option: ComboboxOption) => {
    onValueChange(option.value, option);
    setOpen(false);
    onSearchChange?.('');
  };

  return (
    <Popover open={open} onOpenChange={setOpen} modal={modal}>
      <PopoverTrigger asChild>
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
      </PopoverTrigger>
      <PopoverContent
        className="w-72 max-w-[calc(100vw-2rem)] min-w-(--radix-popover-trigger-width) p-0"
        align={align}
      >
        <Command shouldFilter={shouldFilter}>
          <CommandInput
            placeholder={searchPlaceholder}
            value={search}
            onValueChange={onSearchChange}
          />
          <CommandList>
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
                        keywords={[option.label, ...(option.keywords ?? [])]}
                        checked={checked}
                        onSelect={() => select(option)}
                      >
                        {renderItem ? (
                          renderItem(option, { checked })
                        ) : (
                          <>
                            {option.leading}
                            <span
                              className="min-w-0 flex-1 truncate"
                              title={option.label}
                            >
                              {option.label}
                            </span>
                            {option.hint && (
                              <span
                                data-slot="combobox-hint"
                                className="text-muted-foreground shrink-0 text-xs"
                              >
                                {option.hint}
                              </span>
                            )}
                          </>
                        )}
                      </CommandItem>
                    );
                  })}
                </CommandGroup>
              ),
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

export { Combobox };
