import { RefreshCw } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Card } from '@/components/ui/card';
import { cn, focusRing } from '@/lib/utils';

import {
  formatClock,
  formatCount,
  intlLocale,
} from '../../utils/dateTimeUtils';
import { dayKey, sameDay } from './dates';
import {
  blockState,
  byDay,
  eventClass,
  layoutDay,
  blockCount,
  STATE_CLASS,
  type FrequentBlock,
} from './layout';
import { eventTitle } from './labels';
import MonitorChips from './MonitorChips';
import type { CalendarEvent, MonitorRange } from './types';

/** Items a day cell lists before its "+N" opens the day. */
const ITEMS_PER_DAY = 3;

export type MonthGridProps = {
  /** The 42 days of the six weeks that hold the month. */
  days: Date[];
  /** The month shown; days outside it are muted. */
  month: number;
  events: CalendarEvent[];
  now: number;
  onSelectEvent: (event: CalendarEvent) => void;
  onSelectBlock: (block: FrequentBlock) => void;
  onOpenDay: (day: Date) => void;
  /** Monitors active in the window, as chips above the month. */
  monitors: MonitorRange[];
  onSelectMonitor: (monitor: MonitorRange) => void;
};

/**
 * A month as six Monday-first weeks. Each day lists its first few slots by
 * time (a frequent schedule as one "×N" item) and a "+N" that opens the day.
 * The window's monitors sit above it as chips (`MonitorChips`).
 */
export default function MonthGrid({
  days,
  month,
  events,
  now,
  onSelectEvent,
  onSelectBlock,
  onOpenDay,
  monitors,
  onSelectMonitor,
}: MonthGridProps) {
  const { t, i18n } = useTranslation();
  const grouped = byDay(events);
  const weekday = new Intl.DateTimeFormat(intlLocale(i18n.language), {
    weekday: 'short',
  });
  const today = new Date(now);
  const blockLabel = (block: FrequentBlock) =>
    t('activity.calendar.block', {
      name: block.name ?? '',
      count: blockCount(block),
      formatted: formatCount(blockCount(block)),
      interpolation: { escapeValue: false },
    });

  return (
    <div className="flex flex-col gap-6">
      <MonitorChips monitors={monitors} onSelectMonitor={onSelectMonitor} />
      <Card variant="subtle" padding="none" className="overflow-hidden">
        <div className="border-border grid grid-cols-7 border-b">
          {days.slice(0, 7).map((day) => (
            <div
              key={dayKey(day)}
              className="text-muted-foreground border-border border-l px-2 py-2 text-xs first:border-l-0"
            >
              {weekday.format(day)}
            </div>
          ))}
        </div>
        <div className="grid grid-cols-7">
          {days.map((day) => {
            const { placed, blocks } = layoutDay(
              grouped.get(dayKey(day)) ?? [],
            );
            type Item =
              | { kind: 'event'; at: number; event: CalendarEvent }
              | { kind: 'block'; at: number; block: FrequentBlock };
            const items: Item[] = [
              ...placed.map(({ event, hour }) => ({
                kind: 'event' as const,
                at: hour,
                event,
              })),
              ...blocks.map((block) => ({
                kind: 'block' as const,
                at: block.from,
                block,
              })),
            ].sort((a, b) => a.at - b.at);
            const hidden = items.length - ITEMS_PER_DAY;
            return (
              <div
                key={dayKey(day)}
                data-day={dayKey(day)}
                className={cn(
                  'border-border flex min-h-28 min-w-0 flex-col gap-1 border-t border-l p-1.5 [&:nth-child(-n+7)]:border-t-0 [&:nth-child(7n+1)]:border-l-0',
                  day.getMonth() !== month && 'bg-muted',
                )}
              >
                <button
                  type="button"
                  onClick={() => onOpenDay(day)}
                  className={cn(
                    focusRing,
                    'hover:bg-accent grid size-6 place-items-center self-start rounded-full text-xs font-semibold outline-none',
                    sameDay(day, today) &&
                      'bg-primary text-primary-foreground hover:bg-primary',
                    day.getMonth() !== month &&
                      !sameDay(day, today) &&
                      'text-muted-foreground',
                  )}
                >
                  {day.getDate()}
                </button>
                {items.slice(0, ITEMS_PER_DAY).map((item) =>
                  item.kind === 'event' ? (
                    <button
                      key={`${item.event.schedule_id}:${item.event.at}`}
                      type="button"
                      data-kind={item.event.kind}
                      data-state={item.event.state}
                      onClick={() => onSelectEvent(item.event)}
                      title={`${formatClock(new Date(item.event.at))} ${eventTitle(item.event, t)}`}
                      className={cn(
                        focusRing,
                        eventClass(item.event),
                        'truncate rounded-sm px-1.5 py-0.5 text-left text-xs outline-none hover:brightness-95',
                      )}
                    >
                      {item.event.kind === 'sync' && (
                        <RefreshCw
                          aria-hidden
                          className="me-1 inline size-3 align-[-2px]"
                        />
                      )}
                      <span className="tabular-nums">
                        {formatClock(new Date(item.event.at))}
                      </span>{' '}
                      {eventTitle(item.event, t)}
                    </button>
                  ) : (
                    <button
                      key={item.block.schedule_id}
                      type="button"
                      onClick={() => onSelectBlock(item.block)}
                      title={blockLabel(item.block)}
                      className={cn(
                        focusRing,
                        STATE_CLASS[blockState(item.block.events)],
                        'truncate rounded-sm px-1.5 py-0.5 text-left text-xs outline-none hover:brightness-95',
                      )}
                    >
                      {blockLabel(item.block)}
                    </button>
                  ),
                )}
                {hidden > 0 && (
                  <button
                    type="button"
                    onClick={() => onOpenDay(day)}
                    className={cn(
                      focusRing,
                      'text-muted-foreground hover:text-foreground self-start rounded-sm px-1.5 text-xs outline-none',
                    )}
                  >
                    {t('activity.calendar.more', {
                      count: hidden,
                      formatted: formatCount(hidden),
                    })}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      </Card>
    </div>
  );
}
