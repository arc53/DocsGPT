'use client';

import { Check, ChevronsUpDown, X } from 'lucide-react';
import * as React from 'react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
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
            // Grows past the 42px row when the chips wrap.
            'h-auto min-h-10.5 w-full justify-between py-1.5',
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
                      <span
                        role="button"
                        tabIndex={0}
                        className="hover:text-primary/70 flex h-3 w-3 cursor-pointer items-center justify-center"
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
                        <X className="h-3 w-3" />
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
          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        className="border-border bg-card w-(--radix-popover-trigger-width) p-0"
        align="start"
      >
        <Command className="bg-transparent">
          <CommandInput placeholder={searchPlaceholder} className="h-9" />
          <CommandList>
            <CommandEmpty className="py-2 text-center text-sm">
              {emptyText}
            </CommandEmpty>
            <CommandGroup className="p-1">
              {options.map((option) => {
                const isSelected = selected.includes(option.value);
                return (
                  <CommandItem
                    key={option.value}
                    value={option.label}
                    onSelect={() => handleSelect(option.value)}
                    className="cursor-pointer"
                  >
                    <div
                      className={cn(
                        'mr-2 flex h-4 w-4 items-center justify-center rounded-sm border-2',
                        isSelected
                          ? 'border-primary bg-primary text-primary-foreground'
                          : 'border-input',
                      )}
                    >
                      {isSelected && <Check className="h-3 w-3" />}
                    </div>
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
