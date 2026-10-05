import { useMemo, useState } from 'react';

import { Combobox } from '@/components/ui/combobox';

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
 * normalized to spaces on both sides — so typing "warsaw", "Warsaw",
 * "europe war" or "Europe/W" all match ``Europe/Warsaw``.
 */
export function matchesTimezone(option: string, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const normalise = (text: string) => text.replace(/[/_]/g, ' ');
  const haystack = normalise(option.toLowerCase());
  // Split on typed spaces only; a separator inside a token ("asia/d",
  // "los_ang") is normalised like the zone name, so it stays one phrase.
  return q
    .split(/\s+/)
    .filter(Boolean)
    .every((token) => haystack.includes(normalise(token)));
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

/** Searchable IANA timezone picker (a Combobox, offset as the hint). */
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
  const [query, setQuery] = useState('');

  // Precompute (tz, offset) once per options array — ~400 zones is fast but
  // not free, and we re-render on every keystroke during filtering.
  const optionsWithOffset = useMemo(
    () =>
      options.map((tz) => ({
        value: tz,
        label: tz,
        hint: getTimezoneOffsetLabel(tz),
      })),
    [options],
  );

  const filtered = useMemo(
    () =>
      optionsWithOffset.filter(({ value: tz }) => matchesTimezone(tz, query)),
    [optionsWithOffset, query],
  );

  return (
    <Combobox
      options={filtered}
      value={value || null}
      // The picked zone stays on the trigger while a search hides its row.
      valueOption={
        value
          ? { value, label: value, hint: getTimezoneOffsetLabel(value) }
          : undefined
      }
      onValueChange={(tz) => onChange(tz)}
      shouldFilter={false}
      search={query}
      onSearchChange={setQuery}
      placeholder={placeholder}
      searchPlaceholder={searchPlaceholder}
      emptyText={emptyText}
      aria-label={ariaLabel}
      className={className}
    />
  );
}
