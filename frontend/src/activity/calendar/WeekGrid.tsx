import { Radar, RefreshCw, TriangleAlert } from 'lucide-react';
import type { CSSProperties, ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { Card } from '@/components/ui/card';
import { cn, focusRing } from '@/lib/utils';

import {
  formatClock,
  formatCount,
  intlLocale,
} from '../../utils/dateTimeUtils';
import { addDays, dayKey, hourOf, sameDay, startOfDay } from './dates';
import {
  blockState,
  byDay,
  eventClass,
  hourRange,
  layoutDay,
  SLOT_HOURS,
  blockCount,
  STATE_CLASS,
  type FrequentBlock,
} from './layout';
import { eventTitle, syncSummary } from './labels';
import type { CalendarEvent, MonitorRange } from './types';

/** One hour's height in the grid, in px (the hour labels' `h-11`). */
const HOUR_PX = 44;

// Positions are computed at runtime, so they travel as CSS custom properties
// the elements' classes read (DESIGN.md "Inline styles").
/** A frequent block's strip width, in px; strips sit at the column's right edge. */
const STRIP_PX = 22;

export type WeekGridProps = {
  days: Date[];
  events: CalendarEvent[];
  monitors: MonitorRange[];
  now: number;
  onSelectEvent: (event: CalendarEvent) => void;
  onSelectBlock: (block: FrequentBlock) => void;
  onSelectMonitor: (monitor: MonitorRange) => void;
};

/**
 * The time grid of a day or a week: a header per day, the all-day lane
 * (monitors as bars from creation to expiry), then the hours with each slot
 * coloured by its state and each knowledge sync batch at its time. A schedule
 * that runs hourly or more often is one tall block per day instead of a slot
 * per run.
 */
export default function WeekGrid({
  days,
  events,
  monitors,
  now,
  onSelectEvent,
  onSelectBlock,
  onSelectMonitor,
}: WeekGridProps) {
  const { t, i18n } = useTranslation();
  const [first, last] = hourRange(events);
  const hours = Array.from({ length: last - first }, (_, i) => first + i);
  const grouped = byDay(events);
  const columns = `4.25rem repeat(${days.length}, minmax(0, 1fr))`;
  const weekday = new Intl.DateTimeFormat(intlLocale(i18n.language), {
    weekday: 'short',
  });
  const today = new Date(now);
  const windowStart = days[0];
  const windowEnd = addDays(days[days.length - 1], 1);

  // A range's first and last column inside the window, 1-based after the gutter.
  const span = (from: string | null, to: string | null) => {
    const start = from ? startOfDay(new Date(from)) : windowStart;
    const end = to ? new Date(to) : windowEnd;
    let a = days.findIndex((d) => d >= start);
    if (start < windowStart) a = 0;
    let b = days.length - 1;
    for (let i = days.length - 1; i >= 0; i--) {
      if (days[i] < end) {
        b = i;
        break;
      }
    }
    if (a === -1 || end <= windowStart) return null;
    return `${a + 2} / ${b + 3}`;
  };

  const lane = (label: string, bars: ReactNode[]) => (
    <div
      className="border-border grid grid-cols-(--cols) gap-y-1 border-b py-1.5"
      style={{ '--cols': columns } as CSSProperties}
    >
      <div
        className="text-muted-foreground row-(--rows) px-2 pt-1 text-xs"
        style={
          { '--rows': `1 / span ${Math.max(1, bars.length)}` } as CSSProperties
        }
      >
        {label}
      </div>
      {bars}
    </div>
  );

  const monitorBars = monitors.flatMap((monitor) => {
    const col = span(monitor.starts_at, monitor.ends_at);
    if (!col) return [];
    return [
      <button
        key={monitor.monitor_id}
        type="button"
        style={{ '--col': col } as CSSProperties}
        onClick={() => onSelectMonitor(monitor)}
        className={cn(
          focusRing,
          'hover:bg-accent col-(--col) flex min-w-0 items-center gap-1.5 rounded-md px-2 py-1 text-left text-xs font-medium outline-none',
          monitor.status === 'paused'
            ? 'text-muted-foreground border-muted-foreground border border-dashed'
            : 'bg-muted text-foreground',
        )}
      >
        <Radar aria-hidden className="size-3 shrink-0" />
        <span className="truncate" title={monitor.description || undefined}>
          {monitor.description || t('monitors.untitled')}
        </span>
      </button>,
    ];
  });

  return (
    <Card variant="subtle" padding="none" className="overflow-hidden">
      <div
        className="border-border grid grid-cols-(--cols) border-b"
        style={{ '--cols': columns } as CSSProperties}
      >
        <div />
        {days.map((day) => (
          <div
            key={dayKey(day)}
            className="border-border flex items-baseline gap-1.5 border-l px-2 py-2"
          >
            <span className="text-muted-foreground text-xs">
              {weekday.format(day)}
            </span>
            {sameDay(day, today) ? (
              <span className="bg-primary text-primary-foreground grid size-6 place-items-center rounded-full text-xs font-semibold">
                {day.getDate()}
              </span>
            ) : (
              <span className="text-sm font-semibold">{day.getDate()}</span>
            )}
          </div>
        ))}
      </div>
      {monitorBars.length > 0 &&
        lane(t('activity.calendar.watching'), monitorBars)}
      <div
        className="grid grid-cols-(--cols)"
        style={{ '--cols': columns } as CSSProperties}
      >
        <div>
          {hours.map((hour) => (
            <div
              key={hour}
              className="text-muted-foreground h-11 pe-2 text-right text-xs tabular-nums"
            >
              {`${String(hour).padStart(2, '0')}:00`}
            </div>
          ))}
        </div>
        {days.map((day) => {
          const { placed, blocks } = layoutDay(grouped.get(dayKey(day)) ?? []);
          const stripSpace = blocks.length * STRIP_PX + (blocks.length ? 4 : 0);
          const nowHour = hourOf(today);
          return (
            <div
              key={dayKey(day)}
              data-day={dayKey(day)}
              className="border-border relative h-(--h) border-l"
              style={{ '--h': `${hours.length * HOUR_PX}px` } as CSSProperties}
            >
              {hours.slice(1).map((hour, i) => (
                <div
                  key={hour}
                  aria-hidden
                  className="border-border absolute inset-x-0 top-(--top) border-t"
                  style={{ '--top': `${(i + 1) * HOUR_PX}px` } as CSSProperties}
                />
              ))}
              {placed.map(({ event, hour, lane: index, lanes }) => {
                const at = new Date(event.at);
                const title = eventTitle(event, t);
                const label = `${formatClock(at)} ${title}`;
                const detail =
                  event.kind === 'sync'
                    ? syncSummary(event, t)
                    : t(`activity.calendar.state.${event.state}`);
                return (
                  <button
                    key={`${event.schedule_id}:${event.at}`}
                    type="button"
                    data-kind={event.kind}
                    data-state={event.state}
                    title={`${label} · ${detail}`}
                    aria-label={`${label}, ${detail}`}
                    onClick={() => onSelectEvent(event)}
                    className={cn(
                      focusRing,
                      eventClass(event),
                      'absolute top-(--top) left-(--left) h-(--h) w-(--w) truncate rounded-md px-1.5 py-1 text-left text-xs leading-4 font-medium outline-none hover:brightness-95',
                    )}
                    style={
                      {
                        '--top': `${(hour - first) * HOUR_PX + 1}px`,
                        '--h': `${SLOT_HOURS * HOUR_PX + 2}px`,
                        '--left': `calc((100% - ${stripSpace}px) * ${index / lanes} + 2px)`,
                        '--w': `calc((100% - ${stripSpace}px) / ${lanes} - 4px)`,
                      } as CSSProperties
                    }
                  >
                    {event.state === 'running' && (
                      <span
                        aria-hidden
                        className="bg-info me-1 inline-block size-1.5 animate-pulse rounded-full align-middle motion-reduce:animate-none"
                      />
                    )}
                    {event.kind === 'sync' && (
                      <RefreshCw
                        aria-hidden
                        className="me-1 inline size-3 align-[-2px]"
                      />
                    )}
                    {title}
                    {event.kind === 'sync' &&
                      event.sources.some((source) => source.blocked) && (
                        <TriangleAlert
                          aria-hidden
                          className="text-warning ms-1 inline size-3 align-[-2px]"
                        />
                      )}
                  </button>
                );
              })}
              {blocks.map((block, i) => {
                const label = t('activity.calendar.block', {
                  name: block.name ?? '',
                  count: blockCount(block),
                  formatted: formatCount(blockCount(block)),
                  interpolation: { escapeValue: false },
                });
                return (
                  <button
                    key={block.schedule_id}
                    type="button"
                    title={label}
                    aria-label={label}
                    onClick={() => onSelectBlock(block)}
                    className={cn(
                      focusRing,
                      STATE_CLASS[blockState(block.events)],
                      'absolute top-(--top) right-(--right) flex h-(--h) w-(--w) items-center justify-center overflow-hidden rounded-md text-xs font-medium outline-none hover:brightness-95',
                    )}
                    style={
                      {
                        '--top': `${(block.from - first) * HOUR_PX + 1}px`,
                        '--h': `${(block.to - block.from + SLOT_HOURS) * HOUR_PX}px`,
                        '--right': `${2 + i * STRIP_PX}px`,
                        '--w': `${STRIP_PX - 2}px`,
                      } as CSSProperties
                    }
                  >
                    <span className="rotate-180 truncate [writing-mode:vertical-rl]">
                      {label}
                    </span>
                  </button>
                );
              })}
              {sameDay(day, today) && nowHour >= first && nowHour <= last && (
                <div
                  aria-hidden
                  className="bg-primary pointer-events-none absolute inset-x-0 top-(--top) h-0.5"
                  style={
                    {
                      '--top': `${(nowHour - first) * HOUR_PX}px`,
                    } as CSSProperties
                  }
                >
                  <span className="bg-primary absolute -top-1 -left-1 size-2.5 rounded-full" />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </Card>
  );
}
