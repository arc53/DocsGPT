'use client';

import { Check, ChevronsUpDown, X } from 'lucide-react';
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
}

export function MultiSelect({
  options,
  selected,
  onChange,
  placeholder = 'Select items...',
  emptyText = 'No results found.',
  searchPlaceholder = 'Search...',
  className,
}: MultiSelectProps) {
  const [open, setOpen] = React.useState(false);

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
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          className={cn(
            'w-full justify-between border-border bg-card hover:bg-accent',
            !selected.length && 'text-gray-500 dark:text-gray-400',
            className,
          )}
        >
          <div className="flex flex-wrap gap-1">
            {selected.length === 0 ? (
              placeholder
            ) : (
              <>
                {selectedLabels.slice(0, 2).map((label) => {
                  const option = options.find((o) => o.label === label);
                  return (
                    <span
                      key={option?.value || label}
                      className="dark:bg-primary/30 bg-primary/20 inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium text-purple-700 dark:text-purple-300"
                    >
                      {label}
                      <span
                        role="button"
                        tabIndex={0}
                        className="flex h-3 w-3 cursor-pointer items-center justify-center hover:text-purple-900 dark:hover:text-purple-200"
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
                    </span>
                  );
                })}
                {selected.length > 2 && (
                  <span className="text-xs text-gray-600 dark:text-gray-400">
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
        className="w-(--radix-popover-trigger-width) border-border bg-card p-0"
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
                          ? 'border-primary bg-primary text-white'
                          : 'border-gray-400 dark:border-gray-500',
                      )}
                    >
                      {isSelected && <Check className="h-3 w-3 stroke-white" />}
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
