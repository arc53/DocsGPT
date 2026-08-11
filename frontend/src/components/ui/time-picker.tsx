import { Clock } from 'lucide-react';
import * as React from 'react';

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { cn } from '@/lib/utils';

export interface TimePickerProps {
  /** 24-hour "HH:MM" value (matches the native <input type="time"> contract). */
  value: string;
  onChange: (next: string) => void;
  ariaLabel?: string;
  className?: string;
  /** Minute step within the dropdown. Default 1 (minute precision). */
  minuteStep?: number;
  /** Hide the leading clock icon when ``false``. */
  showIcon?: boolean;
}

const pad2 = (n: number): string => String(n).padStart(2, '0');

const parseValue = (value: string): { hour: number; minute: number } => {
  const m = /^(\d{1,2}):(\d{1,2})$/.exec(value ?? '');
  if (!m) return { hour: 9, minute: 0 };
  const hour = Math.max(0, Math.min(23, Number(m[1])));
  const minute = Math.max(0, Math.min(59, Number(m[2])));
  return { hour, minute };
};

/**
 * Shadcn-style time picker composed of two Selects (hours + minutes).
 * Theme-aware (avoids the native <input type="time"> styling issues in dark mode).
 */
export function TimePicker({
  value,
  onChange,
  ariaLabel,
  className,
  minuteStep = 1,
  showIcon = true,
}: TimePickerProps) {
  const { hour, minute } = React.useMemo(() => parseValue(value), [value]);

  const hourOptions = React.useMemo(
    () => Array.from({ length: 24 }, (_, i) => i),
    [],
  );
  const minuteOptions = React.useMemo(() => {
    const step = Math.max(1, Math.floor(minuteStep));
    return Array.from({ length: Math.ceil(60 / step) }, (_, i) => i * step);
  }, [minuteStep]);

  const emit = (h: number, m: number) => onChange(`${pad2(h)}:${pad2(m)}`);

  return (
    <div
      className={cn('inline-flex items-center gap-1.5', className)}
      role="group"
      aria-label={ariaLabel}
    >
      {showIcon && (
        <Clock
          className="text-muted-foreground size-4 shrink-0"
          aria-hidden="true"
        />
      )}
      <Select
        value={String(hour)}
        onValueChange={(v) => emit(Number(v), minute)}
      >
        <SelectTrigger
          size="sm"
          aria-label={ariaLabel ? `${ariaLabel} hours` : 'Hours'}
          className="h-9 w-[4.25rem]"
        >
          <SelectValue>{pad2(hour)}</SelectValue>
        </SelectTrigger>
        <SelectContent className="max-h-60">
          {hourOptions.map((h) => (
            <SelectItem key={h} value={String(h)}>
              {pad2(h)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <span className="text-muted-foreground text-sm select-none">:</span>
      <Select
        value={String(minute)}
        onValueChange={(v) => emit(hour, Number(v))}
      >
        <SelectTrigger
          size="sm"
          aria-label={ariaLabel ? `${ariaLabel} minutes` : 'Minutes'}
          className="h-9 w-[4.25rem]"
        >
          <SelectValue>{pad2(minute)}</SelectValue>
        </SelectTrigger>
        <SelectContent className="max-h-60">
          {minuteOptions.map((m) => (
            <SelectItem key={m} value={String(m)}>
              {pad2(m)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
