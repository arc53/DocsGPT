/** The Activity › Calendar window (`GET /api/activity/planned`, docsgpt/activity/planned.py). */

export type EventState =
  | 'planned'
  | 'paused'
  | 'pending'
  | 'running'
  | 'success'
  | 'failed'
  | 'skipped'
  | 'timeout'
  /** A past slot of an active schedule that never got a run. */
  | 'missed';

type EventCommon = {
  /** The series: a schedule's id, or `sync:<frequency>` for a sync batch. */
  schedule_id: string;
  name: string | null;
  agent_id: string | null;
  agent_name: string | null;
  /** Hourly or finer: drawn as one block per day. */
  frequent: boolean;
  at: string;
  state: EventState;
  /**
   * A frequent schedule over the server's cap is summed up per day: one event
   * per state, standing for `count` slots from `at` to `until`.
   */
  count?: number;
  until?: string;
};

/** A schedule's slot: planned, or a run with its status. */
export type ScheduleEvent = EventCommon & {
  kind: 'schedule';
  trigger_type: 'once' | 'recurring';
  cron: string | null;
  timezone: string | null;
  origin_conversation_id: string | null;
  origin_conversation_name: string | null;
  run_id?: string;
  trigger_source?: string;
  error_type?: string | null;
  conversation_id?: string | null;
};

export type SyncSource = {
  id: string;
  name: string;
  type: string | null;
  /** It needs its connection reconnected before it can sync. */
  blocked: boolean;
  last_synced_at: string | null;
};

/** One sync frequency's batch, each time it fires (future only). */
export type SyncEvent = EventCommon & {
  kind: 'sync';
  frequency: 'daily' | 'weekly' | 'monthly';
  sources: SyncSource[];
};

export type CalendarEvent = ScheduleEvent | SyncEvent;

export type MonitorRange = {
  monitor_id: string;
  description: string | null;
  source_type: string;
  status: 'active' | 'paused';
  interval_seconds: number | null;
  conversation_id: string | null;
  starts_at: string | null;
  ends_at: string | null;
  last_checked_at: string | null;
};

export type PlannedWindow = {
  from: string;
  to: string;
  events: CalendarEvent[];
  monitors: MonitorRange[];
  truncated: string[];
};

export type CalendarView = 'day' | 'week' | 'month' | 'agenda';
