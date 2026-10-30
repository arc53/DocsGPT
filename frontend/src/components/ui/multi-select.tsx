import { ChevronDown } from 'lucide-react';
import * as React from 'react';
import { useTranslation } from 'react-i18next';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { useFormFieldControl } from '@/components/ui/form-field';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { cn } from '@/lib/utils';

export interface MultiSelectOption {
  value: string;
  label: string;
  /** A muted line under the label in the list; chips show the label only. */
  description?: string;
}

interface MultiSelectProps {
  options: MultiSelectOption[];
  selected: string[];
  onChange: (selected: string[]) => void;
  placeholder?: string;
  emptyText?: string;
  searchPlaceholder?: string;
  className?: string;
  /**
   * Set when the MultiSelect sits inside a Modal. A non-modal popover there
   * cannot scroll (the dialog's scroll lock swallows the wheel, since the
   * dropdown is portalled outside it) and never closes on an outside click
   * (Radix defers that to the document `click`, which Modal stops from
   * propagating). A modal popover owns its own scroll lock and dismisses on
   * pointerdown instead.
   */
  modal?: boolean;
  /** The trigger's id; inside a FormField it defaults to the field's. */
  id?: string;
  /** `pill` in a page toolbar beside pill searches and filters. */
  shape?: 'default' | 'pill';
}

type MultiSelectTriggerProps = Omit<
  React.ComponentProps<typeof Button>,
  'children' | 'variant' | 'size'
> & {
  /** The picked items' names, in the order the chips show them. */
  labels: string[];
  /** How many are picked, when some have no name to show; `labels.length` by default. */
  count?: number;
  /** Shown while nothing is picked. */
  placeholder: string;
  /** `pill` in a page toolbar beside pill searches and filters. */
  shape?: 'default' | 'pill';
};

/**
 * The `combobox field` trigger of a multi-pick: the first two picks as
 * `default` Badges (one on a `pill`), then "+N more", growing past the 38px
 * row when the chips wrap, with the turning chevron. `MultiSelect` draws it,
 * and a picker with its own list (`MultiSelectPopover`) passes it as its
 * `trigger`. Inside a FormField it takes the field's id and aria wiring.
 */
export function MultiSelectTrigger({
  labels,
  count = labels.length,
  placeholder,
  shape = 'default',
  className,
  id,
  ...props
}: MultiSelectTriggerProps) {
  const { t } = useTranslation();
  const control = useFormFieldControl<{
    id?: string;
    disabled?: boolean;
    'aria-invalid'?: React.AriaAttributes['aria-invalid'];
    'aria-describedby'?: string;
    'aria-required'?: React.AriaAttributes['aria-required'];
  }>({ id, disabled: props.disabled });
  // Pills show one chip and "+N more", so a toolbar stays one row.
  const chipLimit = shape === 'pill' ? 1 : 2;

  return (
    <Button
      type="button"
      variant="combobox"
      size="field"
      shape={shape}
      role="combobox"
      data-placeholder={count ? undefined : ''}
      {...props}
      {...control}
      // After the props: a PopoverTrigger asChild passes its own data-slot.
      data-slot="multi-select-trigger"
      className={cn(
        // Grows past the 38px row when the chips wrap; `group` lets the
        // chevron turn while open, like SelectTrigger's.
        'group h-auto min-h-9.5 w-full justify-between py-1.5',
        className,
      )}
    >
      {/* flex-1 gives the chip row a definite width; without it, a lone
          chip's percentage max-width resolves against its own natural
          width and truncates a short label. */}
      <div
        className={cn(
          'flex min-w-0 flex-1 items-center gap-1',
          // A pill sits in a toolbar row: one chip that truncates, then
          // the count, never a second line.
          shape === 'pill' ? 'flex-nowrap' : 'flex-wrap',
        )}
      >
        {count === 0 ? (
          placeholder
        ) : (
          <>
            {/* No X on the chips: the trigger is a <button>, so a remove
                control can't nest in it. Unselect in the list. */}
            {labels.slice(0, chipLimit).map((label, index) => (
              <Badge key={index} className="max-w-full min-w-0 shrink">
                <span className="truncate">{label}</span>
              </Badge>
            ))}
            {count > chipLimit && (
              <span className="text-muted-foreground shrink-0 text-xs">
                {t('components.multiSelect.more', {
                  count: count - chipLimit,
                })}
              </span>
            )}
          </>
        )}
      </div>
      <ChevronDown className="size-4 shrink-0 opacity-50 transition-transform duration-200 group-data-[state=open]:rotate-180" />
    </Button>
  );
}

export function MultiSelect({
  options,
  selected,
  onChange,
  placeholder = 'Select items...',
  emptyText = 'No results found.',
  searchPlaceholder = 'Search...',
  className,
  modal = false,
  id,
  shape = 'default',
}: MultiSelectProps) {
  const [open, setOpen] = React.useState(false);

  const handleSelect = (value: string) => {
    const newSelected = selected.includes(value)
      ? selected.filter((item) => item !== value)
      : [...selected, value];
    onChange(newSelected);
  };

  const selectedLabels = options
    .filter((option) => selected.includes(option.value))
    .map((option) => option.label);

  return (
    <Popover open={open} onOpenChange={setOpen} modal={modal}>
      <PopoverTrigger asChild>
        <MultiSelectTrigger
          id={id}
          labels={selectedLabels}
          count={selected.length}
          placeholder={placeholder}
          shape={shape}
          className={className}
        />
      </PopoverTrigger>
      <PopoverContent
        className="w-(--radix-popover-trigger-width) p-0"
        align="start"
      >
        <Command>
          <CommandInput placeholder={searchPlaceholder} />
          <CommandList>
            <CommandEmpty className="py-2 text-center text-sm">
              {emptyText}
            </CommandEmpty>
            <CommandGroup>
              {options.map((option) => {
                const isSelected = selected.includes(option.value);
                return (
                  <CommandItem
                    key={option.value}
                    value={option.label}
                    onSelect={() => handleSelect(option.value)}
                    checked={isSelected}
                  >
                    {/* Visual only: the row is the control (cmdk handles the
                        click and Enter), so the box takes no focus or events. */}
                    <Checkbox
                      size="sm"
                      checked={isSelected}
                      tabIndex={-1}
                      aria-hidden
                      className="pointer-events-none"
                    />
                    {option.description ? (
                      <span className="flex min-w-0 flex-col">
                        <span>{option.label}</span>
                        <span className="text-muted-foreground text-xs">
                          {option.description}
                        </span>
                      </span>
                    ) : (
                      option.label
                    )}
                  </CommandItem>
                );
              })}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
