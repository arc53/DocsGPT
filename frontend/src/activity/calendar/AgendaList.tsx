import { Clock, RefreshCw, Repeat } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { ListRow, ListRows } from '@/components/ui/list-row';
import { SectionHeader } from '@/components/ui/section-header';

import {
  formatClock,
  formatCount,
  headingLocale,
} from '../../utils/dateTimeUtils';
import { dayKey, sameDay, addDays } from './dates';
import {
  blockCount,
  blockState,
  byDay,
  eventCount,
  layoutDay,
  type FrequentBlock,
} from './layout';
import { eventTitle, syncSummary } from './labels';
import MonitorChips from './MonitorChips';
import type { CalendarEvent, EventState, MonitorRange } from './types';

const BADGE: Partial<
  Record<EventState, 'success' | 'destructive' | 'info' | 'warning' | 'neutral'>
> = {
  success: 'success',
  failed: 'destructive',
  timeout: 'destructive',
  running: 'info',
  pending: 'info',
  skipped: 'neutral',
  paused: 'neutral',
  missed: 'warning',
};

export type AgendaListProps = {
  days: Date[];
  events: CalendarEvent[];
  monitors: MonitorRange[];
  now: number;
  onSelectEvent: (event: CalendarEvent) => void;
  onSelectBlock: (block: FrequentBlock) => void;
  onSelectMonitor: (monitor: MonitorRange) => void;
};

/**
 * The calendar as a list of days, the phone's default: each day's slots by
 * time, a frequent schedule as one row with how many of its runs are done.
 */
export default function AgendaList({
  days,
  events,
  monitors,
  now,
  onSelectEvent,
  onSelectBlock,
  onSelectMonitor,
}: AgendaListProps) {
  const { t, i18n } = useTranslation();
  const grouped = byDay(events);
  const today = new Date(now);
  // "Mon 12 Oct": English day-first, every other language in its own words.
  const locale = headingLocale(i18n.language);
  const dayName = new Intl.DateTimeFormat(locale, { weekday: 'short' });
  const date = new Intl.DateTimeFormat(locale, {
    day: 'numeric',
    month: 'short',
  });
  const filled = days.filter((day) => grouped.has(dayKey(day)));

  const heading = (day: Date) => {
    const label = `${dayName.format(day)} ${date.format(day)}`;
    if (sameDay(day, today))
      return `${t('activity.calendar.today')} · ${label}`;
    if (sameDay(day, addDays(today, 1)))
      return `${t('activity.calendar.tomorrow')} · ${label}`;
    return label;
  };

  /** "3 of 12 runs done": how far a frequent schedule's day has got. */
  const doneLabel = (block: FrequentBlock) => {
    const done = block.events
      .filter((e) => e.state !== 'planned' && e.state !== 'paused')
      .reduce((sum, e) => sum + eventCount(e), 0);
    const count = blockCount(block);
    return t('activity.calendar.blockDone', {
      done: formatCount(done),
      count,
      formatted: formatCount(count),
    });
  };

  const stateBadge = (state: EventState) =>
    BADGE[state] ? (
      <Badge variant={BADGE[state]}>
        {t(`activity.calendar.state.${state}`)}
      </Badge>
    ) : null;

  return (
    <div className="flex flex-col gap-6">
      <MonitorChips monitors={monitors} onSelectMonitor={onSelectMonitor} />
      {filled.length === 0 ? (
        <Card variant="subtle" padding="lg">
          <EmptyState
            size="sm"
            illustration="none"
            title={t('activity.calendar.empty')}
          />
        </Card>
      ) : (
        filled.map((day) => {
          const { placed, blocks } = layoutDay(grouped.get(dayKey(day)) ?? []);
          type Row =
            | { at: number; event: CalendarEvent }
            | { at: number; block: FrequentBlock };
          const rows: Row[] = [
            ...placed.map(({ event, hour }) => ({ at: hour, event })),
            ...blocks.map((block) => ({ at: block.from, block })),
          ].sort((a, b) => a.at - b.at);
          return (
            <section key={dayKey(day)} className="flex flex-col gap-2">
              <SectionHeader as="h2" size="sm" title={heading(day)} />
              <Card variant="subtle" padding="none" className="overflow-hidden">
                <ListRows>
                  {rows.map((row) =>
                    'event' in row ? (
                      <ListRow
                        key={`${row.event.schedule_id}:${row.event.at}`}
                        interactive
                        asChild
                        leading={
                          <span className="text-foreground w-12 shrink-0 text-xs font-medium tabular-nums">
                            {formatClock(new Date(row.event.at))}
                          </span>
                        }
                        data-kind={row.event.kind}
                        title={eventTitle(row.event, t)}
                        description={
                          row.event.kind === 'sync'
                            ? syncSummary(row.event, t)
                            : (row.event.agent_name ??
                              t('activity.schedules.createdInChat'))
                        }
                        trailing={
                          row.event.kind === 'sync' ? (
                            <RefreshCw
                              aria-hidden
                              className="text-muted-foreground size-3.5"
                            />
                          ) : (
                            (stateBadge(row.event.state) ??
                            (row.event.trigger_type === 'once' ? (
                              <Clock
                                aria-hidden
                                className="text-muted-foreground size-3.5"
                              />
                            ) : (
                              <Repeat
                                aria-hidden
                                className="text-muted-foreground size-3.5"
                              />
                            )))
                          )
                        }
                      >
                        <button
                          type="button"
                          onClick={() => onSelectEvent(row.event)}
                        />
                      </ListRow>
                    ) : (
                      <ListRow
                        key={row.block.schedule_id}
                        interactive
                        asChild
                        leading={
                          <span className="text-foreground w-12 shrink-0 text-xs font-medium tabular-nums">
                            {`${formatClock(new Date(row.block.events[0].at))}`}
                          </span>
                        }
                        title={row.block.name ?? ''}
                        description={doneLabel(row.block)}
                        trailing={stateBadge(blockState(row.block.events))}
                      >
                        <button
                          type="button"
                          onClick={() => onSelectBlock(row.block)}
                        />
                      </ListRow>
                    ),
                  )}
                </ListRows>
              </Card>
            </section>
          );
        })
      )}
    </div>
  );
}
