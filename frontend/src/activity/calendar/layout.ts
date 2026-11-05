import { dayKey, hourOf } from './dates';
import type { CalendarEvent, EventState, ScheduleEvent } from './types';

/** A frequent schedule's runs of one day, drawn as one tall block. */
export type FrequentBlock = {
  schedule_id: string;
  name: string | null;
  events: ScheduleEvent[];
  /** Hours since local midnight of the first and last run. */
  from: number;
  to: number;
};

/** A one-off slot with its lane among slots that overlap it. */
export type PlacedEvent = {
  event: CalendarEvent;
  hour: number;
  lane: number;
  lanes: number;
};

/** How long a slot is drawn, in hours (runs have no planned length). */
export const SLOT_HOURS = 0.5;

/** The colour of a slot by its state (DESIGN.md: status colour on fills only). */
export const STATE_CLASS: Record<EventState, string> = {
  planned: 'bg-secondary text-secondary-foreground border-l-2 border-primary',
  pending: 'bg-info/10 text-foreground border-l-2 border-info',
  running: 'bg-info/10 text-foreground border-l-2 border-info',
  success: 'bg-success/10 text-foreground border-l-2 border-success',
  failed: 'bg-destructive/10 text-foreground border-l-2 border-destructive',
  timeout: 'bg-destructive/10 text-foreground border-l-2 border-destructive',
  skipped:
    'bg-background text-muted-foreground border border-dashed border-muted-foreground',
  paused:
    'bg-background text-muted-foreground border border-dashed border-muted-foreground',
  // Dashed like a skip, amber because nobody chose it: the scheduler was down.
  missed:
    'bg-background text-muted-foreground border border-dashed border-warning',
};

/** A knowledge sync: its own dashed fill, not a run status (it has none yet). */
export const SYNC_CLASS =
  'bg-muted text-foreground border border-dashed border-muted-foreground';

/** An event's look: a sync's, else its state's. */
export function eventClass(event: CalendarEvent): string {
  return event.kind === 'sync' ? SYNC_CLASS : STATE_CLASS[event.state];
}

/** How many slots an event stands for: a summed-up day's count, else one. */
export const eventCount = (event: CalendarEvent): number => event.count ?? 1;

/** How many slots a frequent block's day has. */
export const blockCount = (block: FrequentBlock): number =>
  block.events.reduce((sum, event) => sum + eventCount(event), 0);

/** The worst state among a block's runs, which colours the block. */
export function blockState(events: CalendarEvent[]): EventState {
  const order: EventState[] = [
    'failed',
    'timeout',
    'missed',
    'running',
    'pending',
    'planned',
    'success',
    'paused',
    'skipped',
  ];
  const present = new Set(events.map((e) => e.state));
  return order.find((state) => present.has(state)) ?? 'planned';
}

/** Events bucketed by their local day. */
export function byDay(events: CalendarEvent[]): Map<string, CalendarEvent[]> {
  const out = new Map<string, CalendarEvent[]>();
  for (const event of events) {
    const key = dayKey(new Date(event.at));
    const list = out.get(key);
    if (list) list.push(event);
    else out.set(key, [event]);
  }
  return out;
}

/**
 * Splits a day's events into one-off slots and frequent blocks, and gives
 * each slot a lane so slots that overlap sit side by side.
 */
export function layoutDay(events: CalendarEvent[]): {
  placed: PlacedEvent[];
  blocks: FrequentBlock[];
} {
  const blocks = new Map<string, FrequentBlock>();
  const points: { event: CalendarEvent; hour: number }[] = [];
  for (const event of events) {
    const hour = hourOf(new Date(event.at));
    if (event.frequent && event.kind === 'schedule') {
      const last = event.until ? hourOf(new Date(event.until)) : hour;
      const block = blocks.get(event.schedule_id);
      if (block) {
        block.events.push(event);
        block.from = Math.min(block.from, hour);
        block.to = Math.max(block.to, last);
      } else {
        blocks.set(event.schedule_id, {
          schedule_id: event.schedule_id,
          name: event.name,
          events: [event],
          from: hour,
          to: last,
        });
      }
    } else {
      points.push({ event, hour });
    }
  }
  points.sort((a, b) => a.hour - b.hour);

  // Greedy lanes over clusters of overlapping slots.
  const placed: PlacedEvent[] = [];
  let cluster: PlacedEvent[] = [];
  let laneEnds: number[] = [];
  let clusterEnd = -1;
  const flush = () => {
    for (const item of cluster) item.lanes = laneEnds.length;
    placed.push(...cluster);
    cluster = [];
    laneEnds = [];
  };
  for (const point of points) {
    if (point.hour >= clusterEnd) flush();
    let lane = laneEnds.findIndex((end) => end <= point.hour);
    if (lane === -1) {
      lane = laneEnds.length;
      laneEnds.push(0);
    }
    laneEnds[lane] = point.hour + SLOT_HOURS;
    clusterEnd = Math.max(clusterEnd, point.hour + SLOT_HOURS);
    cluster.push({ ...point, lane, lanes: 1 });
  }
  flush();
  return { placed, blocks: [...blocks.values()] };
}

/** Default first and last hour a day grid shows, widened to fit its events. */
export const DEFAULT_HOURS: [number, number] = [7, 19];

export function hourRange(events: CalendarEvent[]): [number, number] {
  let [first, last] = DEFAULT_HOURS;
  for (const event of events) {
    const hour = hourOf(new Date(event.at));
    const end = event.until ? hourOf(new Date(event.until)) : hour;
    first = Math.min(first, Math.floor(hour));
    last = Math.max(last, Math.ceil(end + SLOT_HOURS));
  }
  return [Math.max(0, first), Math.min(24, last)];
}
