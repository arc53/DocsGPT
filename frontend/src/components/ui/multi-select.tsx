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
  const { t } = useTranslation();
  const [open, setOpen] = React.useState(false);
  const control = useFormFieldControl<{
    id?: string;
    disabled?: boolean;
    'aria-invalid'?: React.AriaAttributes['aria-invalid'];
    'aria-describedby'?: string;
    'aria-required'?: React.AriaAttributes['aria-required'];
  }>({ id });

  const handleSelect = (value: string) => {
    const newSelected = selected.includes(value)
      ? selected.filter((item) => item !== value)
      : [...selected, value];
    onChange(newSelected);
  };

  const selectedOptions = options.filter((option) =>
    selected.includes(option.value),
  );
  // Pills show one chip and "+N more", so a toolbar stays one row.
  const chipLimit = shape === 'pill' ? 1 : 2;

  return (
    <Popover open={open} onOpenChange={setOpen} modal={modal}>
      <PopoverTrigger asChild>
        <Button
          variant="combobox"
          size="field"
          shape={shape}
          role="combobox"
          data-slot="multi-select-trigger"
          data-placeholder={selected.length ? undefined : ''}
          {...control}
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
            {selected.length === 0 ? (
              placeholder
            ) : (
              <>
                {/* No X on the chips: the trigger is a <button>, so a remove
                    control can't nest in it. Unselect in the list. */}
                {selectedOptions.slice(0, chipLimit).map((option) => (
                  <Badge
                    key={option.value}
                    className="max-w-full min-w-0 shrink"
                  >
                    <span className="truncate">{option.label}</span>
                  </Badge>
                ))}
                {selected.length > chipLimit && (
                  <span className="text-muted-foreground shrink-0 text-xs">
                    {t('components.multiSelect.more', {
                      count: selected.length - chipLimit,
                    })}
                  </span>
                )}
              </>
            )}
          </div>
          <ChevronDown className="size-4 shrink-0 opacity-50 transition-transform duration-200 group-data-[state=open]:rotate-180" />
        </Button>
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
