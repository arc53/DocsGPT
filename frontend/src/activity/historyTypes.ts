/** Activity › History rows (`GET /api/activity/history`, docsgpt/activity/history.py). */

export type HistoryKind =
  'schedule' | 'webhook' | 'workflow' | 'job' | 'monitor';

export type HistoryStatus =
  'success' | 'failed' | 'timeout' | 'skipped' | 'cancelled';

export type HistoryRun = {
  kind: HistoryKind;
  id: string;
  title: string | null;
  agent_id: string | null;
  agent_name: string | null;
  conversation_id: string | null;
  conversation_name: string | null;
  trigger: string | null;
  status: HistoryStatus;
  at: string;
  duration_ms: number | null;
  tokens: number | null;
  schedule_id: string | null;
  trace_id: string | null;
  workflow_run_id: string | null;
  error_type: string | null;
  error: string | null;
};

export type HistoryPage = { runs: HistoryRun[]; has_more: boolean };

export type HistoryQuery = {
  kind?: HistoryKind;
  status?: HistoryStatus;
  q?: string;
  days?: number;
  limit?: number;
  offset?: number;
};
