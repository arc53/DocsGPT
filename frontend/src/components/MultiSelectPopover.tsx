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
  /** The group's key; it is also its heading unless `groupHeading` is set. */
  group?: string;
  /** The group's heading when it is more than its key (an icon and a name). */
  groupHeading?: React.ReactNode;
  disabled?: boolean;
};

// The key of the Selected group; no caller's group key starts with a NUL.
const SELECTED_GROUP = '\u0000selected';

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
  /**
   * Lists the rows chosen when the picker opens in a Selected group on top.
   * The set is taken on open and kept until it closes, so toggling only
   * changes a tick and no row moves under the pointer.
   */
  selectedFirst?: boolean;
  /**
   * Off: a group that is the only one in the list draws no heading (the
   * Selected group counts as one). On by default.
   */
  loneGroupHeading?: boolean;
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
  loneGroupHeading = true,
  title,
}: MultiSelectPopoverProps) {
  const { t } = useTranslation();
  const { isMobile } = useMediaQuery();
  const selectedSet = React.useMemo(() => new Set(selectedIds), [selectedIds]);

  // Uncontrolled callers still need to know when it opens, for the snapshot.
  const [uncontrolledOpen, setUncontrolledOpen] = React.useState(false);
  const isOpen = open ?? uncontrolledOpen;
  const handleOpenChange = (next: boolean) => {
    if (open === undefined) setUncontrolledOpen(next);
    onOpenChange?.(next);
  };

  // What was chosen when the picker opened; kept until it closes.
  const [snapshot, setSnapshot] = React.useState<Set<string> | null>(() =>
    isOpen ? new Set(selectedIds) : null,
  );
  const [snapshotOpen, setSnapshotOpen] = React.useState(isOpen);
  if (snapshotOpen !== isOpen) {
    setSnapshotOpen(isOpen);
    setSnapshot(isOpen ? new Set(selectedIds) : null);
  }
  const pinned = selectedFirst ? snapshot : null;

  const grouped = React.useMemo(() => {
    const groupOrder: string[] = [];
    const map = new Map<string, MultiSelectPopoverItem[]>();
    const headings = new Map<string, React.ReactNode>();
    const add = (key: string, item: MultiSelectPopoverItem) => {
      if (!map.has(key)) {
        groupOrder.push(key);
        map.set(key, []);
      }
      map.get(key)!.push(item);
    };
    if (pinned && items.some((item) => pinned.has(item.id))) {
      groupOrder.push(SELECTED_GROUP);
      map.set(SELECTED_GROUP, []);
    }
    items.forEach((item) => {
      const key = item.group ?? '';
      if (item.groupHeading !== undefined && !headings.has(key)) {
        headings.set(key, item.groupHeading);
      }
      add(pinned?.has(item.id) ? SELECTED_GROUP : key, item);
    });
    return { groupOrder, map, headings };
  }, [items, pinned]);

  const nonEmptyGroups = grouped.groupOrder.filter(
    (key) => (grouped.map.get(key)?.length ?? 0) > 0,
  );
  const hasGroups =
    nonEmptyGroups.some((key) => key !== '') &&
    (loneGroupHeading || nonEmptyGroups.length > 1);
  const headingOf = (key: string): React.ReactNode =>
    key === SELECTED_GROUP
      ? t('components.multiSelect.selectedGroup', 'Selected')
      : (grouped.headings.get(key) ?? (key || undefined));
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
        className="justify-between"
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
    <Command shouldFilter={searchable} className="min-h-0 flex-1">
      {title && (
        <div className="shrink-0 px-4 pt-4">
          <SectionHeader as="h3" size="xs" title={title} />
        </div>
      )}
      {searchable && (
        <div className={cn('shrink-0', title && 'mt-3')}>
          <CommandInput placeholder={effectivePlaceholder} />
        </div>
      )}

      {loading ? (
        <LoadingState fill="block" size="sm" />
      ) : (
        <CommandList className="max-h-none min-h-0 flex-1 overflow-y-auto">
          <CommandEmpty>{renderEmptyState()}</CommandEmpty>
          {hasGroups ? (
            nonEmptyGroups.map((groupKey) => (
              <CommandGroup
                key={`group-${groupKey || 'ungrouped'}`}
                heading={headingOf(groupKey)}
              >
                {(grouped.map.get(groupKey) ?? []).map(renderItem)}
              </CommandGroup>
            ))
          ) : (
            <CommandGroup>
              {nonEmptyGroups.flatMap((key) =>
                (grouped.map.get(key) ?? []).map(renderItem),
              )}
            </CommandGroup>
          )}
        </CommandList>
      )}
    </Command>
  );

  // The footer sits outside cmdk: its root turns Enter into "toggle the
  // highlighted row", which would swallow a footer button's Enter.
  const body = (
    <>
      {commandBody}
      {footer && (
        <div
          data-slot="multi-select-footer"
          className="border-border shrink-0 border-t px-4 py-4"
        >
          {footer}
        </div>
      )}
    </>
  );

  if (isMobile) {
    return (
      <Sheet open={isOpen} onOpenChange={handleOpenChange}>
        <SheetTrigger asChild>{trigger}</SheetTrigger>
        <SheetContent
          side="bottom"
          handle
          onOpenAutoFocus={(e) => e.preventDefault()}
          className={cn('overflow-hidden', className)}
        >
          <SheetTitle className="sr-only">
            {title || effectivePlaceholder}
          </SheetTitle>
          {body}
        </SheetContent>
      </Sheet>
    );
  }

  return (
    <Popover open={isOpen} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>{trigger}</PopoverTrigger>
      <PopoverContent
        align={align}
        side={side}
        className={cn(
          'flex max-h-[min(600px,var(--radix-popover-content-available-height))] w-[min(462px,calc(100vw-20px))] flex-col overflow-hidden p-0',
          className,
        )}
      >
        {body}
      </PopoverContent>
    </Popover>
  );
}

export default MultiSelectPopover;
