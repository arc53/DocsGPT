/** The Activity › Now snapshot (`GET /api/activity/now`, docsgpt/activity/now.py). */

export type RunningKind =
  'chat' | 'api' | 'job' | 'schedule' | 'workflow' | 'webhook' | 'ingest';

/** Where a running workflow is (`workflow_runs.progress`). */
export type WorkflowProgress = {
  /** Steps finished before the current one. */
  done: number;
  /** Steps in the run; null when the workflow branches. */
  total: number | null;
  current: {
    node_id: string;
    title?: string | null;
    type: string;
    started_at?: string | null;
  } | null;
};

export type RunningItem = {
  kind: RunningKind;
  id: string;
  title: string | null;
  agent_id?: string | null;
  agent_name?: string | null;
  started_at?: string | null;
  conversation_id?: string | null;
  conversation_name?: string | null;
  /** chat */
  message_id?: string;
  status?: string;
  /** api: one agent's API requests being answered, as one row. */
  count?: number;
  /** chat / schedule / webhook: a workflow agent's run is folded in. */
  workflow?: boolean;
  /** workflow, or a host a workflow run is folded into: the step it is on. */
  workflow_progress?: WorkflowProgress | null;
  /** job */
  job_id?: string;
  tool_name?: string | null;
  /** The tool as the user knows it (its own or the catalog's name). */
  tool_label?: string | null;
  action_name?: string | null;
  job_kind?: string | null;
  status_message?: string | null;
  /** job / ingest: done so far, 0 to 1 (null when the job prints none). */
  progress?: number | null;
  output_tail?: string | null;
  cancel_requested?: boolean;
  /** schedule */
  run_id?: string;
  schedule_id?: string;
  trigger_source?: string;
  scheduled_for?: string | null;
  /** ingest */
  source_id?: string;
  /** What started it: `upload`, `sync` or `reingest` (null when unknown). */
  operation?: string | null;
  /** `reading` the content, then `embedding` its chunks. */
  stage?: 'reading' | 'embedding';
  embedded_chunks?: number;
  total_chunks?: number;
};

export type ApprovalItem = {
  kind: 'approval';
  id: string;
  conversation_id: string;
  title: string | null;
  agent_id?: string | null;
  agent_name?: string | null;
  tools: string[];
  created_at?: string | null;
  expires_at?: string | null;
};

export type PausedScheduleItem = {
  kind: 'schedule_paused';
  id: string;
  schedule_id: string;
  title: string | null;
  agent_id?: string | null;
  agent_name?: string | null;
  failures: number;
  last_error_type?: string | null;
  last_error?: string | null;
  last_failed_at?: string | null;
};

export type NeedsYouItem = ApprovalItem | PausedScheduleItem;

/** A schedule due in the next day. */
export type ScheduleUpNext = {
  kind: 'schedule';
  id: string;
  schedule_id: string;
  name: string | null;
  agent_id?: string | null;
  agent_name?: string | null;
  trigger_type: 'once' | 'recurring';
  cron?: string | null;
  timezone?: string | null;
  next_run_at: string;
  origin_conversation_id?: string | null;
  origin_conversation_name?: string | null;
  runs_in_window: number;
};

/** One sync frequency's batch of sources due in the next day (docsgpt/activity/syncs.py). */
export type SyncUpNext = {
  kind: 'sync';
  id: string;
  frequency: 'daily' | 'weekly' | 'monthly';
  next_run_at: string;
  /** Names of the sources that sync. */
  sources: string[];
  /** Names of the sources that need a reconnect first. */
  blocked: string[];
  runs_in_window: number;
};

export type UpNextItem = ScheduleUpNext | SyncUpNext;

export type NowSnapshot = {
  running: RunningItem[];
  needs_you: NeedsYouItem[];
  up_next: UpNextItem[];
  approval_conversations: string[];
  failed_conversations: string[];
  stats: {
    next_24h: number;
    failed_24h: number;
  };
};
