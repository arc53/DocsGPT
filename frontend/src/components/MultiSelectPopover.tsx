import * as React from 'react';
import { useTranslation } from 'react-i18next';

import CheckmarkIcon from '../assets/checkmark.svg';
import NoFilesDarkIcon from '../assets/no-files-dark.svg';
import NoFilesIcon from '../assets/no-files.svg';
import { useDarkTheme, useMediaQuery } from '../hooks';
import { cn } from '@/lib/utils';
import Spinner from './Spinner';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from './ui/command';
import { Popover, PopoverContent, PopoverTrigger } from './ui/popover';
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
  contentClassName?: string;
  emptyMessage?: string;
  selectedFirst?: boolean;
  title?: string;
};

function renderIcon(icon: MultiSelectPopoverItem['icon']) {
  if (!icon) return null;
  if (typeof icon === 'string') {
    return (
      <img
        src={icon}
        alt=""
        aria-hidden="true"
        className="mr-3 h-5 w-5 shrink-0"
      />
    );
  }
  return (
    <span className="mr-3 flex h-5 w-5 shrink-0 items-center justify-center">
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
  contentClassName,
  emptyMessage,
  selectedFirst = false,
  title,
}: MultiSelectPopoverProps) {
  const { t } = useTranslation();
  const [isDarkTheme] = useDarkTheme();
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
        className="dark:border-border data-[selected=true]:bg-accent flex cursor-pointer items-center justify-between gap-2 rounded-none border-b border-[#D9D9D9] px-3 py-3 last:border-b-0"
        aria-selected={isSelected}
      >
        <div className="mr-3 flex grow items-center overflow-hidden">
          {renderIcon(item.icon)}
          <div className="overflow-hidden">
            <p
              className="overflow-hidden text-sm font-medium text-ellipsis whitespace-nowrap text-gray-900 dark:text-white"
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
          className="border-border bg-card flex h-4 w-4 shrink-0 items-center justify-center rounded-xs border-2 p-[0.5px]"
          aria-hidden="true"
        >
          {isSelected && (
            <img
              src={CheckmarkIcon}
              alt=""
              width={10}
              height={10}
              aria-hidden="true"
            />
          )}
        </div>
      </CommandItem>
    );
  };

  const renderEmptyState = () => (
    <div className="flex flex-col items-center justify-center px-4 py-8 text-center">
      <img
        src={isDarkTheme ? NoFilesDarkIcon : NoFilesIcon}
        alt=""
        aria-hidden="true"
        className="mb-3 h-16 w-16"
      />
      <p className="text-sm text-gray-500 dark:text-gray-400">
        {emptyMessage || t('settings.tools.noToolsFound', 'No results found')}
      </p>
    </div>
  );

  const commandBody = (
    <Command shouldFilter={searchable} className="bg-transparent">
      {title && (
        <div className="shrink-0 px-4 pt-4">
          <h3 className="text-lg font-medium text-gray-900 dark:text-white">
            {title}
          </h3>
        </div>
      )}
      {searchable && (
        <div className="shrink-0 px-4 pt-4">
          <CommandInput placeholder={effectivePlaceholder} className="h-10" />
        </div>
      )}

      {loading ? (
        <div className="text-foreground flex items-center justify-center py-8 dark:text-white">
          <Spinner size="small" />
        </div>
      ) : (
        <div className="dark:border-border mx-4 my-4 flex min-h-0 flex-1 flex-col overflow-hidden rounded-md border border-[#D9D9D9]">
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
                    className="[&_[cmdk-group-heading]]:bg-muted/50 [&_[cmdk-group-heading]]:dark:bg-card [&_[cmdk-group-heading]]:text-muted-foreground p-0 [&_[cmdk-group-heading]]:sticky [&_[cmdk-group-heading]]:top-0 [&_[cmdk-group-heading]]:z-10 [&_[cmdk-group-heading]]:border-b [&_[cmdk-group-heading]]:border-[#D9D9D9] [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:dark:border-[#2E2E2E]"
                  >
                    {groupItems.map(renderItem)}
                  </CommandGroup>
                );
              })
            ) : (
              <CommandGroup className="p-0">
                {orderedItems.map(renderItem)}
              </CommandGroup>
            )}
          </CommandList>
        </div>
      )}

      {footer && (
        <div className="border-border dark:border-border shrink-0 border-t px-4 py-4">
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
          showCloseButton={false}
          onOpenAutoFocus={(e) => e.preventDefault()}
          className={cn(
            'border-border bg-background dark:border-border dark:bg-card flex max-h-[85vh] flex-col gap-0 overflow-hidden rounded-t-2xl p-0 pb-[env(safe-area-inset-bottom)]',
            contentClassName,
          )}
        >
          <SheetTitle className="sr-only">
            {title || effectivePlaceholder}
          </SheetTitle>
          <div
            className="mx-auto mt-2 mb-1 h-1.5 w-12 shrink-0 rounded-full bg-gray-300 dark:bg-gray-600"
            aria-hidden="true"
          />
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
          'border-border bg-background dark:border-border dark:bg-card flex max-h-[min(600px,80vh)] w-[min(462px,calc(100vw-20px))] flex-col overflow-hidden rounded-lg p-0 shadow-md',
          contentClassName,
        )}
      >
        {commandBody}
      </PopoverContent>
    </Popover>
  );
}

export default MultiSelectPopover;
