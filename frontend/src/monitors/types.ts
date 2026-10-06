/** A monitor as `/api/monitors` lists it (never its state, secrets or tokens). */
export type MonitorStatus = 'active' | 'paused' | 'completed' | 'cancelled';

export type MonitorSourceType =
  'webpage' | 'tool' | 'ingest' | 'webhook' | 'approval';

export interface MonitorLink {
  id: string;
  kind: 'webhook' | 'approval';
  /** Whether the link still works. */
  state?: 'live' | 'expired' | 'revoked' | 'used_up';
  signature: string | null;
  expires_at: string | null;
  hit_count: number;
  max_hits: number;
  last_hit_at: string | null;
  revoked: boolean;
  decided: boolean;
}

export interface Monitor {
  monitor_id: string;
  description: string;
  status: MonitorStatus;
  source_type: MonitorSourceType;
  watching: string;
  /** The URL, tool call or source id watched; none for links. */
  target: string | null;
  interval: string | null;
  interval_seconds: number | null;
  conversation_id: string | null;
  agent_id: string | null;
  created_at: string | null;
  expires_at: string | null;
  next_check_at: string | null;
  last_checked_at: string | null;
  last_changed_at: string | null;
  last_woken_at: string | null;
  check_count: number;
  wake_count: number;
  max_wakes: number;
  wakes_left: number;
  last_error: string | null;
  paused_reason: string | null;
  approval_required: boolean;
  links?: MonitorLink[];
}

/** The `monitor.updated` SSE payload. */
export interface MonitorUpdatedPayload {
  monitor_id: string;
  status: MonitorStatus;
  wakes_left: number;
  last_checked_at: string | null;
  conversation_id: string | null;
  check_count?: number;
  last_error?: string | null;
}

/** What the public approval page shows. */
export interface ApprovalView {
  question: string | null;
  details: string | null;
  options: string[];
  allow_comment: boolean;
  expires_at: string | null;
  decided: boolean;
  decision: string | null;
  decided_at: string | null;
  waiting: boolean;
}
