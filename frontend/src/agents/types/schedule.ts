export type ScheduleTriggerType = 'once' | 'recurring';

export type ScheduleStatus = 'active' | 'paused' | 'completed' | 'cancelled';

export type ScheduleRunStatus =
  | 'pending'
  | 'running'
  | 'success'
  | 'failed'
  | 'skipped'
  | 'timeout';

export type ScheduleRunErrorType =
  | 'auth_expired'
  | 'tool_not_allowed'
  | 'budget_exceeded'
  | 'timeout'
  | 'agent_error'
  | 'internal'
  | 'missed'
  | 'overlap';

export type Schedule = {
  id: string;
  user_id: string;
  // Null for agentless one-time tasks (migration 0011).
  agent_id: string | null;
  trigger_type: ScheduleTriggerType;
  name?: string | null;
  instruction: string;
  status: ScheduleStatus;
  cron?: string | null;
  run_at?: string | null;
  timezone: string;
  next_run_at?: string | null;
  last_run_at?: string | null;
  end_at?: string | null;
  tool_allowlist: string[];
  model_id?: string | null;
  token_budget?: number | null;
  origin_conversation_id?: string | null;
  created_via: 'chat' | 'ui';
  consecutive_failure_count: number;
  created_at: string;
  updated_at: string;
};

export type ScheduleRun = {
  id: string;
  schedule_id: string;
  user_id: string;
  // Null for runs of agentless schedules (migration 0011).
  agent_id: string | null;
  status: ScheduleRunStatus;
  scheduled_for: string;
  trigger_source: 'cron' | 'manual';
  started_at?: string | null;
  finished_at?: string | null;
  output?: string | null;
  output_truncated: boolean;
  error?: string | null;
  error_type?: ScheduleRunErrorType | null;
  prompt_tokens: number;
  generated_tokens: number;
  conversation_id?: string | null;
  message_id?: string | null;
  celery_task_id?: string | null;
  created_at: string;
  updated_at: string;
};

export type ScheduleListResponse = { schedules: Schedule[] };
export type ScheduleResponse = { schedule: Schedule };
export type ScheduleRunListResponse = {
  runs: ScheduleRun[];
  limit: number;
  offset: number;
};
export type ScheduleRunResponse = { run: ScheduleRun };

export type ScheduleCreatePayload = {
  instruction: string;
  trigger_type?: ScheduleTriggerType;
  cron?: string;
  run_at?: string; // ISO 8601 UTC; set for trigger_type === 'once'
  timezone?: string;
  name?: string;
  end_at?: string;
  tool_allowlist?: string[];
  model_id?: string;
  token_budget?: number;
};

export type ScheduleUpdatePayload = Partial<ScheduleCreatePayload>;
