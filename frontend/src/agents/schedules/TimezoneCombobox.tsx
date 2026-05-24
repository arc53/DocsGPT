import { Check, ChevronsUpDown } from 'lucide-react';
import { useMemo, useState } from 'react';

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

export type TimezoneComboboxProps = {
  value: string;
  options: string[];
  onChange: (next: string) => void;
  placeholder?: string;
  searchPlaceholder?: string;
  emptyText?: string;
  ariaLabel?: string;
  className?: string;
};

/**
 * Case-insensitive substring match against the tz string with separators
 * normalized to spaces — so typing "warsaw", "Warsaw", or "europe war" all
 * match ``Europe/Warsaw``.
 */
export function matchesTimezone(option: string, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const haystack = option.toLowerCase().replace(/[/_]/g, ' ');
  return q
    .split(/\s+/)
    .filter(Boolean)
    .every((token) => haystack.includes(token));
}

// Process-lifetime cache. Offsets are DST-dependent so they're correct for
// "now" — matches what users see in Google Calendar et al. We trade a stale
// offset across a DST boundary mid-session for a much cheaper render path.
const offsetCache = new Map<string, string>();

/**
 * Current UTC offset for an IANA timezone, e.g. ``UTC+1``, ``UTC+5:30``,
 * ``UTC-3:30``, or just ``UTC`` for GMT. Returns the raw input on invalid
 * timezones so the UI degrades gracefully. Memoized for the process lifetime.
 */
export function getTimezoneOffsetLabel(tz: string): string {
  const cached = offsetCache.get(tz);
  if (cached !== undefined) return cached;
  const label = computeTimezoneOffsetLabel(tz);
  offsetCache.set(tz, label);
  return label;
}

function computeTimezoneOffsetLabel(tz: string): string {
  let raw: string | undefined;
  try {
    const fmt = new Intl.DateTimeFormat('en', {
      timeZone: tz,
      timeZoneName: 'shortOffset',
    });
    raw = fmt
      .formatToParts(new Date())
      .find((p) => p.type === 'timeZoneName')?.value;
  } catch {
    return tz;
  }
  if (!raw) return 'UTC';
  // Normalize ``GMT+1`` → ``UTC+1``, ``GMT-05:30`` → ``UTC-5:30``,
  // and the bare ``GMT`` (UTC zone) → ``UTC``.
  const normalized = raw.replace(/^GMT/, 'UTC');
  if (
    normalized === 'UTC' ||
    normalized === 'UTC+0' ||
    normalized === 'UTC-0'
  ) {
    return 'UTC';
  }
  // Strip leading zero in the hour part: ``UTC+05:30`` → ``UTC+5:30``.
  return normalized.replace(
    /^UTC([+-])0?(\d+)(?::(\d{2}))?$/,
    (_, sign, h, m) => (m ? `UTC${sign}${h}:${m}` : `UTC${sign}${h}`),
  );
}

/** Searchable IANA timezone picker (Popover + Command). */
export default function TimezoneCombobox({
  value,
  options,
  onChange,
  placeholder = 'Select timezone',
  searchPlaceholder = 'Search timezone…',
  emptyText = 'No timezone found.',
  ariaLabel,
  className,
}: TimezoneComboboxProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');

  // Precompute (tz, offset) once per options array — ~400 zones is fast but
  // not free, and we re-render on every keystroke during filtering.
  const optionsWithOffset = useMemo(
    () => options.map((tz) => ({ tz, offset: getTimezoneOffsetLabel(tz) })),
    [options],
  );

  const filtered = useMemo(
    () => optionsWithOffset.filter(({ tz }) => matchesTimezone(tz, query)),
    [optionsWithOffset, query],
  );

  const selectedOffset = value ? getTimezoneOffsetLabel(value) : '';

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          role="combobox"
          size="sm"
          aria-expanded={open}
          aria-label={ariaLabel}
          className={cn(
            'h-9 w-full justify-between gap-2 px-3 font-normal',
            !value && 'text-muted-foreground',
            className,
          )}
        >
          {value ? (
            <span className="flex min-w-0 flex-1 items-center justify-between gap-3">
              <span className="truncate">{value}</span>
              <span className="text-muted-foreground shrink-0 text-xs">
                {selectedOffset}
              </span>
            </span>
          ) : (
            <span className="truncate">{placeholder}</span>
          )}
          <ChevronsUpDown className="size-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      {/* z-200 keeps the popover above WrapperModal (z-100); matches DatePicker. */}
      <PopoverContent
        className="z-200 w-[min(20rem,calc(100vw-2rem))] p-0"
        align="start"
      >
        <Command shouldFilter={false}>
          <CommandInput
            placeholder={searchPlaceholder}
            value={query}
            onValueChange={setQuery}
          />
          <CommandList>
            <CommandEmpty>{emptyText}</CommandEmpty>
            <CommandGroup>
              {filtered.map(({ tz, offset }) => {
                const selected = tz === value;
                return (
                  <CommandItem
                    key={tz}
                    value={tz}
                    onSelect={() => {
                      onChange(tz);
                      setOpen(false);
                      setQuery('');
                    }}
                  >
                    <Check
                      className={cn(
                        'mr-2 size-4 shrink-0',
                        selected ? 'opacity-100' : 'opacity-0',
                      )}
                    />
                    <div className="flex w-full min-w-0 items-center justify-between gap-3">
                      <span className="truncate">{tz}</span>
                      <span className="text-muted-foreground shrink-0 text-xs">
                        {offset}
                      </span>
                    </div>
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
