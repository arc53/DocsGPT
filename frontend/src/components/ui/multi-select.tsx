import { ChevronDown, X } from 'lucide-react';
import * as React from 'react';

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
}: MultiSelectProps) {
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

  const handleRemove = (value: string, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    onChange(selected.filter((item) => item !== value));
  };

  const selectedLabels = options
    .filter((option) => selected.includes(option.value))
    .map((option) => option.label);

  return (
    <Popover open={open} onOpenChange={setOpen} modal={modal}>
      <PopoverTrigger asChild>
        <Button
          variant="combobox"
          size="field"
          role="combobox"
          aria-expanded={open}
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
              width and shaves 1rem off the label (a short ref like "A1"
              disappears entirely). */}
          <div className="flex min-w-0 flex-1 flex-wrap gap-1">
            {selected.length === 0 ? (
              placeholder
            ) : (
              <>
                {selectedLabels.slice(0, 2).map((label) => {
                  const option = options.find((o) => o.label === label);
                  return (
                    <Badge
                      key={option?.value || label}
                      className="max-w-[calc(100%-1rem)] min-w-0"
                    >
                      <span className="truncate">{label}</span>
                      {/* A span, not a button: the trigger is already a
                          <button>, and buttons can't nest. */}
                      <span
                        role="button"
                        tabIndex={0}
                        className="hover:text-primary/70 flex size-3 cursor-pointer items-center justify-center"
                        onMouseDown={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                        }}
                        onClick={(e) => handleRemove(option?.value || '', e)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            handleRemove(
                              option?.value || '',
                              e as unknown as React.MouseEvent,
                            );
                          }
                        }}
                      >
                        <X className="size-3" />
                      </span>
                    </Badge>
                  );
                })}
                {selected.length > 2 && (
                  <span className="text-muted-foreground text-xs">
                    +{selected.length - 2} more
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
                    className="cursor-pointer"
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
                    {option.label}
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
