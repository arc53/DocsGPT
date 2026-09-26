import { Check } from 'lucide-react';
import * as React from 'react';
import { useTranslation } from 'react-i18next';

import { useMediaQuery } from '../hooks';
import { cn } from '@/lib/utils';
import { EmptyState } from '@/components/ui/empty-state';
import { LoadingState } from '@/components/ui/loading-state';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from './ui/command';
import { Popover, PopoverContent, PopoverTrigger } from './ui/popover';
import { SectionHeader } from './ui/section-header';
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from './ui/sheet';

export type MultiSelectPopoverItem = {
  id: string;
  label: string;
  description?: string;
  /** Rich variant of ``description`` — wins when both are set. */
  descriptionNode?: React.ReactNode;
  icon?: React.ReactNode | string;
  group?: string;
  disabled?: boolean;
};

export type MultiSelectPopoverProps = {
  trigger: React.ReactNode;
  items: MultiSelectPopoverItem[];
  selectedIds: string[];
  onToggle: (id: string) => void;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  searchable?: boolean;
  searchPlaceholder?: string;
  loading?: boolean;
  footer?: React.ReactNode;
  align?: 'start' | 'center' | 'end';
  side?: 'top' | 'right' | 'bottom' | 'left';
  /** Extra layout classes for the popup (the desktop popover or the mobile sheet). */
  className?: string;
  emptyMessage?: string;
  selectedFirst?: boolean;
  title?: string;
};

function renderIcon(icon: MultiSelectPopoverItem['icon']) {
  if (!icon) return null;
  if (typeof icon === 'string') {
    return (
      <img src={icon} alt="" aria-hidden="true" className="size-5 shrink-0" />
    );
  }
  return (
    <span className="flex size-5 shrink-0 items-center justify-center">
      {icon}
    </span>
  );
}

export function MultiSelectPopover({
  trigger,
  items,
  selectedIds,
  onToggle,
  open,
  onOpenChange,
  searchable = true,
  searchPlaceholder,
  loading = false,
  footer,
  align = 'start',
  side = 'bottom',
  className,
  emptyMessage,
  selectedFirst = false,
  title,
}: MultiSelectPopoverProps) {
  const { t } = useTranslation();
  const { isMobile } = useMediaQuery();
  const selectedSet = React.useMemo(() => new Set(selectedIds), [selectedIds]);

  const orderedItems = React.useMemo(() => {
    if (!selectedFirst) return items;
    const selected: MultiSelectPopoverItem[] = [];
    const unselected: MultiSelectPopoverItem[] = [];
    for (const item of items) {
      (selectedSet.has(item.id) ? selected : unselected).push(item);
    }
    return [...selected, ...unselected];
  }, [items, selectedSet, selectedFirst]);

  const grouped = React.useMemo(() => {
    const groupOrder: string[] = [];
    const map = new Map<string, MultiSelectPopoverItem[]>();
    orderedItems.forEach((item) => {
      const key = item.group ?? '';
      if (!map.has(key)) {
        groupOrder.push(key);
        map.set(key, []);
      }
      map.get(key)!.push(item);
    });
    return { groupOrder, map };
  }, [orderedItems]);

  const hasGroups = grouped.groupOrder.some((g) => g !== '');
  const effectivePlaceholder =
    searchPlaceholder || t('settings.tools.searchPlaceholder', 'Search...');

  const renderItem = (item: MultiSelectPopoverItem) => {
    const isSelected = selectedSet.has(item.id);
    return (
      <CommandItem
        key={item.id}
        value={`${item.label} ${item.id}`}
        disabled={item.disabled}
        onSelect={() => {
          if (!item.disabled) onToggle(item.id);
        }}
        checked={isSelected}
        className="cursor-pointer justify-between"
        aria-selected={isSelected}
      >
        <div className="mr-3 flex grow items-center gap-3 overflow-hidden">
          {renderIcon(item.icon)}
          <div className="overflow-hidden">
            <p
              className="text-foreground overflow-hidden text-sm font-medium text-ellipsis whitespace-nowrap"
              title={item.label}
            >
              {item.label}
            </p>
            {item.descriptionNode ? (
              <div className="overflow-hidden">{item.descriptionNode}</div>
            ) : item.description ? (
              <p className="text-muted-foreground overflow-hidden text-xs text-ellipsis whitespace-nowrap">
                {item.description}
              </p>
            ) : null}
          </div>
        </div>
        <div
          className="border-border bg-card flex size-4 shrink-0 items-center justify-center rounded-xs border-2"
          aria-hidden="true"
        >
          {isSelected && (
            <Check className="text-primary size-2.5" aria-hidden="true" />
          )}
        </div>
      </CommandItem>
    );
  };

  const renderEmptyState = () => (
    <EmptyState
      size="xs"
      title={
        emptyMessage || t('settings.tools.noToolsFound', 'No results found')
      }
    />
  );

  const commandBody = (
    <Command shouldFilter={searchable}>
      {title && (
        <div className="shrink-0 px-4 pt-4">
          <SectionHeader as="h3" size="xs" title={title} />
        </div>
      )}
      {searchable && (
        <div className="shrink-0 px-4 pt-4">
          <CommandInput placeholder={effectivePlaceholder} className="h-10" />
        </div>
      )}

      {loading ? (
        <LoadingState fill="block" size="sm" />
      ) : (
        <div className="border-border mx-4 my-4 flex min-h-0 flex-1 flex-col overflow-hidden rounded-md border">
          <CommandList className="max-h-none min-h-0 flex-1 overflow-y-auto">
            <CommandEmpty>{renderEmptyState()}</CommandEmpty>
            {hasGroups ? (
              grouped.groupOrder.map((groupKey) => {
                const groupItems = grouped.map.get(groupKey) || [];
                if (groupItems.length === 0) return null;
                return (
                  <CommandGroup
                    key={`group-${groupKey || 'ungrouped'}`}
                    heading={groupKey || undefined}
                  >
                    {groupItems.map(renderItem)}
                  </CommandGroup>
                );
              })
            ) : (
              <CommandGroup>{orderedItems.map(renderItem)}</CommandGroup>
            )}
          </CommandList>
        </div>
      )}

      {footer && (
        <div className="border-border shrink-0 border-t px-4 py-4">
          {footer}
        </div>
      )}
    </Command>
  );

  if (isMobile) {
    return (
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetTrigger asChild>{trigger}</SheetTrigger>
        <SheetContent
          side="bottom"
          handle
          showCloseButton={false}
          onOpenAutoFocus={(e) => e.preventDefault()}
          className={cn('overflow-hidden', className)}
        >
          <SheetTitle className="sr-only">
            {title || effectivePlaceholder}
          </SheetTitle>
          {commandBody}
        </SheetContent>
      </Sheet>
    );
  }

  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverTrigger asChild>{trigger}</PopoverTrigger>
      <PopoverContent
        align={align}
        side={side}
        className={cn(
          'flex max-h-[min(600px,80vh)] w-[min(462px,calc(100vw-20px))] flex-col overflow-hidden p-0',
          className,
        )}
      >
        {commandBody}
      </PopoverContent>
    </Popover>
  );
}

export default MultiSelectPopover;
