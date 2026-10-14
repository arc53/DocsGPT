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

export type CalendarEvent = {
  schedule_id: string;
  name: string | null;
  agent_id: string | null;
  agent_name: string | null;
  trigger_type: 'once' | 'recurring';
  cron: string | null;
  timezone: string | null;
  origin_conversation_id: string | null;
  origin_conversation_name: string | null;
  /** Hourly or finer: drawn as one block per day. */
  frequent: boolean;
  at: string;
  state: EventState;
  run_id?: string;
  trigger_source?: string;
  error_type?: string | null;
  conversation_id?: string | null;
};

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

export type SyncEntry = {
  source_id: string;
  name: string;
  frequency: 'daily' | 'weekly' | 'monthly';
  last_synced_at: string | null;
  /** When its frequency syncs next; null when beat hasn't run it yet. */
  next_sync_at: string | null;
};

export type PlannedWindow = {
  from: string;
  to: string;
  events: CalendarEvent[];
  monitors: MonitorRange[];
  syncs: SyncEntry[];
  truncated: string[];
};

export type CalendarView = 'day' | 'week' | 'month' | 'agenda';
